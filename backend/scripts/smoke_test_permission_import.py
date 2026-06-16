#!/usr/bin/env python3
"""Smoke test: organization permission Excel import (template / preview / apply)."""
from __future__ import annotations

import io
import os
import sys

import httpx
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
API = f"{BASE}/api/v1"
ADMIN_LOGIN = os.environ.get("SMOKE_ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.environ.get("SMOKE_ADMIN_PASSWORD", "admin123")

PASS = FAIL = 0
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
            return str(body["detail"])[:300]
        return str(body)[:300]
    except Exception:
        return resp.text[:300]


def login(client: httpx.Client) -> str | None:
    r = client.post(f"{API}/auth/login", json={"login": ADMIN_LOGIN, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        fail("auth/login", f"{r.status_code}: {detail(r)}")
        return None
    token = r.json().get("access_token")
    if not token:
        fail("auth/login", "no access_token")
        return None
    ok("auth/login", ADMIN_LOGIN)
    return token


def main() -> int:
    with httpx.Client(timeout=60.0) as client:
        token = login(client)
        if not token:
            print(f"\n{PASS}/{PASS + FAIL} passed")
            return 1
        headers = {"Authorization": f"Bearer {token}"}

        r = client.get(f"{API}/organization/permissions/import/template", headers=headers)
        if r.status_code != 200 or len(r.content) < 1000:
            fail("GET import/template", f"{r.status_code}, bytes={len(r.content)}")
        else:
            ok("GET import/template", f"bytes={len(r.content)}")

        r = client.get(
            f"{API}/organization/permissions/import/template",
            headers=headers,
            params={"include_current": "true"},
        )
        if r.status_code != 200:
            fail("GET import/template?include_current", detail(r))
        else:
            ok("GET import/template?include_current", f"bytes={len(r.content)}")

        users_r = client.get(f"{API}/organization/users", headers=headers)
        if users_r.status_code != 200:
            fail("GET organization/users", detail(users_r))
            print(f"\n{PASS}/{PASS + FAIL} passed")
            return 1
        users = users_r.json()
        if not users:
            fail("organization/users", "no users")
            print(f"\n{PASS}/{PASS + FAIL} passed")
            return 1
        ok("GET organization/users", f"count={len(users)}")

        target = next((u for u in users if u.get("employee_no")), users[0])
        emp_no = target.get("employee_no") or "admin"

        buf = io.BytesIO()
        pd.DataFrame([{
            "工号": emp_no,
            "姓名": target.get("display_name", ""),
            "主部门编码": "",
            "人员层级": "普通员工",
            "角色": "业务操作员",
            "角色管辖部门编码": "",
            "账号启用": "是",
        }]).to_excel(buf, index=False, sheet_name="权限导入")
        buf.seek(0)

        r = client.post(
            f"{API}/organization/permissions/import/preview",
            headers=headers,
            files={"file": ("test.xlsx", buf.read(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        if r.status_code != 200:
            fail("POST import/preview", detail(r))
            print(f"\n{PASS}/{PASS + FAIL} passed")
            return 1
        preview = r.json()
        ok(
            "POST import/preview",
            f"total={preview.get('total')} ok={preview.get('ok')} warn={preview.get('warning')} err={preview.get('error')}",
        )

        r = client.post(
            f"{API}/organization/permissions/import/apply",
            headers=headers,
            json={"rows": preview.get("rows", [])},
        )
        if r.status_code != 200:
            fail("POST import/apply", detail(r))
        else:
            body = r.json()
            ok("POST import/apply", f"applied={body.get('applied')} skipped={body.get('skipped')}")

        r = client.get(f"{API}/organization/delegation/permissions/import/template", headers=headers)
        if r.status_code not in (200, 403):
            fail("GET delegation import/template", detail(r))
        elif r.status_code == 200:
            ok("GET delegation import/template", f"bytes={len(r.content)}")
        else:
            ok("GET delegation import/template", "403 expected for non-delegator admin")

    print(f"\n{'=' * 40}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    if failures:
        print("Failures:")
        for item in failures:
            print(f"  - {item}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
