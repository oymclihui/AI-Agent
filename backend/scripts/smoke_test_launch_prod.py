#!/usr/bin/env python3
"""Production launch smoke — response style, data-sources proxy, key pages."""
from __future__ import annotations

import io
import os
import sys

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.environ.get("SMOKE_BASE_URL", "http://192.168.50.10:3000").rstrip("/")
API = f"{BASE}/api/v1"
LOGIN = os.environ.get("SMOKE_ADMIN_LOGIN", "admin")
PASSWORD = os.environ.get("SMOKE_ADMIN_PASSWORD", "admin123")

PASS = FAIL = 0
failures: list[str] = []


def ok(name: str, detail: str = "") -> None:
    global PASS
    PASS += 1
    print(f"[PASS] {name}" + (f"  ->  {detail}" if detail else ""))


def fail(name: str, detail: str = "") -> None:
    global FAIL
    FAIL += 1
    failures.append(f"{name}: {detail}")
    print(f"[FAIL] {name}  ->  {detail}")


def main() -> int:
    print(f"Launch prod smoke @ {BASE}\n")
    client = httpx.Client(timeout=120.0, follow_redirects=False)

    try:
        r = client.get(f"{BASE}/health")
        r.raise_for_status()
        ok("health", r.json().get("status", ""))
    except Exception as exc:
        fail("health", str(exc))
        return 1

    try:
        r = client.post(f"{API}/auth/login", json={"login": LOGIN, "password": PASSWORD})
        r.raise_for_status()
        token = r.json()["access_token"]
        ok("auth/login", LOGIN)
    except Exception as exc:
        fail("auth/login", str(exc))
        return 1

    auth = {"Authorization": f"Bearer {token}"}

    pages = ["/login", "/chat", "/agents", "/employees", "/knowledge", "/workflows", "/data-sources", "/settings"]
    for path in pages:
        try:
            r = client.get(f"{BASE}{path}")
            if r.status_code == 200 and "html" in (r.headers.get("content-type") or "").lower():
                ok(f"page{path}", f"{len(r.content)} bytes")
            else:
                fail(f"page{path}", f"status={r.status_code}")
        except Exception as exc:
            fail(f"page{path}", str(exc))

    try:
        r = client.post(f"{API}/data-sources", headers=auth, json={"name": "__smoke_skip__", "driver": "postgres"})
        if r.status_code in (307, 308):
            fail("data-sources/no-trailing-slash-redirect", f"got {r.status_code} redirect")
        elif r.status_code >= 400:
            ok("data-sources/post-direct", f"status={r.status_code} (no 307)")
        else:
            ok("data-sources/post-direct", f"status={r.status_code}")
    except Exception as exc:
        fail("data-sources/post-direct", str(exc))

    conv_id = None
    try:
        r = client.post(
            f"{API}/chat/conversations",
            headers=auth,
            json={"title": "smoke-style", "response_style": "creative", "chat_mode": "single"},
        )
        r.raise_for_status()
        body = r.json()
        conv_id = body["id"]
        style = body.get("response_style")
        if style == "creative":
            ok("chat/response_style-create", style)
        else:
            fail("chat/response_style-create", f"got {style}")
    except Exception as exc:
        fail("chat/response_style-create", str(exc))

    if conv_id:
        try:
            r = client.patch(
                f"{API}/chat/conversations/{conv_id}/context",
                headers=auth,
                json={"response_style": "precise"},
            )
            r.raise_for_status()
            style = r.json().get("response_style")
            if style == "precise":
                ok("chat/response_style-patch", style)
            else:
                fail("chat/response_style-patch", f"got {style}")
        except Exception as exc:
            fail("chat/response_style-patch", str(exc))

        try:
            r = client.delete(f"{API}/chat/conversations/{conv_id}", headers=auth)
            r.raise_for_status()
            ok("chat/cleanup", conv_id[:8])
        except Exception as exc:
            fail("chat/cleanup", str(exc))

    try:
        r = client.post(
            f"{API}/chat/conversations",
            headers=auth,
            json={
                "title": "smoke-data-ask",
                "chat_mode": "data_ask",
                "data_source_id": "00000000-0000-0000-0000-000000000001",
            },
        )
        if r.status_code == 404:
            ok("chat/data_ask-missing-source", "404 expected for fake id")
        elif r.status_code == 400:
            ok("chat/data_ask-missing-source", "400 validation")
        else:
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if body.get("response_style") == "precise":
                ok("chat/data_ask-locks-precise", body.get("response_style"))
                client.delete(f"{API}/chat/conversations/{body['id']}", headers=auth)
            else:
                fail("chat/data_ask-locks-precise", str(body)[:200])
    except Exception as exc:
        fail("chat/data_ask-locks-precise", str(exc))

    try:
        r = client.get(f"{API}/data-sources", headers=auth)
        r.raise_for_status()
        ok("data-sources/list", f"count={len(r.json())}")
    except Exception as exc:
        fail("data-sources/list", str(exc))

    print(f"\n{'=' * 50}\nTOTAL: {PASS} passed, {FAIL} failed")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
