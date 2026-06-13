#!/usr/bin/env python3
"""
Create PostgreSQL database/user and apply AI-AGENT schema.

Run from backend/ after configuring admin credentials in .env or environment:

  # On the PostgreSQL server (localhost) or when port 5432 is reachable:
  set PG_ADMIN_USER=postgres
  set PG_ADMIN_PASSWORD=your_postgres_superuser_password
  set DB_HOST=your.db.server
  set DB_NAME=AI-AGENT
  set DB_USER=AI-AGENT
  set DB_PASSWORD=AI-AGENT
  python scripts/provision_postgres.py

  # Also migrate local SQLite data:
  python scripts/provision_postgres.py --migrate --sqlite ./aiagnet.db
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env")

from app.database_url import build_database_url, to_sync_url  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: F401, E402

DEFAULT_DB_NAME = "AI-AGENT"
DEFAULT_DB_USER = "AI-AGENT"
DEFAULT_DB_PASSWORD = "AI-AGENT"


def admin_connect(host: str, port: int, user: str, password: str):
    return psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database="postgres",
        connect_timeout=10,
    )


def ensure_role_and_database(
    host: str,
    port: int,
    admin_user: str,
    admin_password: str,
    app_user: str,
    app_password: str,
    db_name: str,
) -> None:
    conn = admin_connect(host, port, admin_user, admin_password)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (app_user,))
    if cur.fetchone() is None:
        cur.execute(
            sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD %s").format(sql.Identifier(app_user)),
            (app_password,),
        )
        print(f"Created role: {app_user}")
    else:
        cur.execute(
            sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD %s").format(sql.Identifier(app_user)),
            (app_password,),
        )
        print(f"Updated password for role: {app_user}")

    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
    if cur.fetchone() is None:
        cur.execute(
            sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8'").format(
                sql.Identifier(db_name), sql.Identifier(app_user)
            )
        )
        print(f"Created database: {db_name}")
    else:
        print(f"Database already exists: {db_name}")

    cur.execute(
        sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(
            sql.Identifier(db_name), sql.Identifier(app_user)
        )
    )
    cur.close()
    conn.close()


def apply_schema(host: str, port: int, app_user: str, app_password: str, db_name: str) -> None:
    url = build_database_url(
        driver="postgresql",
        host=host,
        port=port,
        user=app_user,
        password=app_password,
        database=db_name,
        async_driver=False,
    )
    engine = create_engine(url)
    print("Creating tables (create_all)...")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE agents ADD COLUMN IF NOT EXISTS "
                "skills_config JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
        )
    print("Schema ready.")


def migrate_sqlite(sqlite_path: Path, target_url: str) -> None:
    import importlib.util

    script = BACKEND_ROOT / "scripts" / "migrate_sqlite_to_postgres.py"
    spec = importlib.util.spec_from_file_location("migrate_sqlite_to_postgres", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    src_engine = create_engine(f"sqlite:///{sqlite_path.as_posix()}")
    tgt_engine = create_engine(to_sync_url(target_url))
    tables = [t for t in mod.TABLES_IN_ORDER if t in mod.list_tables(src_engine)]
    total = 0
    for table in tables:
        n = mod.copy_table(src_engine, tgt_engine, table, dry_run=False)
        print(f"  migrated {table}: {n} rows")
        total += n
    print(f"Migrated {total} rows from SQLite.")


def write_env_snippet(host: str, port: int, app_user: str, app_password: str, db_name: str) -> None:
    env_path = BACKEND_ROOT / ".env"
    snippet = f"""
# ── PostgreSQL on {host} ───────────────────────────────────
DB_HOST={host}
DB_PORT={port}
DB_USER={app_user}
DB_PASSWORD={app_password}
DB_NAME={db_name}
DB_SSL=prefer
"""
    print("\nAdd to backend/.env:")
    print(snippet)
    if env_path.is_file():
        text = env_path.read_text(encoding="utf-8")
        if "DB_HOST=" in text:
            print("(backend/.env already contains DB_HOST — update manually if needed)")
        else:
            env_path.write_text(text.rstrip() + "\n" + snippet, encoding="utf-8")
            print("Appended DB_* settings to backend/.env")


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision PostgreSQL for AI-AGENT")
    parser.add_argument("--host", default=os.getenv("DB_HOST") or os.getenv("PGHOST") or "127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.getenv("DB_PORT", "5432")))
    parser.add_argument("--db-name", default=os.getenv("DB_NAME", DEFAULT_DB_NAME))
    parser.add_argument("--app-user", default=os.getenv("DB_USER", DEFAULT_DB_USER))
    parser.add_argument("--app-password", default=os.getenv("DB_PASSWORD", DEFAULT_DB_PASSWORD))
    parser.add_argument("--admin-user", default=os.getenv("PG_ADMIN_USER", "postgres"))
    parser.add_argument("--admin-password", default=os.getenv("PG_ADMIN_PASSWORD", ""))
    parser.add_argument("--migrate", action="store_true", help="Copy data from local SQLite")
    parser.add_argument("--sqlite", default=str(BACKEND_ROOT / "aiagnet.db"))
    parser.add_argument("--skip-env", action="store_true")
    args = parser.parse_args()

    if not args.admin_password:
        print(
            "ERROR: Set PG_ADMIN_PASSWORD (PostgreSQL superuser password) to create database/user.",
            file=sys.stderr,
        )
        print(
            "Example:\n"
            f"  set PG_ADMIN_USER=postgres\n"
            f"  set PG_ADMIN_PASSWORD=your_password\n"
            f"  python scripts/provision_postgres.py --host {args.host}",
            file=sys.stderr,
        )
        return 1

    print(f"Connecting to PostgreSQL admin on {args.host}:{args.port} as {args.admin_user} ...")
    try:
        ensure_role_and_database(
            args.host,
            args.port,
            args.admin_user,
            args.admin_password,
            args.app_user,
            args.app_password,
            args.db_name,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if "timeout" in str(exc).lower() or "could not connect" in str(exc).lower():
            print(
                "\nHint: port 5432 may be blocked remotely. Run this script on the DB server or open the firewall:\n"
                "  PG_ADMIN_PASSWORD=... python scripts/provision_postgres.py --host 127.0.0.1\n"
                "Or open firewall / postgresql.conf listen_addresses + pg_hba.conf for your PC IP.",
                file=sys.stderr,
            )
        return 1

    apply_schema(args.host, args.port, args.app_user, args.app_password, args.db_name)

    target_url = build_database_url(
        driver="postgresql",
        host=args.host,
        port=args.port,
        user=args.app_user,
        password=args.app_password,
        database=args.db_name,
        async_driver=True,
    )

    if args.migrate:
        sqlite_path = Path(args.sqlite).resolve()
        if sqlite_path.is_file():
            print(f"Migrating from {sqlite_path} ...")
            migrate_sqlite(sqlite_path, target_url)
        else:
            print(f"Skip migrate: SQLite not found at {sqlite_path}")

    if not args.skip_env and args.host not in ("127.0.0.1", "localhost"):
        write_env_snippet(args.host, args.port, args.app_user, args.app_password, args.db_name)

    print("\nDone.")
    print(f"DATABASE_URL={target_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
