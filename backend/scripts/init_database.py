#!/usr/bin/env python3
"""One-click database init: create tables + seed test data (never overwrites existing tables).

Usage (from backend/):
  python scripts/init_database.py
  python scripts/init_database.py --driver postgresql --schema aiagnet_dev
  python scripts/init_database.py --driver vastbase --host vastbase.internal --schema public

If tables already exist in the target schema, exits with code 2 and lists them.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.core.database.env_config import current_db_config, validate_schema_name  # noqa: E402
from app.core.database.provisioning import initialize_database  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize AI-AGENT database schema + seeds")
    parser.add_argument("--driver", default=os.getenv("DB_DRIVER", "postgresql"))
    parser.add_argument("--host", default=os.getenv("DB_HOST"))
    parser.add_argument("--port", type=int, default=int(os.getenv("DB_PORT", "5432")))
    parser.add_argument("--user", default=os.getenv("DB_USER"))
    parser.add_argument("--password", default=os.getenv("DB_PASSWORD", ""))
    parser.add_argument("--database", default=os.getenv("DB_NAME"))
    parser.add_argument("--ssl", default=os.getenv("DB_SSL", "prefer"))
    parser.add_argument("--schema", default=os.getenv("DB_SCHEMA", "public"))
    parser.add_argument("--no-seed", action="store_true", help="Skip test seed data")
    args = parser.parse_args()

    cfg = current_db_config()
    host = args.host or cfg["host"]
    user = args.user or cfg["user"]
    database = args.database or cfg["database"]
    password = args.password
    if not password and cfg["password_set"]:
        from app.config import settings
        from app.core.database.env_config import parse_database_url

        password = settings.DB_PASSWORD if settings.DB_HOST else parse_database_url(settings.DATABASE_URL)["password"]

    if not host or not user or not database:
        print("ERROR: Set DB_HOST, DB_USER, DB_NAME in .env or pass CLI flags.", file=sys.stderr)
        return 1

    try:
        schema = validate_schema_name(args.schema)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Initializing driver={args.driver} host={host} db={database} schema={schema} ...")
    result = await initialize_database(
        driver=args.driver,
        host=host,
        port=args.port,
        user=user,
        password=str(password),
        database=database,
        ssl=args.ssl,
        schema=schema,
        seed_test_data=not args.no_seed,
    )

    if result.status == "conflict":
        print("\n⚠ CONFLICT — existing tables detected (no changes made):", file=sys.stderr)
        for name in result.existing_tables:
            print(f"  - {name}", file=sys.stderr)
        print(
            f"\nUse a different schema, e.g.: --schema aiagnet_dev\n"
            f"Then set DB_SCHEMA=aiagnet_dev in .env and restart backend.",
            file=sys.stderr,
        )
        return 2

    if result.status == "error":
        print(f"ERROR: {result.message}", file=sys.stderr)
        return 1

    print(f"\n✓ {result.message}")
    if result.seeds_run:
        print("  Seeds: admin/admin123, template agents, skills, workflows, etc.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
