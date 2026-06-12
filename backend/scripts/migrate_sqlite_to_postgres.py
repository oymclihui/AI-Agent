#!/usr/bin/env python3
"""
Migrate relational data from local SQLite to PostgreSQL.

Usage (from backend/):
  # Option A — full DATABASE_URL for remote PostgreSQL
  set DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/aiagnet
  python scripts/migrate_sqlite_to_postgres.py

  # Option B — compose URL from DB_HOST / DB_USER / ...
  set DB_HOST=your.server.com
  set DB_USER=aiagnet
  set DB_PASSWORD=secret
  set DB_NAME=aiagnet
  python scripts/migrate_sqlite_to_postgres.py --sqlite ./aiagnet.db

Flags:
  --dry-run     Print row counts only, do not write
  --clear       Truncate target tables before copy (destructive)
  --skip-create Skip create_all on target (schema already exists)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from app.config import settings  # noqa: E402
from app.database_url import is_postgresql_url, is_sqlite_url, to_sync_url  # noqa: E402
from scripts.migrate_common import (  # noqa: E402
    copy_all_tables,
    print_row_counts,
    resolve_tables,
    test_connection,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate SQLite data to PostgreSQL")
    parser.add_argument(
        "--sqlite",
        default=str(BACKEND_ROOT / "aiagnet.db"),
        help="Path to source SQLite file (default: backend/aiagnet.db)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count rows only")
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Truncate target tables before copying (destructive)",
    )
    parser.add_argument(
        "--skip-create",
        action="store_true",
        help="Do not run create_all on target",
    )
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite).resolve()
    if not sqlite_path.is_file():
        print(f"ERROR: SQLite file not found: {sqlite_path}", file=sys.stderr)
        return 1

    target_url = settings.DATABASE_URL
    if is_sqlite_url(target_url):
        print(
            "ERROR: Target DATABASE_URL is still SQLite. "
            "Set DATABASE_URL=postgresql+asyncpg://... or DB_HOST/DB_USER/DB_PASSWORD/DB_NAME in backend/.env",
            file=sys.stderr,
        )
        return 1
    if not is_postgresql_url(target_url):
        print(f"ERROR: Unsupported target URL: {target_url}", file=sys.stderr)
        return 1

    src_url = f"sqlite:///{sqlite_path.as_posix()}"
    tgt_url = to_sync_url(target_url)

    print(f"Source : {src_url}")
    print(f"Target : {tgt_url.split('@')[-1] if '@' in tgt_url else tgt_url}")

    src_engine = create_engine(src_url)
    tgt_engine = create_engine(tgt_url)

    try:
        test_connection(tgt_engine, "Target PostgreSQL")
    except Exception as exc:
        print(f"ERROR: Cannot connect to PostgreSQL: {exc}", file=sys.stderr)
        return 1

    tables, extra = resolve_tables(src_engine)
    if extra:
        print(f"Note: skipping unknown SQLite tables: {', '.join(extra)}")

    print_row_counts(src_engine, tables, title="Source row counts:")

    copied_total = copy_all_tables(
        src_engine,
        tgt_engine,
        tables,
        dry_run=args.dry_run,
        clear=args.clear,
        skip_create=args.skip_create,
    )

    if args.dry_run:
        print("\nDry run — no data written.")
        return 0

    print(f"\nDone. Copied {copied_total} rows to PostgreSQL.")
    print(
        "\nNext steps:\n"
        "  1. Keep DATABASE_URL (or DB_HOST) in backend/.env\n"
        "  2. Restart backend: .\\start_backend.ps1\n"
        "  3. Vector store (Chroma) and uploads/ are NOT migrated — re-upload docs if needed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
