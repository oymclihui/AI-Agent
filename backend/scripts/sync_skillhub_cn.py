"""Sync SkillHub.cn popular skills into bundled catalog and optionally import to DB."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main() -> None:
    from app.core.skills.library import SkillLibrary
    from app.db.session import AsyncSessionLocal

    parser = argparse.ArgumentParser()
    parser.add_argument("--import-hot", type=int, default=0, help="Import top N hot skills into DB")
    args = parser.parse_args()

    result = await SkillLibrary.sync_catalog_from_skillhub_cn()
    print("sync:", result)

    if args.import_hot > 0:
        hot = [
            t for t in SkillLibrary.list_catalog(source="skillhub-cn")
            if "skillhub-hot" in (t.get("tags") or [])
        ]
        items = hot[: args.import_hot]
        print(f"importing {len(items)} hot skills...")
        async with AsyncSessionLocal() as db:
            out = await SkillLibrary.import_templates(
                db,
                [{"source": t["source"], "slug": t["slug"]} for t in items],
                overwrite=False,
            )
            await db.commit()
            print("import:", out)


if __name__ == "__main__":
    asyncio.run(main())
