#!/usr/bin/env python3
"""Smoke test: agent visibility, sharing ACL, copy, and scope filters."""
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


def login(client: httpx.Client, login: str, password: str) -> str:
    r = client.post(f"{API}/auth/login", json={"login": login, "password": password})
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("missing access_token")
    return token


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def main() -> int:
    suffix = uuid.uuid4().hex[:8]
    user_a_login = f"smoke_a_{suffix}"
    user_b_login = f"smoke_b_{suffix}"
    user_pass = "SmokeTest123!"
    copy_id: str | None = None

    print(f"Agent permissions smoke test @ {BASE}\n")

    with httpx.Client(timeout=60.0) as client:
        try:
            r = client.get(f"{BASE}/health")
            r.raise_for_status()
            ok("health", r.json().get("status", "ok"))
        except Exception as exc:
            fail("health", str(exc))
            return 1

        # OpenAPI: new routes
        try:
            spec = client.get(f"{BASE}/openapi.json").json()
            paths = spec.get("paths", {})
            for p in (
                "/api/v1/agents/share-targets",
                "/api/v1/agents/{agent_id}/sharing",
                "/api/v1/agents/{agent_id}/copy",
            ):
                if p in paths:
                    ok(f"openapi {p}", "present")
                else:
                    fail(f"openapi {p}", "missing")
        except Exception as exc:
            fail("openapi", str(exc))

        # User A (owner)
        r = client.post(
            f"{API}/auth/register",
            json={
                "employee_no": user_a_login,
                "password": user_pass,
                "display_name": f"Smoke User A {suffix}",
            },
        )
        if r.status_code not in (200, 201):
            fail("register user A", detail(r))
            return 1
        user_a_token = r.json().get("access_token") or login(client, user_a_login, user_pass)
        user_a_h = auth_headers(user_a_token)
        ok("register user A", user_a_login)

        # User B (other)
        r = client.post(
            f"{API}/auth/register",
            json={
                "employee_no": user_b_login,
                "password": user_pass,
                "display_name": f"Smoke User B {suffix}",
            },
        )
        if r.status_code not in (200, 201):
            fail("register user B", detail(r))
            return 1
        user_b_token = r.json().get("access_token") or login(client, user_b_login, user_pass)
        user_b_h = auth_headers(user_b_token)
        ok("register user B", user_b_login)

        # User A creates private agent
        agent_name = f"Smoke Private Agent {suffix}"
        r = client.post(
            f"{API}/agents/",
            headers=user_a_h,
            json={
                "name": agent_name,
                "role": "Tester",
                "goal": "Verify private visibility",
                "backstory": "",
                "tools_config": [],
                "skills_config": [],
            },
        )
        if r.status_code != 201:
            fail("create private agent", detail(r))
            return 1
        agent = r.json()
        agent_id = agent["id"]
        ok("create private agent", f"id={agent_id[:8]} visibility={agent.get('visibility', 'private')}")

        # User B cannot see in mine or usable (only platform/org/shared)
        r = client.get(f"{API}/agents/", headers=user_b_h, params={"scope": "mine"})
        mine_ids = {a["id"] for a in r.json()}
        if agent_id in mine_ids:
            fail("user B mine scope", "should not include admin private agent")
        else:
            ok("user B mine scope", "private agent hidden")

        r = client.get(f"{API}/agents/", headers=user_b_h, params={"scope": "usable"})
        if r.status_code != 200:
            fail("user B usable before share", f"status={r.status_code} {detail(r)}")
        else:
            usable_ids = {a["id"] for a in r.json()}
            if agent_id in usable_ids:
                fail("user B usable before share", "private agent leaked")
            else:
                ok("user B usable before share", "private agent hidden")

        r = client.get(f"{API}/agents/{agent_id}", headers=user_b_h)
        if r.status_code == 404:
            ok("user B get private agent", "404 as expected")
        else:
            fail("user B get private agent", f"status={r.status_code}")

        # Share with user B
        me_b = client.get(f"{API}/auth/me", headers=user_b_h).json()
        user_b_id = me_b["id"]
        r = client.put(
            f"{API}/agents/{agent_id}/sharing",
            headers=user_a_h,
            json={
                "visibility": "shared",
                "grants": [
                    {"grantee_type": "user", "grantee_id": user_b_id, "permission": "use"},
                ],
            },
        )
        if r.status_code != 200:
            fail("share with user B", detail(r))
        else:
            ok("share with user B", f"visibility={r.json().get('visibility')}")

        r = client.get(f"{API}/agents/", headers=user_b_h, params={"scope": "shared"})
        shared_ids = {a["id"] for a in r.json()}
        if agent_id in shared_ids:
            ok("user B shared scope", "agent visible")
        else:
            fail("user B shared scope", "agent not listed")

        r = client.get(f"{API}/agents/", headers=user_b_h, params={"scope": "usable"})
        usable_ids = {a["id"] for a in r.json()}
        if agent_id in usable_ids:
            ok("user B usable after share", "agent usable")
        else:
            fail("user B usable after share", "agent missing")

        # User B can run / use in conversation
        r = client.post(
            f"{API}/chat/conversations",
            headers=user_b_h,
            json={"title": "Smoke conv", "agent_id": agent_id},
        )
        if r.status_code == 201:
            ok("user B bind agent in chat", "conversation created")
            conv_id = r.json()["id"]
            client.delete(f"{API}/chat/conversations/{conv_id}", headers=user_b_h)
        else:
            fail("user B bind agent in chat", detail(r))

        # Copy as user B
        r = client.post(f"{API}/agents/{agent_id}/copy", headers=user_b_h)
        if r.status_code != 201:
            fail("user B copy agent", detail(r))
            copy_id = None
        else:
            copy_id = r.json()["id"]
            ok("user B copy agent", f"copy={copy_id[:8]}")

        # Org visibility
        r = client.put(
            f"{API}/agents/{agent_id}/sharing",
            headers=user_a_h,
            json={"visibility": "org", "grants": []},
        )
        if r.status_code == 200:
            ok("set org visibility", "ok")
        else:
            fail("set org visibility", detail(r))

        # Register user C — should see org agent in usable without explicit grant
        user_c_login = f"smoke_c_{suffix}"
        r = client.post(
            f"{API}/auth/register",
            json={
                "employee_no": user_c_login,
                "password": user_pass,
                "display_name": f"Smoke User C {suffix}",
            },
        )
        if r.status_code in (200, 201):
            user_c_token = r.json().get("access_token") or login(client, user_c_login, user_pass)
            r = client.get(
                f"{API}/agents/",
                headers=auth_headers(user_c_token),
                params={"scope": "org"},
            )
            org_ids = {a["id"] for a in r.json()}
            if agent_id in org_ids:
                ok("user C org scope", "org agent visible")
            else:
                fail("user C org scope", "org agent not listed")
        else:
            fail("register user C", detail(r))

        # Platform scope has entries
        r = client.get(f"{API}/agents/", headers=user_a_h, params={"scope": "platform"})
        platform_list = r.json()
        if isinstance(platform_list, list):
            ok("platform scope", f"count={len(platform_list)}")
        else:
            fail("platform scope", "invalid response")

        # Cleanup
        if copy_id:
            dr = client.delete(f"{API}/agents/{copy_id}", headers=user_b_h)
            if dr.status_code in (204, 200):
                ok("cleanup copy", "deleted")
            else:
                fail("cleanup copy", detail(dr))
        dr = client.delete(f"{API}/agents/{agent_id}", headers=user_a_h)
        if dr.status_code in (204, 200):
            ok("cleanup agent", "deleted")
        else:
            fail("cleanup agent", detail(dr))

        r = client.get(f"{API}/agents/{agent_id}", headers=user_b_h)
        if r.status_code == 404:
            ok("access revoked after delete", "404")
        elif r.status_code == 403:
            ok("access revoked after delete", "403")
        else:
            fail("access revoked after delete", f"status={r.status_code}")

    print(f"\n{'=' * 50}")
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
