#!/usr/bin/env python3
"""Extended smoke test for excel-parser UI APIs."""
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
    print(f"Excel parser UI API smoke @ {BASE}\n")
    c = httpx.Client(timeout=120.0)

    r = c.post(f"{API}/auth/login", json={"login": LOGIN, "password": PASSWORD})
    if r.status_code != 200:
        fail("auth/login", r.text[:200])
        return 1
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    ok("auth/login")

    spec = c.get(f"{BASE}/openapi.json").json()
    for route in [
        "/api/v1/excel-parser/stats/global",
        "/api/v1/excel-parser/jobs/{job_id}/result",
    ]:
        if route in spec.get("paths", {}):
            ok("openapi", route)
        else:
            fail("openapi", f"missing {route}")

    r = c.get(f"{API}/excel-parser/stats/global", headers=h)
    if r.status_code == 200:
        ok("stats/global", str(r.json()))
    else:
        fail("stats/global", f"{r.status_code} {r.text[:200]}")

    tpl_id = f"smoke_ui_tpl_{int(time.time())}"
    r = c.post(
        f"{API}/excel-parser/templates",
        headers=h,
        json={
            "id": tpl_id,
            "name": "Smoke UI Template",
            "type": "BS",
            "sheet_mappings": [
                {
                    "sheet_name": "Sheet1",
                    "field_mapping": [
                        {"field_name": "门店名称", "cell_ref": "B2"},
                        {"field_name": "销售", "cell_ref": "C2"},
                    ],
                }
            ],
        },
    )
    if r.status_code == 201:
        ok("templates/create", tpl_id)
    else:
        fail("templates/create", f"{r.status_code} {r.text[:300]}")
        return 1

    r = c.put(
        f"{API}/excel-parser/templates/{tpl_id}",
        headers=h,
        json={"name": "Smoke UI Template Updated"},
    )
    if r.status_code == 200 and r.json().get("name") == "Smoke UI Template Updated":
        ok("templates/update")
    else:
        fail("templates/update", r.text[:200])

    demo_dir = Path(__file__).resolve().parent.parent / "demo_data" / "excel_merge"
    sample_files = list(demo_dir.glob("*.xlsx")) if demo_dir.is_dir() else []
    job_id = None

    if sample_files:
        folder = str(sample_files[0].parent)
        r = c.post(
            f"{API}/excel-parser/jobs",
            headers=h,
            json={
                "template_id": tpl_id,
                "folder_path": folder,
                "recursive": False,
                "output_filename": f"smoke_ui_{int(time.time())}.xlsx",
            },
        )
        if r.status_code == 201:
            job_id = r.json()["id"]
            ok("jobs/start", job_id[:8])
        else:
            fail("jobs/start", f"{r.status_code} {r.text[:300]}")

        if job_id:
            for _ in range(60):
                time.sleep(1)
                jr = c.get(f"{API}/excel-parser/jobs/{job_id}", headers=h)
                st = jr.json().get("status")
                if st == "completed":
                    body = jr.json()
                    ok("jobs/completed", f"rows={body.get('row_count')} ok={body.get('success_count')} fail={body.get('failed_count')}")
                    rr = c.get(f"{API}/excel-parser/jobs/{job_id}/result", headers=h)
                    if rr.status_code == 200 and rr.json().get("total", 0) >= 0:
                        ok("jobs/result", f"total={rr.json().get('total')} cols={len(rr.json().get('columns', []))}")
                    else:
                        fail("jobs/result", rr.text[:200])
                    ex = c.get(
                        f"{API}/excel-parser/jobs/{job_id}/export",
                        headers=h,
                        params={"format": "csv", "filename": "smoke_export"},
                    )
                    if ex.status_code == 200 and "text/csv" in ex.headers.get("content-type", ""):
                        ok("jobs/export-csv", f"bytes={len(ex.content)}")
                    else:
                        fail("jobs/export-csv", f"{ex.status_code} {ex.text[:100]}")
                    ex2 = c.get(
                        f"{API}/excel-parser/jobs/{job_id}/export",
                        headers=h,
                        params={"format": "excel", "filename": "smoke_export"},
                    )
                    if ex2.status_code == 200:
                        ok("jobs/export-excel", f"bytes={len(ex2.content)}")
                    else:
                        fail("jobs/export-excel", f"{ex2.status_code}")
                    logs = body.get("error_logs") or []
                    ok("jobs/error_logs", f"count={len(logs)}")
                    break
                if st == "failed":
                    fail("jobs/completed", jr.json().get("error_message", "failed"))
                    break
            else:
                fail("jobs/completed", "timeout")
    else:
        print("[SKIP] folder parse  ->  no demo xlsx in demo_data/excel_merge")

    r = c.delete(f"{API}/excel-parser/templates/{tpl_id}", headers=h)
    if r.status_code == 204:
        ok("templates/delete")
    else:
        fail("templates/delete", f"{r.status_code} {r.text[:200]}")

    print(f"\n{'=' * 50}\nPASS={PASS} FAIL={FAIL}")
    if failures:
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
