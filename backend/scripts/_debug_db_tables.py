import asyncio
from sqlalchemy import inspect, text
from app.db.session import engine
from app.db import models  # noqa


async def main():
    async with engine.begin() as conn:
        def check(sync):
            insp = inspect(sync)
            print("agent_shares exists:", insp.has_table("agent_shares"))
            print("agents visibility cols:", [c["name"] for c in insp.get_columns("agents") if "vis" in c["name"].lower()])
        await conn.run_sync(check)

asyncio.run(main())
