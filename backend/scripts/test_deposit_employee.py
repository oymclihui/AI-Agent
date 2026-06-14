"""Verify employee deposit when LLM omits agent block."""
import asyncio
import httpx

BASE = "http://192.168.50.10:3000/api/v1"
CONV = "11364871-de70-495a-ba0c-20b2a71a6721"


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=300.0) as c:
        token = (await c.post("/auth/login", json={"login": "admin", "password": "admin123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        sug = await c.post(f"/chat/conversations/{CONV}/suggest-deposit", headers=h, json={"lang": "zh"})
        print("suggest", sug.status_code)
        data = sug.json()
        print("agent_name in draft preview:", (data.get("draft") or {}).get("agent_name"))
        draft = data.get("draft_id")
        if not draft:
            print("no draft")
            return
        conf = await c.post(
            f"/chat/conversations/{CONV}/deposit/confirm",
            headers=h,
            json={
                "draft_id": draft,
                "types": ["skill", "employee"],
                "activate_employee": False,
            },
        )
        print("confirm employee", conf.status_code, conf.text[:400])


if __name__ == "__main__":
    asyncio.run(main())
