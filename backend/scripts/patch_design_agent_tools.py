"""Patch design agents to include create_presentation tool."""
import asyncio

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.db.models import Agent


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Agent).where(Agent.name.in_(["HTML 设计顾问", "HTML Hi-Fi Design Specialist"]))
        )
        agents = result.scalars().all()
        updated = 0
        for agent in agents:
            tools = list(agent.tools_config or [])
            names = {t.get("tool_name") for t in tools if isinstance(t, dict)}
            if "create_presentation" not in names:
                tools.append({"tool_name": "create_presentation"})
                agent.tools_config = tools
                updated += 1
        await db.commit()
        print(f"updated_agents={updated}")


if __name__ == "__main__":
    asyncio.run(main())
