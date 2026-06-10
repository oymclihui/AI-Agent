#!/usr/bin/env python3
"""Sync and import all Agency Agents into the local database."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.session import AsyncSessionLocal
from app.core.agents.agency_library import AgencyAgentLibrary


async def main(overwrite: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        sync = await AgencyAgentLibrary.sync_catalog()
        print("Catalog synced:", sync)
        result = await AgencyAgentLibrary.import_all(db, overwrite=overwrite)
        from app.core.agents.i18n_backfill import backfill_all_agent_i18n
        i18n = await backfill_all_agent_i18n(db)
        await db.commit()
        print("Import result:")
        print(f"  agents: {len(result['imported_agents'])}")
        print(f"  skills: {len(result['imported_skills'])}")
        print(f"  skipped: {len(result['skipped'])}")
        print(f"  errors: {len(result['errors'])}")
        print("I18n backfill:", i18n)
        if result["errors"][:5]:
            print("  sample errors:", result["errors"][:5])


if __name__ == "__main__":
    ow = "--overwrite" in sys.argv
    asyncio.run(main(overwrite=ow))
