#!/usr/bin/env python3
"""Create sample `test` table on a PostgreSQL host (for DataAsk trial)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

import psycopg2

HOST = os.environ.get("TARGET_DB_HOST", "192.168.1.50")
PORT = int(os.environ.get("TARGET_DB_PORT", "5432"))
USER = os.environ.get("TARGET_DB_USER", os.environ.get("DB_USER", "AI-AGENT"))
PASSWORD = os.environ.get("TARGET_DB_PASSWORD", os.environ.get("DB_PASSWORD", "AI-AGENT"))
DATABASE = os.environ.get("TARGET_DB_NAME", "test")


DDL = """
CREATE TABLE IF NOT EXISTS test (
    id SERIAL PRIMARY KEY,
    bu_code VARCHAR(64) NOT NULL,
    country_code VARCHAR(16) NOT NULL,
    week_label VARCHAR(16) NOT NULL,
    sales_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

SEED = """
INSERT INTO test (bu_code, country_code, week_label, sales_amount)
SELECT v.bu_code, v.country_code, v.week_label, v.sales_amount
FROM (VALUES
    ('乘用车', 'CN', 'W11', 1200.50),
    ('乘用车', 'CN', 'W12', 1350.00),
    ('乘用车', 'DE', 'W11', 890.00),
    ('乘用车', 'DE', 'W12', 920.50),
    ('商用车', 'IN', 'W11', 640.00),
    ('商用车', 'IN', 'W12', 560.25),
    ('商用车', 'BR', 'W11', 410.00),
    ('商用车', 'BR', 'W12', 380.75)
) AS v(bu_code, country_code, week_label, sales_amount)
WHERE NOT EXISTS (SELECT 1 FROM test LIMIT 1);
"""


def main() -> int:
    print(f"Target: {HOST}:{PORT}/{DATABASE} user={USER}")
    try:
        conn = psycopg2.connect(
            host=HOST,
            port=PORT,
            user=USER,
            password=PASSWORD,
            database=DATABASE,
            connect_timeout=15,
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(DDL)
            cur.execute(SEED)
            cur.execute("SELECT COUNT(*) FROM test")
            count = cur.fetchone()[0]
        conn.close()
        print(f"OK: table `test` ready, rows={count}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
