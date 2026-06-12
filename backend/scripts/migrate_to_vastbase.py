#!/usr/bin/env python3
"""
Migrate AI-AGENT relational data to VastBase (海量 / PostgreSQL-compatible).

Supports:
  • SQLite  → VastBase   (local aiagnet.db → unit VastBase)
  • PostgreSQL → VastBase (dev/home PG → unit VastBase)

Usage (from backend/):

  # 1) Configure TARGET in backend/.env (see .env.vastbase.example)
  # 2) Preview:
  python scripts/migrate_to_vastbase.py --dry-run

  # 3) Migrate from local SQLite (default when backend/aiagnet.db exists):
  python scripts/migrate_to_vastbase.py

  # 4) Migrate from PostgreSQL source:
  python scripts/migrate_to_vastbase.py --source postgres

  # 5) Full refresh on VastBase (truncate target first):
  python scripts/migrate_to_vastbase.py --clear

Environment variables (backend/.env):

  TARGET_DB_HOST / TARGET_DB_PORT / TARGET_DB_USER / TARGET_DB_PASSWORD / TARGET_DB_NAME
  SOURCE_DB_*     — only when --source postgres

After migration, point the backend at VastBase:

  DB_DRIVER=vastbase
  DB_HOST=<same as TARGET_DB_HOST>
  DB_PORT=5432
  DB_USER=...
  DB_PASSWORD=...
  DB_NAME=...
  DB_SSL=prefer

Notes:
  • Chroma vector index and uploads/ are NOT in the database — copy or re-index separately.
  • Re-run is safe: existing row ids are skipped (use --clear for a full refresh).
  • For very large databases, pg_dump | pg_restore on the server may be faster.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from app.database_url import build_url_from_parts, to_sync_url  # noqa: E402
from scripts.migrate_common import (  # noqa: E402
    copy_all_tables,
    print_row_counts,
    resolve_tables,
    test_connection,
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


def _pg_url_from_prefix(prefix: str) -> str:
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


def _resolve_source(args: argparse.Namespace) -> tuple[str, str]:
    if args.source_url:
        return args.source_url, "custom URL"

    mode = args.source
    sqlite_path = Path(args.sqlite).resolve()

    if mode == "auto":
        if _env("SOURCE_DB_HOST"):
            mode = "postgres"
        elif sqlite_path.is_file():
            mode = "sqlite"
        else:
            raise ValueError(
                "Cannot detect source: set SOURCE_DB_* in .env, "
                f"or place SQLite at {sqlite_path}, or pass --source postgres|sqlite"
            )

    if mode == "sqlite":
        if not sqlite_path.is_file():
            raise ValueError(f"SQLite file not found: {sqlite_path}")
        return f"sqlite:///{sqlite_path.as_posix()}", str(sqlite_path)

    return _pg_url_from_prefix("SOURCE"), _parts("SOURCE")["host"]


def _resolve_target(args: argparse.Namespace) -> str:
    if args.target_url:
        return args.target_url
    return _pg_url_from_prefix("TARGET")


def _mask_url(url: str) -> str:
    return url.split("@")[-1] if "@" in url else url


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate SQLite or PostgreSQL data to VastBase",
    )
    parser.add_argument(
        "--source",
        choices=("auto", "sqlite", "postgres"),
        default="auto",
        help="Source database (default: auto-detect)",
    )
    parser.add_argument(
        "--sqlite",
        default=str(BACKEND_ROOT / "aiagnet.db"),
        help="SQLite file when --source sqlite (default: backend/aiagnet.db)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count rows only")
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Truncate VastBase tables before copy (destructive on target only)",
    )
    parser.add_argument(
        "--skip-create",
        action="store_true",
        help="Skip create_all on VastBase (schema must already exist)",
    )
    parser.add_argument("--source-url", help="Override source sync SQLAlchemy URL")
    parser.add_argument("--target-url", help="Override VastBase sync SQLAlchemy URL")
    args = parser.parse_args()

    try:
        src_url, src_label = _resolve_source(args)
        tgt_url = _resolve_target(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "\n在 backend/.env 中配置 TARGET_DB_*（VastBase 目标库）。\n"
            "从 PostgreSQL 迁移时还需 SOURCE_DB_*。\n"
            "示例见 backend/.env.vastbase.example\n",
            file=sys.stderr,
        )
        return 1

    print("Mode   : MIGRATE → VastBase")
    print(f"Source : {_mask_url(src_url)}  ({src_label})")
    print(f"Target : {_mask_url(tgt_url)}  [VastBase]")

    src_engine = create_engine(src_url)
    tgt_engine = create_engine(tgt_url)

    try:
        test_connection(src_engine, "Source")
        test_connection(tgt_engine, "Target VastBase")
    except Exception as exc:
        print(f"ERROR: Connection failed: {exc}", file=sys.stderr)
        return 1

    tables, extra = resolve_tables(src_engine)
    if extra:
        print(f"Note: skipping unknown source tables: {', '.join(extra)}")
    if not tables:
        print("ERROR: No known tables found in source database.", file=sys.stderr)
        return 1

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
        return 0

    print(f"\nDone. Inserted {copied_total} rows into VastBase.")
    print(
        "\n下一步:\n"
        "  1. 修改 backend/.env，让后端连接 VastBase:\n"
        "       DB_DRIVER=vastbase\n"
        "       DB_HOST=<TARGET_DB_HOST>\n"
        "       DB_PORT=5432\n"
        "       DB_USER=<TARGET_DB_USER>\n"
        "       DB_PASSWORD=<TARGET_DB_PASSWORD>\n"
        "       DB_NAME=<TARGET_DB_NAME>\n"
        "       DB_SSL=prefer\n"
        "  2. 重启后端: .\\start_backend.ps1\n"
        "  3. 访问 http://localhost:8000/health 确认 database.backend 为 vastbase\n"
        "  4. Chroma / uploads 需另行拷贝或重新上传文档\n"
        "\n再次迁移: 直接重跑本脚本；全量刷新目标库请加 --clear"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
