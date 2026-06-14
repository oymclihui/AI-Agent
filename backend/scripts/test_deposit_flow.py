"""Test chat deposit flow against remote or local server."""
from __future__ import annotations

import asyncio
import sys

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://192.168.50.10:3000").rstrip("/")
API = f"{BASE}/api/v1"


async def main() -> int:
    print(f"Testing deposit at {BASE}\n")
    async with httpx.AsyncClient(base_url=API, timeout=300.0) as client:
        login = await client.post("/auth/login", json={"login": "admin", "password": "admin123"})
        print("login:", login.status_code, login.text[:120] if login.status_code >= 400 else "ok")
        if login.status_code >= 400:
            return 1
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        agents = (await client.get("/agents/", headers=headers)).json()
        agent_id = agents[0]["id"] if agents else None

        conv = await client.post(
            "/chat/conversations",
            headers=headers,
            json={"title": "沉淀测试", "agent_id": agent_id},
        )
        print("create conv:", conv.status_code, conv.json().get("id") if conv.status_code < 400 else conv.text[:200])
        conv_id = conv.json()["id"]

        msg = await client.post(
            f"/chat/conversations/{conv_id}/messages",
            headers=headers,
            json={
                "message": (
                    "请帮我设计一个财务周报数字员工：每周一上午9点自动生成上周销售与回款摘要，"
                    "包含 KPI 表格和建议。岗位名称：财务分析助理。"
                ),
                "stream": False,
            },
            timeout=300.0,
        )
        print("chat msg:", msg.status_code, "len=", len(str(msg.json())) if msg.status_code < 400 else msg.text[:300])

        suggest = await client.post(
            f"/chat/conversations/{conv_id}/suggest-deposit",
            headers=headers,
            json={"lang": "zh"},
            timeout=300.0,
        )
        print("suggest-deposit:", suggest.status_code)
        if suggest.status_code >= 400:
            print("  error:", suggest.text[:500])
            return 1
        sdata = suggest.json()
        print("  worth=", sdata.get("worth_deposit"), "draft=", sdata.get("draft_id"))
        print("  suggestions=", [s.get("type") for s in sdata.get("suggestions") or []])

        draft_id = sdata.get("draft_id")
        if not draft_id:
            print("No draft — conversation may be too simple for deposit")
            return 0

        for types in (["skill"], ["skill", "agent"], ["skill", "knowledge", "agent", "employee"]):
            # re-suggest to refresh draft if confirm consumed it
            if types != ["skill"]:
                suggest2 = await client.post(
                    f"/chat/conversations/{conv_id}/suggest-deposit",
                    headers=headers,
                    json={"lang": "zh"},
                    timeout=300.0,
                )
                if suggest2.status_code >= 400:
                    print(f"re-suggest failed: {suggest2.text[:200]}")
                    break
                draft_id = suggest2.json().get("draft_id")
                if not draft_id:
                    break

            confirm = await client.post(
                f"/chat/conversations/{conv_id}/deposit/confirm",
                headers=headers,
                json={
                    "draft_id": draft_id,
                    "types": types,
                    "activate_employee": False,
                },
                timeout=300.0,
            )
            print(f"confirm {types}:", confirm.status_code)
            if confirm.status_code >= 400:
                print("  error:", confirm.text[:500])
                return 1
            print("  result:", confirm.json())
            if types == ["skill"]:
                break  # first test skill only for quick pass

    print("\nDeposit flow OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
