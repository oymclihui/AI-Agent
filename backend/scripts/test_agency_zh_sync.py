#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.agents.agency_library import AgencyAgentLibrary, SOURCE_ZH
from app.core.agents.i18n_backfill import backfill_all_agent_i18n
from app.db.session import AsyncSessionLocal


async def main() -> None:
    sync = await AgencyAgentLibrary.sync_catalog()
    print("sync:", sync)
    zh_only = AgencyAgentLibrary.list_catalog(source=SOURCE_ZH)
    print("zh_only count:", len(zh_only))
    if zh_only[:3]:
        print("sample zh_only:", [t["slug"] for t in zh_only[:3]])

    async with AsyncSessionLocal() as db:
        stats = await backfill_all_agent_i18n(db)
        await db.commit()
        print("backfill:", stats)


if __name__ == "__main__":
    asyncio.run(main())
