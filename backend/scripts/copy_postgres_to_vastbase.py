#!/usr/bin/env python3
"""
Copy relational data from PostgreSQL → VastBase (duplicate, NOT cutover).

- Source PostgreSQL is read-only for this script — nothing is deleted or moved.
- Target VastBase receives a copy (INSERT … ON CONFLICT DO NOTHING).
- Re-run is safe: existing rows on VastBase are skipped unless you pass --clear.

For very large databases, native tools on the server may be faster:

  pg_dump -h SOURCE_HOST -U USER -d DBNAME -Fc -f aiagnet.dump
  pg_restore -h VASTBASE_HOST -U USER -d DBNAME --no-owner --no-acl aiagnet.dump

Usage (from backend/):

  # 1) SOURCE_DB_* = current PG,  TARGET_DB_* = VastBase in backend/.env
  # 2) Preview:
  python scripts/copy_postgres_to_vastbase.py --dry-run

  # 3) Copy (schema created on VastBase if missing):
  python scripts/copy_postgres_to_vastbase.py

  # 4) Full refresh on VastBase (truncate target first — still does NOT touch source PG):
  python scripts/copy_postgres_to_vastbase.py --clear
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from app.database_url import build_url_from_parts, to_sync_url  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: F401, E402
from scripts.migrate_sqlite_to_postgres import (  # noqa: E402
    TABLES_IN_ORDER,
    copy_table,
    count_rows,
    list_tables,
    truncate_target,
)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _parts(prefix: str) -> dict:
    return {
        "host": _env(f"{prefix}_DB_HOST"),
        "port": int(_env(f"{prefix}_DB_PORT", "5432")),
        "user": _env(f"{prefix}_DB_USER"),
        "password": _env(f"{prefix}_DB_PASSWORD"),
        "database": _env(f"{prefix}_DB_NAME", "aiagnet"),
        "ssl": _env(f"{prefix}_DB_SSL", "prefer"),
    }


def _url_from_prefix(prefix: str) -> str:
    parts = _parts(prefix)
    if not parts["host"] or not parts["user"]:
        raise ValueError(f"Missing {prefix}_DB_HOST or {prefix}_DB_USER")
    return to_sync_url(
        build_url_from_parts(
            host=parts["host"],
            port=parts["port"],
            user=parts["user"],
            password=parts["password"],
            database=parts["database"],
            ssl=parts["ssl"],
            async_driver=True,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy PostgreSQL data to VastBase (source PG unchanged)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count rows only")
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Truncate VastBase tables before copy (refresh copy only; source PG untouched)",
    )
    parser.add_argument("--skip-create", action="store_true", help="Skip create_all on VastBase")
    parser.add_argument("--source-url", help="Override source sync URL")
    parser.add_argument("--target-url", help="Override VastBase sync URL")
    args = parser.parse_args()

    try:
        src_url = args.source_url or _url_from_prefix("SOURCE")
        tgt_url = args.target_url or _url_from_prefix("TARGET")
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "\n在 backend/.env 中配置 SOURCE_DB_*（PostgreSQL 源库）和 TARGET_DB_*（VastBase 副本库）\n"
            "示例:\n"
            "  SOURCE_DB_HOST=192.168.50.10\n"
            "  SOURCE_DB_USER=AI-AGENT\n"
            "  SOURCE_DB_PASSWORD=...\n"
            "  SOURCE_DB_NAME=AI-AGENT\n"
            "  TARGET_DB_HOST=vastbase.company.internal\n"
            "  TARGET_DB_USER=...\n"
            "  TARGET_DB_PASSWORD=...\n"
            "  TARGET_DB_NAME=AI-AGENT\n",
            file=sys.stderr,
        )
        return 1

    print("Mode   : COPY (PostgreSQL → VastBase duplicate, source unchanged)")
    print(f"Source : {src_url.split('@')[-1] if '@' in src_url else src_url}  [read only]")
    print(f"Target : {tgt_url.split('@')[-1] if '@' in tgt_url else tgt_url}  [write copy]")

    src_engine = create_engine(src_url)
    tgt_engine = create_engine(tgt_url)

    for label, eng in ("Source PG", src_engine), ("Target VastBase", tgt_engine):
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            print(f"{label} connection: OK")
        except Exception as exc:
            print(f"ERROR: {label} connection failed: {exc}", file=sys.stderr)
            return 1

    src_tables = list_tables(src_engine)
    tables = [t for t in TABLES_IN_ORDER if t in src_tables]
    extra = sorted(src_tables - set(TABLES_IN_ORDER))
    if extra:
        print(f"Note: skipping unknown source tables: {', '.join(extra)}")

    print("\nSource row counts:")
    summary = {table: count_rows(src_engine, table) for table in tables}
    for table, n in summary.items():
        print(f"  {table}: {n}")
    print(f"  TOTAL: {sum(summary.values())}")

    if args.dry_run:
        print("\nDry run — no data written.")
        return 0

    if not args.skip_create:
        print("\nEnsuring VastBase schema (create_all)...")
        Base.metadata.create_all(tgt_engine)

    if args.clear:
        print("Clearing existing copy on VastBase (--clear)...")
        truncate_target(tgt_engine, tables)

    print("\nCopying rows to VastBase...")
    copied_total = 0
    skipped_hint = "" if args.clear else " (duplicate id skipped on target)"
    for table in tables:
        n = copy_table(src_engine, tgt_engine, table, dry_run=False)
        copied_total += n
        print(f"  {table}: {n} rows inserted{skipped_hint}")

    print(f"\nDone. Inserted {copied_total} rows into VastBase.")
    print(
        "\n说明:\n"
        "  • 源 PostgreSQL 未被修改或删除，仍可继续作为日常主库使用\n"
        "  • VastBase 上是 PG 的一份副本\n"
        "  • 再次复制: 直接重跑本脚本（已存在 id 会跳过）；要全量刷新副本请加 --clear\n"
        "\n单位环境可选:\n"
        "  • 后端仍连 PG：不用改 DB_*，只把 VastBase 当备份/同步库\n"
        "  • 单位后端连 VastBase 副本：单独配置 DB_DRIVER=vastbase + DB_HOST=TARGET 地址\n"
        "  • Chroma / uploads 不在 PG 里，需另行拷贝或重新上传"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
