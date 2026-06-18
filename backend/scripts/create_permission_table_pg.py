#!/usr/bin/env python3
"""Create user_data_scope permission table (工号 -> 国家) for DataAsk."""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

import psycopg2

HOST = os.environ.get("TARGET_DB_HOST", "192.168.50.10")
PORT = int(os.environ.get("TARGET_DB_PORT", "5432"))
USER = os.environ.get("TARGET_DB_USER", os.environ.get("DB_USER", "AI-AGENT"))
PASSWORD = os.environ.get("TARGET_DB_PASSWORD", os.environ.get("DB_PASSWORD", "AI-AGENT"))
DATABASE = os.environ.get("TARGET_DB_NAME", "AI-AGENT")

DDL = """
CREATE TABLE IF NOT EXISTS user_data_scope (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    country_code VARCHAR(16) NOT NULL,
    bu_code VARCHAR(64) NOT NULL DEFAULT '',
    remark VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, country_code, bu_code)
);
CREATE INDEX IF NOT EXISTS ix_user_data_scope_user_id ON user_data_scope (user_id);
COMMENT ON TABLE user_data_scope IS '问数行级权限：工号 user_id 可访问的国家/事业部';
COMMENT ON COLUMN user_data_scope.user_id IS '登录工号，与平台 users.employee_no 一致';
"""

# 工号 -> 可访问国家（Agent 不锁国家，查询时按当前登录工号过滤）
SEED = """
DELETE FROM user_data_scope;

INSERT INTO user_data_scope (user_id, country_code, bu_code, remark) VALUES
-- admin：当前默认登录账号，仅中国 + 德国（演示国家筛选）
('admin', 'CN', '', '管理员-中国区+德国区'),
('admin', 'DE', '', '管理员-中国区+德国区'),

-- 示例用户：印度 + 巴西
('E10001', 'IN', '', '海外分析师-印巴区域'),
('E10001', 'BR', '', '海外分析师-印巴区域'),

-- 示例用户：四国全开（等同“全部国家”）
('E10002', 'CN', '', '总部 FP&A-全国别'),
('E10002', 'DE', '', '总部 FP&A-全国别'),
('E10002', 'IN', '', '总部 FP&A-全国别'),
('E10002', 'BR', '', '总部 FP&A-全国别'),

-- 按事业部+国家细粒度（可选）
('E10003', 'CN', '乘用车', '乘用车中国区专员');
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
            cur.execute(
                "SELECT user_id, country_code, bu_code, remark FROM user_data_scope ORDER BY user_id, country_code"
            )
            rows = cur.fetchall()
        conn.close()
        print(f"OK: user_data_scope ready, rows={len(rows)}")
        print("\nPermissions:")
        for r in rows:
            bu = r[2] or "*"
            print(f"  工号={r[0]:8}  country={r[1]:4}  bu={bu:8}  {r[3] or ''}")
        print("\nDataAsk permission_rules (configure on data source):")
        print('  user_column: "user_id"')
        print('  scope_column: "country_code"')
        print('  data_column: "country_code"')
        print("\nLogin as admin -> only CN + DE rows in `test` table.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
