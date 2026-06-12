"""Functional tests for desktop automation (Phase 1–3)."""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

BASE = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/v1"
OPENAPI = BASE.replace("/api/v1", "") + "/openapi.json"
DEVICE_ID = f"test-sidecar-{uuid.uuid4().hex[:8]}"

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    line = f"  [{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)


async def sidecar_poll(client: httpx.AsyncClient, headers: dict) -> list[dict]:
    resp = await client.get(
        "/desktop-automation/sidecar/poll",
        headers=headers,
        params={"device_id": DEVICE_ID},
    )
    resp.raise_for_status()
    return resp.json().get("tasks") or []


async def sidecar_complete(
    client: httpx.AsyncClient,
    headers: dict,
    task_id: str,
    *,
    status: str = "completed",
    output_data: dict | None = None,
    **extra,
) -> dict:
    payload = {
        "status": status,
        "output_data": output_data or {"mode": "mock", "ok": True},
        "error_message": None,
        **extra,
    }
    resp = await client.post(
        f"/desktop-automation/sidecar/tasks/{task_id}/complete",
        headers=headers,
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()


async def wait_task_status(
    client: httpx.AsyncClient,
    headers: dict,
    task_id: str,
    expected: str,
    timeout_s: float = 15.0,
) -> dict | None:
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = await client.get("/desktop-automation/tasks", headers=headers)
        resp.raise_for_status()
        for t in resp.json():
            if t["id"] == task_id and t["status"] == expected:
                return t
        await asyncio.sleep(0.3)
    return None


async def main() -> int:
    print("=== Desktop Automation Functional Test ===")
    print(f"  base: {BASE.replace('/api/v1', '')}\n")
    demo_id: str | None = None
    demo_name = f"ft-demo-{uuid.uuid4().hex[:6]}"

    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        # Health
        try:
            health = await client.get(BASE.replace("/api/v1", "") + "/health")
            record("health", health.status_code == 200, str(health.status_code))
        except Exception as exc:
            record("health", False, str(exc))
            print("\nBackend not reachable on :8000. Start uvicorn first.")
            return 1

        # OpenAPI routes
        try:
            spec = (await client.get(OPENAPI)).json()
            paths = spec.get("paths", {})
            required = [
                "/api/v1/desktop-automation/demos",
                "/api/v1/desktop-automation/tasks/replay",
                "/api/v1/desktop-automation/tasks/awaiting-confirmation",
                "/api/v1/desktop-automation/tasks/{task_id}/confirm",
                "/api/v1/desktop-automation/tasks/{task_id}/reject",
                "/api/v1/desktop-automation/sidecar/register",
                "/api/v1/desktop-automation/sidecar/poll",
                "/api/v1/desktop-automation/demos/{demo_id}/deposit",
            ]
            missing = [p for p in required if p not in paths]
            record("openapi desktop routes", not missing, ", ".join(missing) if missing else "ok")
        except Exception as exc:
            record("openapi desktop routes", False, str(exc))

        # Auth
        try:
            login = await client.post("/auth/login", json={"login": "admin", "password": "admin123"})
            login.raise_for_status()
            token = login.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            record("auth login", True)
        except Exception as exc:
            record("auth login", False, str(exc))
            return 1

        # Desktop operator agent
        try:
            agents = (await client.get("/agents/", headers=headers)).json()
            operator = next((a for a in agents if a.get("name") == "桌面操作员"), None)
            tools = (operator or {}).get("tools_config") or []
            tool_names = {t.get("tool_name") for t in tools}
            has_tools = {"desktop_list_demos", "desktop_replay", "desktop_capture"}.issubset(tool_names)
            record("seed agent 桌面操作员", operator is not None and has_tools, f"tools={sorted(tool_names)}")
        except Exception as exc:
            record("seed agent 桌面操作员", False, str(exc))

        # Register sidecar
        try:
            reg = await client.post(
                "/desktop-automation/sidecar/register",
                headers=headers,
                json={
                    "device_id": DEVICE_ID,
                    "device_name": "func-test-sidecar",
                    "hostname": "test-host",
                    "platform": "Windows",
                },
            )
            reg.raise_for_status()
            record("sidecar register", reg.json().get("online") is True)
        except Exception as exc:
            record("sidecar register", False, str(exc))
            return 1

        # Sidecar status
        try:
            st = (await client.get("/desktop-automation/sidecar/status", headers=headers)).json()
            record("sidecar status online", st.get("online") is True, st.get("device_name", ""))
        except Exception as exc:
            record("sidecar status online", False, str(exc))

        # Create demo
        try:
            created = await client.post(
                "/desktop-automation/demos",
                headers=headers,
                json={
                    "name": demo_name,
                    "description": "functional test demo",
                    "app_name": "Notepad",
                    "tags": ["test"],
                },
            )
            created.raise_for_status()
            demo_id = created.json()["id"]
            record("create demo", bool(demo_id), demo_name)
        except Exception as exc:
            record("create demo", False, str(exc))

        # Replay without confirm -> awaiting_confirmation
        gate_task_id: str | None = None
        try:
            replay = await client.post(
                "/desktop-automation/tasks/replay",
                headers=headers,
                json={"demo_id": demo_id, "confirmed": False},
            )
            replay.raise_for_status()
            body = replay.json()
            gate_task_id = body["id"]
            ok = body["status"] == "awaiting_confirmation"
            record("replay gate (awaiting_confirmation)", ok, body["status"])
        except Exception as exc:
            record("replay gate (awaiting_confirmation)", False, str(exc))

        # Poll should NOT pick awaiting task
        try:
            polled = await sidecar_poll(client, headers)
            ids = {t["id"] for t in polled}
            record("poll skips unconfirmed", gate_task_id not in ids if gate_task_id else False, f"polled={len(polled)}")
        except Exception as exc:
            record("poll skips unconfirmed", False, str(exc))

        # List awaiting
        try:
            awaiting = (await client.get("/desktop-automation/tasks/awaiting-confirmation", headers=headers)).json()
            ids = {t["id"] for t in awaiting}
            record("list awaiting-confirmation", gate_task_id in ids if gate_task_id else False, f"count={len(awaiting)}")
        except Exception as exc:
            record("list awaiting-confirmation", False, str(exc))

        # Reject one pending gate task (create another first for confirm flow)
        reject_task_id: str | None = None
        try:
            replay2 = await client.post(
                "/desktop-automation/tasks/replay",
                headers=headers,
                json={"demo_id": demo_id, "confirmed": False},
            )
            replay2.raise_for_status()
            reject_task_id = replay2.json()["id"]
            rejected = await client.post(
                f"/desktop-automation/tasks/{reject_task_id}/reject",
                headers=headers,
            )
            rejected.raise_for_status()
            record("reject task", rejected.json()["status"] == "cancelled", rejected.json()["status"])
        except Exception as exc:
            record("reject task", False, str(exc))

        # Confirm gate task
        try:
            confirmed = await client.post(
                f"/desktop-automation/tasks/{gate_task_id}/confirm",
                headers=headers,
            )
            confirmed.raise_for_status()
            record("confirm task", confirmed.json()["status"] == "pending", confirmed.json()["status"])
        except Exception as exc:
            record("confirm task", False, str(exc))

        # Sidecar poll + complete confirmed replay
        try:
            polled = await sidecar_poll(client, headers)
            target = next((t for t in polled if t["id"] == gate_task_id), None)
            if not target:
                record("poll picks confirmed task", False, "task not in poll")
            else:
                done = await sidecar_complete(
                    client,
                    headers,
                    gate_task_id,
                    output_data={"mode": "mock", "demo_name": demo_name, "steps": 3},
                )
                record("sidecar complete replay", done["status"] == "completed", done["status"])
        except Exception as exc:
            record("sidecar complete replay", False, str(exc))

        # Replay with confirmed=true -> pending immediately
        direct_id: str | None = None
        try:
            direct = await client.post(
                "/desktop-automation/tasks/replay",
                headers=headers,
                json={"demo_id": demo_id, "confirmed": True},
            )
            direct.raise_for_status()
            direct_id = direct.json()["id"]
            ok = direct.json()["status"] == "pending"
            record("replay confirmed bypasses gate", ok, direct.json()["status"])
            polled = await sidecar_poll(client, headers)
            if any(t["id"] == direct_id for t in polled):
                await sidecar_complete(client, headers, direct_id)
        except Exception as exc:
            record("replay confirmed bypasses gate", False, str(exc))

        # Deposit to knowledge (no LLM to keep test fast)
        try:
            dep = await client.post(
                f"/desktop-automation/demos/{demo_id}/deposit",
                headers=headers,
                json={"target": "knowledge", "use_llm": False},
            )
            dep.raise_for_status()
            body = dep.json()
            record(
                "deposit demo -> knowledge",
                body.get("target") == "knowledge" and bool(body.get("document_id")),
                f"doc={body.get('document_id', '')[:8]}",
            )
        except Exception as exc:
            record("deposit demo -> knowledge", False, str(exc))

        # OpenAdapt runner unit (local import)
        try:
            from app.core.desktop.openadapt_runner import create_runner

            runner = create_runner()
            cap = runner.start_capture({})
            demo_capture_name = f"{demo_name}-capture"
            stop = runner.stop_capture(demo_capture_name, {})
            rep = runner.replay(demo_capture_name, "test instructions")
            ok = (
                cap.get("mode") == "mock"
                and stop.get("demo_name") == demo_capture_name
                and rep.get("mode") == "mock"
                and not rep.get("error")
            )
            record("OpenAdaptRunner mock cycle", ok, f"mode={runner.mode}")
        except Exception as exc:
            record("OpenAdaptRunner mock cycle", False, str(exc))

        # Cleanup demo
        if demo_id:
            try:
                await client.delete(f"/desktop-automation/demos/{demo_id}", headers=headers)
                record("cleanup demo", True)
            except Exception as exc:
                record("cleanup demo", False, str(exc))

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n=== Summary: {passed} passed, {failed} failed / {len(RESULTS)} total ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
