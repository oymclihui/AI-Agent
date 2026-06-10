"""Quick test for dashboard overview."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.session import AsyncSessionLocal
from app.core.dashboard.overview import build_dashboard_overview


async def main() -> None:
    async with AsyncSessionLocal() as session:
        data = await build_dashboard_overview(session)
    print("ok", data["today"]["total_runs"], "employees", len(data["employees"]))


if __name__ == "__main__":
    asyncio.run(main())
