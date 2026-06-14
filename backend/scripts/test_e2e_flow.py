"""End-to-end smoke test: login -> chat -> agent -> digital employee."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.50.10:3000"
API = f"{BASE.rstrip('/')}/api/v1"


def ok(label: str, status: int, detail: str = "") -> None:
    mark = "OK" if status < 400 else "FAIL"
    print(f"[{mark}] {label}: {status} {detail[:200]}")


async def main() -> int:
    failures = 0
    async with httpx.AsyncClient(base_url=API, timeout=120.0, follow_redirects=True) as client:
        # Health
        health = await client.get(f"{BASE.rstrip('/')}/health")
        ok("health", health.status_code, health.text)
        if health.status_code >= 400:
            return 1

        # Login admin
        login = await client.post("/auth/login", json={"login": "admin", "password": "admin123"})
        ok("login admin", login.status_code, login.text[:120] if login.status_code >= 400 else "token received")
        if login.status_code >= 400:
            return 1
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Agents list
        agents = await client.get("/agents/", headers=headers)
        ok("agents list", agents.status_code, f"count={len(agents.json()) if agents.status_code < 400 else agents.text}")
        if agents.status_code >= 400:
            failures += 1
            agent_id = None
        else:
            agent_list = agents.json()
            agent_id = agent_list[0]["id"] if agent_list else None
            print(f"    first agent: {agent_list[0]['name'] if agent_list else 'NONE'} ({agent_id})")

        # Skip create-agent if we already have one (avoids long LLM-less create + connection drops)
        if not agent_id:
            create_agent = await client.post(
                "/agents",
                headers=headers,
                json={
                    "name": "E2E测试智能体",
                    "role": "Tester",
                    "goal": "验证链路",
                    "backstory": "自动化测试",
                    "llm_provider": "ollama",
                    "llm_model": "qwen3.6:35b",
                    "temperature": 0.3,
                    "tools_config": [],
                    "skills_config": [],
                },
            )
            ok("create agent", create_agent.status_code, create_agent.text[:200] if create_agent.status_code >= 400 else create_agent.json().get("id", ""))
            if create_agent.status_code < 400:
                agent_id = create_agent.json()["id"]
            else:
                failures += 1

        if not agent_id:
            print("ERROR: no agent_id, cannot continue employee/chat tests")
            failures += 1
        else:
            # Chat conversation with agent
            conv = await client.post(
                "/chat/conversations",
                headers=headers,
                json={"title": "E2E测试对话", "agent_id": agent_id},
            )
            ok("create conversation", conv.status_code, conv.text[:200] if conv.status_code >= 400 else conv.json().get("id", ""))
            if conv.status_code < 400:
                conv_id = conv.json()["id"]
                msg = await client.post(
                    f"/chat/conversations/{conv_id}/messages",
                    headers=headers,
                    json={"message": "你好，请用一句话介绍你自己", "stream": False},
                )
                ok("chat message", msg.status_code, msg.text[:200] if msg.status_code >= 400 else "reply received")
                if msg.status_code >= 400:
                    failures += 1
                else:
                    body = msg.json()
                    reply = (body.get("assistant_message") or body.get("message") or body.get("content") or "")
                    if isinstance(reply, dict):
                        reply = reply.get("content", "")
                    print(f"    reply preview: {str(reply)[:120]}")

            # Create digital employee (manual)
            emp_create = await client.post(
                "/employees",
                headers=headers,
                json={
                    "name": "E2E测试数字员工",
                    "title": "测试岗",
                    "description": "链路测试",
                    "agent_id": agent_id,
                    "timezone": "Asia/Shanghai",
                },
            )
            ok("create employee", emp_create.status_code, emp_create.text[:200] if emp_create.status_code >= 400 else emp_create.json().get("id", ""))
            if emp_create.status_code >= 400:
                failures += 1
            else:
                emp_id = emp_create.json()["id"]
                # Template import
                templates = await client.get("/employees/templates", headers=headers)
                ok("list templates", templates.status_code, f"count={len(templates.json()) if templates.status_code < 400 else templates.text}")
                if templates.status_code < 400 and templates.json():
                    tpl = templates.json()[0]
                    tpl_id = tpl["template_id"]
                    print(f"    trying template: {tpl_id}")
                    imp = await client.post(
                        "/employees/import-template",
                        headers=headers,
                        json={"template_id": tpl_id, "employee_name": "E2E模板员工"},
                    )
                    ok("import template", imp.status_code, imp.text[:300] if imp.status_code >= 400 else imp.json()["employee"]["id"])
                    if imp.status_code >= 400:
                        failures += 1
                    else:
                        emp_id = imp.json()["employee"]["id"]
                        tasks = await client.get(f"/employees/{emp_id}/tasks", headers=headers)
                        ok("list tasks", tasks.status_code, f"count={len(tasks.json()) if tasks.status_code < 400 else tasks.text}")
                        if tasks.status_code < 400 and tasks.json():
                            task_id = tasks.json()[0]["id"]
                            run = await client.post(f"/employees/{emp_id}/tasks/{task_id}/run", headers=headers, timeout=600.0)
                            ok("run task", run.status_code, run.text[:300] if run.status_code >= 400 else f"status={run.json().get('status')}")
                            if run.status_code >= 400:
                                failures += 1

        # Test non-admin user if finance user exists
        fin_login = await client.post("/auth/login", json={"login": "finance001", "password": "ChangeMe@2026"})
        if fin_login.status_code < 400:
            fin_headers = {"Authorization": f"Bearer {fin_login.json()['access_token']}"}
            fin_agents = await client.get("/agents/", headers=fin_headers)
            ok("finance user agents", fin_agents.status_code, f"count={len(fin_agents.json()) if fin_agents.status_code < 400 else fin_agents.text}")
            fin_emp = await client.post(
                "/employees",
                headers=fin_headers,
                json={
                    "name": "财务用户测试员工",
                    "agent_id": agent_id or "",
                    "timezone": "Asia/Shanghai",
                },
            )
            ok("finance create employee", fin_emp.status_code, fin_emp.text[:200] if fin_emp.status_code >= 400 else "created")
            if fin_emp.status_code >= 400:
                failures += 1
        else:
            print(f"[SKIP] finance user login: {fin_login.status_code}")

    print(f"\n=== Done: {failures} failure(s) ===")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
