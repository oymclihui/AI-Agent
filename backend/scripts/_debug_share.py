import asyncio
import httpx
import uuid

async def main():
    s = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("http://127.0.0.1:8001/api/v1/auth/register", json={
            "employee_no": f"a_{s}", "password": "SmokeTest123!", "display_name": "A"
        })
        ta = r.json()["access_token"]
        ha = {"Authorization": f"Bearer {ta}"}
        r = await c.post("http://127.0.0.1:8001/api/v1/agents/", headers=ha, json={
            "name": "T", "role": "R", "goal": "G"
        })
        aid = r.json()["id"]
        r = await c.post("http://127.0.0.1:8001/api/v1/auth/register", json={
            "employee_no": f"b_{s}", "password": "SmokeTest123!", "display_name": "B"
        })
        tb = r.json()["access_token"]
        me = await c.get("http://127.0.0.1:8001/api/v1/auth/me", headers={"Authorization": f"Bearer {tb}"})
        bid = me.json()["id"]
        r = await c.put(
            f"http://127.0.0.1:8001/api/v1/agents/{aid}/sharing",
            headers=ha,
            json={
                "visibility": "shared",
                "grants": [{"grantee_type": "user", "grantee_id": bid, "permission": "use"}],
            },
        )
        print("share", r.status_code)
        print(r.headers.get("content-type"))
        print(r.content[:2000])

asyncio.run(main())
