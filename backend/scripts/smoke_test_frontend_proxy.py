#!/usr/bin/env python3
"""Frontend proxy smoke (3000 -> backend)."""
import httpx

PASS = FAIL = 0

def ok(n, d=""):
    global PASS
    PASS += 1
    print(f"[PASS] {n}" + (f"  ->  {d}" if d else ""))

def fail(n, d=""):
    global FAIL
    FAIL += 1
    print(f"[FAIL] {n}  ->  {d}")

c = httpx.Client(timeout=60, follow_redirects=True)
r = c.get("http://127.0.0.1:8001/health")
ok("backend/health", r.json().get("status")) if r.status_code == 200 else fail("backend/health", str(r.status_code))

API = "http://localhost:3000/api/v1"
r = c.post(f"{API}/auth/login", json={"login": "admin", "password": "admin123"})
if r.status_code != 200:
    fail("proxy/login", r.text[:120])
else:
    ok("proxy/login")
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    for name, url in [
        ("proxy/data-sources", f"{API}/data-sources/"),
        ("proxy/excel-templates", f"{API}/excel-parser/templates"),
        ("proxy/agents", f"{API}/agents/?lang=zh&scope=usable"),
    ]:
        r = c.get(url, headers=h)
        ok(name, str(r.status_code)) if r.status_code == 200 else fail(name, r.text[:120])
    r = c.post(f"{API}/chat/conversations", headers=h, json={"title": "smoke", "chat_mode": "single"})
    if r.status_code in (200, 201):
        cid = r.json()["id"]
        c.delete(f"{API}/chat/conversations/{cid}", headers=h)
        ok("proxy/chat/create")
    else:
        fail("proxy/chat/create", r.text[:120])

print(f"\nPASS={PASS} FAIL={FAIL}")
raise SystemExit(1 if FAIL else 0)
