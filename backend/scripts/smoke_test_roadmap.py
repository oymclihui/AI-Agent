#!/usr/bin/env python3
"""Extended smoke test — roadmap features (org, integrations, employees)."""
from __future__ import annotations

import io
import os
import sys
import uuid

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API = f"{BASE}/api/v1"
ADMIN_LOGIN = os.environ.get("SMOKE_ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.environ.get("SMOKE_ADMIN_PASSWORD", "admin123")

PASS, FAIL = 0, 0
failures: list[str] = []


def ok(name: str, detail: str = "") -> None:
    global PASS
    PASS += 1
    print(f"[PASS] {name}  ->  {detail}")


def fail(name: str, detail: str = "") -> None:
    global FAIL
    FAIL += 1
    failures.append(f"{name}: {detail}")
    print(f"[FAIL] {name}  ->  {detail}")


def detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict) and "detail" in body:
            return str(body["detail"])[:200]
        return str(body)[:200]
    except Exception:
        return resp.text[:200]


def main() -> int:
    print(f"Extended smoke test: {BASE}\n")
    client = httpx.Client(timeout=60.0)

    try:
        r = client.get(f"{BASE}/health")
        r.raise_for_status()
        ok("health", r.json().get("status", ""))
    except Exception as exc:
        fail("health", str(exc))
        return 1

    try:
        r = client.post(f"{API}/auth/login", json={"login": ADMIN_LOGIN, "password": ADMIN_PASSWORD})
        r.raise_for_status()
        auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
        ok("auth/login", ADMIN_LOGIN)
    except Exception as exc:
        fail("auth/login", str(exc))
        return 1

    # Integrations
    try:
        r = client.get(f"{API}/integrations/status")
        r.raise_for_status()
        body = r.json()
        ok("integrations/status", f"feishu={body.get('feishu', {}).get('enabled')}")
    except Exception as exc:
        fail("integrations/status", str(exc))

    try:
        r = client.get(f"{API}/integrations/admin/status", headers=auth)
        r.raise_for_status()
        ok("integrations/admin/status", "org admin ok")
    except Exception as exc:
        fail("integrations/admin/status", str(exc))

    # Organization RBAC
    try:
        r = client.get(f"{API}/organization/departments", headers=auth)
        r.raise_for_status()
        ok("organization/departments", f"count={len(r.json())}")
    except Exception as exc:
        fail("organization/departments", str(exc))

    try:
        r = client.get(f"{API}/organization/users", headers=auth)
        r.raise_for_status()
        users = r.json()
        ok("organization/users", f"count={len(users)}")
    except Exception as exc:
        fail("organization/users", str(exc))

    try:
        r = client.get(f"{API}/organization/roles", headers=auth)
        r.raise_for_status()
        ok("organization/roles", f"count={len(r.json())}")
    except Exception as exc:
        fail("organization/roles", str(exc))

    preview_user = users[0]["id"] if users else None
    if preview_user:
        try:
            r = client.get(f"{API}/organization/permissions/preview/{preview_user}", headers=auth)
            r.raise_for_status()
            ok("organization/permissions/preview", r.json().get("data_scope", "ok"))
        except Exception as exc:
            fail("organization/permissions/preview", str(exc))
    else:
        fail("organization/permissions/preview", "no users")

    # Employees + task types
    try:
        r = client.get(f"{API}/employees/", headers=auth)
        r.raise_for_status()
        employees = r.json()
        ok("employees/list", f"count={len(employees)}")
    except Exception as exc:
        fail("employees/list", str(exc))
        employees = []

    try:
        r = client.get(f"{API}/employees/scheduler/status", headers=auth)
        r.raise_for_status()
        ok("employees/scheduler/status", str(r.json().get("running", r.json()))[:60])
    except Exception as exc:
        fail("employees/scheduler/status", str(exc))

    # Workflows list (for workflow task type)
    try:
        r = client.get(f"{API}/workflows/", headers=auth)
        r.raise_for_status()
        wfs = r.json()
        ok("workflows/list", f"count={len(wfs)}")
    except Exception as exc:
        fail("workflows/list", str(exc))
        wfs = []

    suffix = uuid.uuid4().hex[:6]
    agent_id = None
    try:
        r = client.get(f"{API}/agents/", headers=auth)
        r.raise_for_status()
        agents = r.json()
        agent_id = agents[0]["id"] if agents else None
    except Exception:
        agents = []

    emp_id = None
    if agent_id:
        try:
            r = client.post(
                f"{API}/employees/",
                headers=auth,
                json={
                    "name": f"冒烟员工-{suffix}",
                    "title": "Smoke",
                    "agent_id": agent_id,
                    "timezone": "Asia/Shanghai",
                },
            )
            if r.status_code >= 400:
                fail("employees/create", f"{r.status_code}: {detail(r)}")
            else:
                emp_id = r.json()["id"]
                ok("employees/create", f"id={emp_id[:8]}")
        except Exception as exc:
            fail("employees/create", str(exc))

    if emp_id and wfs:
        try:
            r = client.post(
                f"{API}/employees/{emp_id}/tasks",
                headers=auth,
                json={
                    "name": f"workflow-task-{suffix}",
                    "schedule_type": "interval",
                    "interval_seconds": 86400,
                    "task_type": "workflow",
                    "task_config": {"workflow_id": wfs[0]["id"]},
                    "enabled": False,
                },
            )
            if r.status_code >= 400:
                fail("employees/task(workflow)", f"{r.status_code}: {detail(r)}")
            else:
                ok("employees/task(workflow)", r.json().get("task_type", "workflow"))
        except Exception as exc:
            fail("employees/task(workflow)", str(exc))

    if emp_id and len(agents) >= 1:
        try:
            r = client.post(
                f"{API}/employees/{emp_id}/tasks",
                headers=auth,
                json={
                    "name": f"crew-task-{suffix}",
                    "schedule_type": "interval",
                    "interval_seconds": 86400,
                    "task_type": "crew",
                    "task_config": {
                        "prompt": "一句话介绍平台",
                        "agent_ids": [a["id"] for a in agents[:2]],
                    },
                    "enabled": False,
                },
            )
            if r.status_code >= 400:
                fail("employees/task(crew)", f"{r.status_code}: {detail(r)}")
            else:
                ok("employees/task(crew)", r.json().get("task_type", "crew"))
        except Exception as exc:
            fail("employees/task(crew)", str(exc))

    if emp_id:
        try:
            client.delete(f"{API}/employees/{emp_id}", headers=auth)
            ok("employees/cleanup", "deleted smoke employee")
        except Exception as exc:
            fail("employees/cleanup", str(exc))

    print("\n" + "=" * 50)
    print(f"TOTAL: {PASS} passed, {FAIL} failed")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
