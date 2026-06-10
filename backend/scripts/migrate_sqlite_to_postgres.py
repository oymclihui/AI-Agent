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
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from app.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: F401, E402
from app.database_url import is_postgresql_url, is_sqlite_url, to_sync_url  # noqa: E402

TABLES_IN_ORDER = [
    "agents",
    "workflows",
    "model_configs",
    "skills",
    "tool_definitions",
    "knowledge_bases",
    "workflow_executions",
    "agent_executions",
    "conversations",
    "messages",
    "documents",
    "digital_employees",
    "employee_scheduled_tasks",
    "employee_task_runs",
]


def _normalize_value(value, col_type: str | None = None):
    if isinstance(value, memoryview):
        return bytes(value)
    if col_type == "BOOLEAN" and value is not None:
        if isinstance(value, bool):
            return value
        return bool(int(value))
    if col_type in ("JSON", "JSONB"):
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, str):
            try:
                json.loads(value)
                return value
            except json.JSONDecodeError:
                return value
    return value


def _row_to_params(row: dict, bool_cols: set[str] | None = None, json_cols: set[str] | None = None) -> dict:
    bool_cols = bool_cols or set()
    json_cols = json_cols or set()
    out = {}
    for key, val in row.items():
        if key in bool_cols:
            out[key] = _normalize_value(val, "BOOLEAN")
        elif key in json_cols:
            out[key] = _normalize_value(val, "JSON")
        else:
            out[key] = _normalize_value(val)
    return out


def count_rows(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        if not inspect(conn).has_table(table):
            return 0
        return conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()


def list_tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def truncate_target(engine: Engine, tables: list[str]) -> None:
    existing = list_tables(engine)
    ordered = [t for t in reversed(tables) if t in existing]
    if not ordered:
        return
    joined = ", ".join(f'"{t}"' for t in ordered)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE"))


def copy_table(src: Engine, tgt: Engine, table: str, dry_run: bool) -> int:
    src_insp = inspect(src)
    tgt_insp = inspect(tgt)
    if not src_insp.has_table(table):
        return 0
    if not tgt_insp.has_table(table):
        raise RuntimeError(f"Target missing table: {table}")

    columns = [c["name"] for c in src_insp.get_columns(table)]
    tgt_cols = {c["name"]: c for c in tgt_insp.get_columns(table)}
    bool_cols = {
        name for name in columns
        if str(tgt_cols.get(name, {}).get("type", "")).upper().startswith("BOOLEAN")
    }
    json_cols = {
        name for name in columns
        if "JSON" in str(tgt_cols.get(name, {}).get("type", "")).upper()
    }
    col_list = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(f":{c}" for c in columns)
    insert_sql = text(
        f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}) '
        f'ON CONFLICT ("id") DO NOTHING'
    )

    with src.connect() as src_conn:
        rows = src_conn.execute(text(f'SELECT {col_list} FROM "{table}"')).mappings().all()

    if dry_run:
        return len(rows)

    copied = 0
    with tgt.begin() as tgt_conn:
        for row in rows:
            tgt_conn.execute(insert_sql, _row_to_params(dict(row), bool_cols, json_cols))
            copied += 1
    return copied


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
        with tgt_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("Target PostgreSQL connection: OK")
    except Exception as exc:
        print(f"ERROR: Cannot connect to PostgreSQL: {exc}", file=sys.stderr)
        return 1

    src_tables = list_tables(src_engine)
    tables = [t for t in TABLES_IN_ORDER if t in src_tables]
    extra = sorted(src_tables - set(TABLES_IN_ORDER))
    if extra:
        print(f"Note: skipping unknown SQLite tables: {', '.join(extra)}")

    summary = {}
    for table in tables:
        summary[table] = count_rows(src_engine, table)

    print("\nSource row counts:")
    for table, n in summary.items():
        print(f"  {table}: {n}")
    print(f"  TOTAL: {sum(summary.values())}")

    if args.dry_run:
        print("\nDry run — no data written.")
        return 0

    if not args.skip_create:
        print("\nCreating/updating PostgreSQL schema (create_all)...")
        Base.metadata.create_all(tgt_engine)

    if args.clear:
        print("Truncating target tables...")
        truncate_target(tgt_engine, tables)

    print("\nCopying data...")
    copied_total = 0
    for table in tables:
        n = copy_table(src_engine, tgt_engine, table, dry_run=False)
        copied_total += n
        print(f"  {table}: {n} rows")

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
