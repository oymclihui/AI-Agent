#!/usr/bin/env python3
"""Switch an Agency agent (by agency_slug) to a reachable LLM."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.db.models import Agent
from app.db.session import AsyncSessionLocal


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agency-slug", required=True)
    parser.add_argument("--provider", default="ollama")
    parser.add_argument("--model", default="qwen3.6:35b")
    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Agent))
        target: Agent | None = None
        for agent in result.scalars().all():
            if (agent.metadata_ or {}).get("agency_slug") == args.agency_slug:
                target = agent
                break
        if not target:
            print(f"Agent not found for agency_slug={args.agency_slug}")
            sys.exit(1)
        old = f"{target.llm_provider}/{target.llm_model}"
        target.llm_provider = args.provider
        target.llm_model = args.model
        await db.commit()
        print(f"Updated {target.name}: {old} -> {args.provider}/{args.model}")


if __name__ == "__main__":
    asyncio.run(main())
