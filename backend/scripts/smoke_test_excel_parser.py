#!/usr/bin/env python3
"""Smoke test for excel_parser integration (B+D+C)."""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
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
    print(f"Excel parser smoke @ {BASE}\n")
    c = httpx.Client(timeout=120.0)

    r = c.get(f"{BASE}/health")
    if r.status_code != 200:
        fail("health", str(r.status_code))
        return 1
    ok("health", r.json().get("status", "ok"))

    r = c.post(f"{API}/auth/login", json={"login": LOGIN, "password": PASSWORD})
    if r.status_code != 200:
        fail("auth/login", r.text[:200])
        return 1
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    ok("auth/login")

    spec = c.get(f"{BASE}/openapi.json").json()
    paths = spec.get("paths", {})
    for route in [
        "/api/v1/excel-parser/templates",
        "/api/v1/excel-parser/jobs",
        "/api/v1/data-sources/{source_id}/excel-template/parse",
        "/api/v1/data-sources/{source_id}/excel-template/status",
    ]:
        if route in paths:
            ok("openapi", route)
        else:
            fail("openapi", f"missing {route}")

    tools = c.get(f"{API}/tools/", headers=h).json()
    if isinstance(tools, list):
        names = {t.get("name") for t in tools}
    else:
        names = {t.get("name") for t in tools.get("items", tools.get("tools", []))}
    if "batch_parse_excel" in names:
        ok("tool/batch_parse_excel")
    else:
        fail("tool/batch_parse_excel", f"tools={sorted(names)[:10]}")

    r = c.get(f"{API}/excel-parser/templates", headers=h)
    if r.status_code != 200:
        fail("templates/list", r.text[:200])
        return 1
    items = r.json().get("items", [])
    ok("templates/list", f"count={len(items)}")
    tpl_id = next((t["id"] for t in items if t.get("id") == "bs_template_v1"), items[0]["id"] if items else "")
    if not tpl_id:
        fail("templates/seed", "no templates")
        return 1
    ok("templates/seed", tpl_id)

    r = c.post(
        f"{API}/data-sources/",
        headers=h,
        json={
            "name": f"smoke-excel-tpl-{int(time.time())}",
            "driver": "excel_template",
            "host": "local",
            "port": 0,
            "username": "-",
            "password": "",
            "database": "smoke",
            "template_id": tpl_id,
        },
    )
    if r.status_code not in (200, 201):
        fail("datasource/create", f"{r.status_code} {r.text[:200]}")
        return 1
    source_id = r.json()["id"]
    ok("datasource/create", source_id[:8])

    r = c.get(f"{API}/data-sources/{source_id}/excel-template/status", headers=h)
    if r.status_code == 200 and r.json().get("parse_status") == "idle":
        ok("template/status-idle")
    else:
        fail("template/status-idle", r.text[:200])

    demo_xlsx = Path(__file__).resolve().parent.parent / "demo_data" / "excel_merge"
    sample_files = list(demo_xlsx.glob("*.xlsx")) if demo_xlsx.is_dir() else []
    if not sample_files:
        skip_msg = "no demo xlsx — skipping upload/parse"
        print(f"[SKIP] upload/parse  ->  {skip_msg}")
    else:
        with sample_files[0].open("rb") as fh:
            r = c.post(
                f"{API}/data-sources/{source_id}/excel/upload",
                headers=h,
                files={"files": (sample_files[0].name, fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        if r.status_code == 200:
            ok("upload/input", sample_files[0].name)
        else:
            fail("upload/input", f"{r.status_code} {r.text[:200]}")

        r = c.post(
            f"{API}/data-sources/{source_id}/excel-template/parse",
            headers=h,
            json={"template_id": tpl_id, "recursive": True},
        )
        if r.status_code not in (200, 201):
            fail("parse/start", f"{r.status_code} {r.text[:200]}")
        else:
            job_id = r.json()["id"]
            ok("parse/start", job_id[:8])
            for _ in range(60):
                time.sleep(1)
                jr = c.get(f"{API}/excel-parser/jobs/{job_id}", headers=h)
                st = jr.json().get("status")
                if st == "completed":
                    ok("parse/completed", f"rows={jr.json().get('row_count', 0)}")
                    for _ in range(10):
                        sr = c.get(f"{API}/data-sources/{source_id}/excel-template/status", headers=h)
                        if sr.json().get("parse_status") == "ready":
                            ok("template/status-ready")
                            break
                        time.sleep(0.5)
                    else:
                        fail("template/status-ready", str(sr.json()))
                    break
                if st == "failed":
                    fail("parse/completed", jr.json().get("error_message", "failed"))
                    break
            else:
                fail("parse/completed", "timeout")

    c.delete(f"{API}/data-sources/{source_id}", headers=h)
    ok("cleanup")

    print(f"\n{'=' * 50}\nPASS={PASS} FAIL={FAIL}")
    if failures:
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
