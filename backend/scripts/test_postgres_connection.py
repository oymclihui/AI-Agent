#!/usr/bin/env python3
"""Quick PostgreSQL connectivity and schema check."""
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

from app.config import settings  # noqa: E402


def main() -> int:
    import psycopg2
    from sqlalchemy import create_engine, text
    from app.database_url import to_sync_url

    host = settings.DB_HOST or "192.168.50.10"
    print(f"Target: {host}:{settings.DB_PORT}/{settings.DB_NAME} user={settings.DB_USER}")
    print(f"URL host part: ...@{settings.DATABASE_URL.split('@')[-1]}")

    try:
        conn = psycopg2.connect(
            host=host,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME,
            connect_timeout=10,
        )
        cur = conn.cursor()
        cur.execute("SELECT current_user, current_database(), version()")
        user, db, ver = cur.fetchone()
        print(f"psycopg2: OK user={user} db={db}")
        print(f"  {ver[:70]}...")
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        tables = [r[0] for r in cur.fetchall()]
        print(f"  public tables: {len(tables)}")
        if tables:
            print("  ", ", ".join(tables))
        conn.close()
    except Exception as exc:
        print(f"psycopg2: FAIL {exc}")
        return 1

    try:
        engine = create_engine(to_sync_url(settings.DATABASE_URL))
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("sqlalchemy sync: OK")
    except Exception as exc:
        print(f"sqlalchemy sync: FAIL {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
