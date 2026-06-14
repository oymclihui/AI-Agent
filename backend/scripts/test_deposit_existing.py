"""Test deposit on existing conversations."""
import asyncio
import httpx

BASE = "http://192.168.50.10:3000/api/v1"


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=300.0) as c:
        token = (await c.post("/auth/login", json={"login": "admin", "password": "admin123"})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        convs = (await c.get("/chat/conversations", headers=h)).json()
        print("conversations", len(convs))
        cid = None
        for conv in convs[:15]:
            msgs = (await c.get(f"/chat/conversations/{conv['id']}/messages", headers=h)).json()
            n = len(msgs) if isinstance(msgs, list) else 0
            title = (conv.get("title") or "")[:40]
            print(f"  {conv['id'][:8]} {title!r} msgs={n}")
            if n >= 2 and cid is None:
                cid = conv["id"]
        if not cid and convs:
            cid = convs[0]["id"]
        print("using", cid)

        sug = await c.post(f"/chat/conversations/{cid}/suggest-deposit", headers=h, json={"lang": "zh"}, timeout=300.0)
        print("suggest", sug.status_code, sug.text[:500])
        if sug.status_code != 200:
            return
        draft = sug.json().get("draft_id")
        if not draft:
            print("no draft_id")
            return

        conf = await c.post(
            f"/chat/conversations/{cid}/deposit/confirm",
            headers=h,
            json={"draft_id": draft, "types": ["skill"], "activate_employee": False},
            timeout=300.0,
        )
        print("confirm skill", conf.status_code, conf.text[:500])

        sug2 = await c.post(f"/chat/conversations/{cid}/suggest-deposit", headers=h, json={"lang": "zh"}, timeout=300.0)
        draft2 = sug2.json().get("draft_id") if sug2.status_code == 200 else None
        if draft2:
            conf2 = await c.post(
                f"/chat/conversations/{cid}/deposit/confirm",
                headers=h,
                json={
                    "draft_id": draft2,
                    "types": ["skill", "knowledge", "agent", "employee"],
                    "activate_employee": False,
                },
                timeout=300.0,
            )
            print("confirm all", conf2.status_code, conf2.text[:600])


if __name__ == "__main__":
    asyncio.run(main())
