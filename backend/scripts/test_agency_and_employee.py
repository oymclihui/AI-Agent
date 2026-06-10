"""Quick smoke tests for agency import and employee run export."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx


BASE = "http://127.0.0.1:8000/api/v1"


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=600.0) as client:
        health = await client.get("http://127.0.0.1:8000/health")
        print("health:", health.status_code, health.json())

        login = await client.post("/auth/login", json={"login": "admin", "password": "admin123"})
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        agents = await client.get("/agents/", headers=headers)
        agents.raise_for_status()
        agency_count = sum(
            1 for a in agents.json()
            if (a.get("metadata") or {}).get("agency_slug")
        )
        print("agents total:", len(agents.json()), "agency:", agency_count)

        catalog = await client.get("/agents/library/catalog", params={"source": "agency-agents"})
        print("agency catalog:", len(catalog.json()))

        skills = await client.get("/skills/", headers=headers)
        skills.raise_for_status()
        agency_skills = [s for s in skills.json() if "agency" in s.get("slug", "")]
        print("agency-like skills:", len(agency_skills), [s["slug"] for s in agency_skills[:5]])

        tmpl = await client.post(
            "/employees/import-template",
            json={"template_id": "agency-marketing-daily", "employee_name": "测试小创"},
        )
        if tmpl.status_code >= 400:
            print("template import failed:", tmpl.status_code, tmpl.text)
            return
        emp = tmpl.json()["employee"]
        emp_id = emp["id"]
        print("employee:", emp_id, emp["name"])

        tasks = await client.get(f"/employees/{emp_id}/tasks", headers=headers)
        tasks.raise_for_status()
        task_id = tasks.json()[0]["id"]
        print("running task:", task_id)

        run_resp = await client.post(
            f"/employees/{emp_id}/tasks/{task_id}/run",
            headers=headers,
        )
        if run_resp.status_code >= 400:
            print("run failed:", run_resp.status_code, run_resp.text)
            return
        run = run_resp.json()
        print("run status:", run["status"], "output_len:", len((run.get("output_data") or {}).get("output") or ""))

        dl = await client.get(f"/employees/{emp_id}/runs/{run['id']}/download", headers=headers)
        print("download:", dl.status_code, "bytes:", len(dl.content))

        save = await client.post(
            f"/employees/{emp_id}/runs/{run['id']}/save-to-knowledge",
            headers=headers,
            json={"kb_name": "数字员工测试报告库"},
        )
        print("save-to-kb:", save.status_code, save.json() if save.status_code < 400 else save.text)


if __name__ == "__main__":
    asyncio.run(main())
