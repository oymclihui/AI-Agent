"""Shared helpers for SQLite / PostgreSQL → VastBase data migration."""
from __future__ import annotations

import json
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.db.base import Base  # noqa: F401
from app.db import models  # noqa: F401

# FK-safe copy order (parents before children).
TABLES_IN_ORDER = [
    "users",
    "password_reset_tokens",
    "model_configs",
    "agents",
    "skills",
    "tool_definitions",
    "knowledge_bases",
    "workflows",
    "user_mailbox_credentials",
    "user_model_credentials",
    "conversations",
    "messages",
    "documents",
    "agent_executions",
    "workflow_executions",
    "digital_employees",
    "employee_scheduled_tasks",
    "employee_task_runs",
    "desktop_demos",
    "desktop_sidecars",
    "desktop_tasks",
    "harness_pending_actions",
]

# PostgreSQL enum types that may need new labels on an existing VastBase schema.
PG_ENUM_PATCHES: dict[str, list[str]] = {
    "executionstatus": [
        "pending",
        "awaiting_confirmation",
        "running",
        "completed",
        "failed",
        "cancelled",
    ],
    "desktopdemostatus": ["draft", "ready", "archived"],
    "desktoptaskaction": ["capture_start", "capture_stop", "replay"],
    "tasktrigger": ["schedule", "manual"],
}


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


def _row_to_params(
    row: dict,
    bool_cols: set[str] | None = None,
    json_cols: set[str] | None = None,
) -> dict:
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
        name
        for name in columns
        if str(tgt_cols.get(name, {}).get("type", "")).upper().startswith("BOOLEAN")
    }
    json_cols = {
        name
        for name in columns
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


def ensure_target_schema(engine: Engine, *, skip_create: bool = False) -> None:
    """Create tables and patch PostgreSQL-compatible enum labels on VastBase."""
    if not skip_create:
        Base.metadata.create_all(engine)
    with engine.begin() as conn:
        if conn.dialect.name != "postgresql":
            return
        for type_name, labels in PG_ENUM_PATCHES.items():
            for label in labels:
                row = conn.execute(
                    text(
                        "SELECT 1 FROM pg_enum e "
                        "JOIN pg_type t ON e.enumtypid = t.oid "
                        "WHERE t.typname = :type_name AND e.enumlabel = :label"
                    ),
                    {"type_name": type_name, "label": label},
                ).fetchone()
                if row:
                    continue
                try:
                    conn.execute(
                        text(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{label}'")
                    )
                except Exception:
                    conn.execute(text(f"ALTER TYPE {type_name} ADD VALUE '{label}'"))


def test_connection(engine: Engine, label: str) -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print(f"{label} connection: OK")


def resolve_tables(src_engine: Engine) -> tuple[list[str], list[str]]:
    src_tables = list_tables(src_engine)
    tables = [t for t in TABLES_IN_ORDER if t in src_tables]
    extra = sorted(src_tables - set(TABLES_IN_ORDER))
    return tables, extra


def print_row_counts(engine: Engine, tables: list[str], *, title: str) -> dict[str, int]:
    print(f"\n{title}")
    summary = {table: count_rows(engine, table) for table in tables}
    for table, n in summary.items():
        print(f"  {table}: {n}")
    print(f"  TOTAL: {sum(summary.values())}")
    return summary


def copy_all_tables(
    src_engine: Engine,
    tgt_engine: Engine,
    tables: list[str],
    *,
    dry_run: bool,
    clear: bool,
    skip_create: bool,
) -> int:
    if dry_run:
        print("\nDry run — no data written.")
        return 0

    print("\nEnsuring VastBase schema...")
    ensure_target_schema(tgt_engine, skip_create=skip_create)

    if clear:
        print("Clearing target tables (--clear)...")
        truncate_target(tgt_engine, tables)

    print("\nCopying rows to VastBase...")
    copied_total = 0
    skipped_hint = "" if clear else " (duplicate id skipped on target)"
    for table in tables:
        n = copy_table(src_engine, tgt_engine, table, dry_run=False)
        copied_total += n
        print(f"  {table}: {n} rows inserted{skipped_hint}")
    return copied_total
