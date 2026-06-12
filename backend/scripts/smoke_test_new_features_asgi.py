"""In-process ASGI smoke test (does not require killing port 8000)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from app.main import app

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    line = f"  [{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)


async def main() -> int:
    print("=== ASGI In-Process Smoke Test (new features) ===\n")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1", timeout=180.0) as client:
        # Routes registered on app
        paths = [getattr(r, "path", "") for r in app.routes if getattr(r, "path", None)]
        deposit_ok = any("suggest-deposit" in p for p in paths) and any("deposit/confirm" in p for p in paths)
        record("app routes (deposit)", deposit_ok, str([p for p in paths if "deposit" in p]))

        login = await client.post("/auth/login", json={"login": "admin", "password": "admin123"})
        record("auth login", login.status_code == 200, str(login.status_code))
        if login.status_code != 200:
            return 1
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        models = await client.get("/models/configs", headers=headers)
        configs = models.json() if models.status_code == 200 else []
        model_config_id = next((c["id"] for c in configs if c.get("is_default")), configs[0]["id"] if configs else None)
        record("models list", models.status_code == 200 and len(configs) > 0, f"count={len(configs)}")

        mb = await client.post(
            "/auth/me/mailbox",
            headers=headers,
            json={
                "email": "smoke-asgi@byd.com",
                "mailbox_password": "dummy",
                "imap_host": "imap.byd.com",
                "imap_port": 1993,
                "imap_use_ssl": True,
            },
        )
        record("mailbox connector preset", mb.status_code in (200, 201), str(mb.status_code))

        conv = await client.post(
            "/chat/conversations",
            headers=headers,
            json={
                "title": "ASGI冒烟",
                "model_config_id": model_config_id,
                "connector_id": "wecom-mail",
            },
        )
        record(
            "conversation model+connector",
            conv.status_code == 201 and conv.json().get("connector_id") == "wecom-mail",
            conv.json().get("id", conv.text)[:40] if conv.status_code == 201 else conv.text[:80],
        )
        conv_id = conv.json()["id"] if conv.status_code == 201 else None

        if conv_id:
            suggest = await client.post(
                f"/chat/conversations/{conv_id}/suggest-deposit",
                headers=headers,
                json={"lang": "zh"},
            )
            record("suggest-deposit endpoint", suggest.status_code == 200, f"status={suggest.status_code}")
            if suggest.status_code == 200:
                sdata = suggest.json()
                record(
                    "suggest-deposit payload",
                    "worth_deposit" in sdata,
                    f"worth={sdata.get('worth_deposit')} n={len(sdata.get('suggestions') or [])}",
                )

            msg = await client.post(
                f"/chat/conversations/{conv_id}/messages",
                headers=headers,
                json={
                    "message": "测试消息",
                    "stream": False,
                    "model_config_id": model_config_id,
                    "connector_id": "wecom-mail",
                },
            )
            llm_ok = msg.status_code == 200
            record(
                "chat message + model override",
                llm_ok or msg.status_code == 502,
                "OK" if llm_ok else f"502 LLM unreachable (expected offline)",
            )

        agents = await client.get("/agents/", headers=headers, params={"lang": "zh"})
        record("agents list", agents.status_code == 200, f"count={len(agents.json())}")

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n=== Summary: {passed} passed, {failed} failed / {len(RESULTS)} total ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
