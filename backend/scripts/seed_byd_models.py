"""Seed or refresh BYD EIS model configs in Model Hub."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.init_db import seed_default_models
from app.db.session import AsyncSessionLocal


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await seed_default_models(session)
    print("BYD model configs seeded. Restart backend or open Model Hub to verify.")


if __name__ == "__main__":
    asyncio.run(main())
