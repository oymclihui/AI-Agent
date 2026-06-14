"""Export full VastBase / PostgreSQL init SQL (DDL + minimal bootstrap seed)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_mock_engine  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.core.auth.security import hash_password  # noqa: E402
from app.core.database.env_config import validate_schema_name  # noqa: E402
from app.core.database.provisioning import POST_CREATE_SQL_PATCHES  # noqa: E402
from app.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: F401, E402


def collect_create_all_sql() -> list[str]:
    statements: list[str] = []

    def dump(sql, *args, **kwargs) -> None:
        compiled = str(sql.compile(dialect=postgresql.dialect()))
        if compiled.strip():
            statements.append(f"{compiled};")

    engine = create_mock_engine("postgresql+psycopg2://", dump)
    Base.metadata.create_all(engine, checkfirst=False)
    return statements


def build_bootstrap_seed_sql(*, admin_password_hash: str) -> list[str]:
    admin_no = settings.DEFAULT_ADMIN_EMPLOYEE_NO.replace("'", "''")
    admin_email = settings.DEFAULT_ADMIN_EMAIL.replace("'", "''")
    pwd = admin_password_hash.replace("'", "''")

    return [
        "-- === 5. 平台最小种子（管理员 + 根部门，幂等）===",
        "-- 默认账号: admin / admin123 （首次登录后请修改密码）",
        "-- 完整模板数据（智能体、工作流、Model Hub 等）请用 Web「设置 → 数据库初始化」或:",
        "--   cd backend && python scripts/init_database.py",
        "",
        "DO $$",
        "DECLARE",
        "  root_id VARCHAR(36) := '00000000-0000-4000-8000-000000000001';",
        "  admin_id VARCHAR(36) := '00000000-0000-4000-8000-000000000002';",
        "  role_id VARCHAR(36) := '00000000-0000-4000-8000-000000000003';",
        "  memb_id VARCHAR(36) := '00000000-0000-4000-8000-000000000004';",
        f"  pwd_hash VARCHAR(255) := '{pwd}';",
        "  ts TIMESTAMPTZ := NOW();",
        "BEGIN",
        "  IF NOT EXISTS (SELECT 1 FROM departments WHERE code = 'root') THEN",
        "    INSERT INTO departments (",
        "      id, name, code, parent_id, path, level, sort_order, dept_tier, is_active, created_at, updated_at",
        "    ) VALUES (",
        "      root_id, '全公司', 'root', NULL,",
        "      '/' || root_id || '/', 0, 0, 'business', TRUE, ts, ts",
        "    );",
        "  END IF;",
        "",
        f"  IF NOT EXISTS (SELECT 1 FROM users WHERE employee_no = '{admin_no}') THEN",
        "    INSERT INTO users (",
        "      id, employee_no, email, password_hash, display_name,",
        "      is_active, is_admin, primary_department_id, user_tier, created_at, updated_at",
        "    ) VALUES (",
        f"      admin_id, '{admin_no}', '{admin_email}', pwd_hash, 'Administrator',",
        "      TRUE, TRUE, root_id, 'staff', ts, ts",
        "    );",
        "  END IF;",
        "",
        "  UPDATE users SET is_admin = TRUE, primary_department_id = root_id",
        f"  WHERE employee_no = '{admin_no}';",
        "",
        "  IF NOT EXISTS (",
        "    SELECT 1 FROM user_roles ur",
        "    JOIN users u ON u.id = ur.user_id",
        f"    WHERE u.employee_no = '{admin_no}' AND ur.role_code = 'super_admin'",
        "  ) THEN",
        "    INSERT INTO user_roles (id, user_id, role_code, scope_department_id, created_at, updated_at)",
        "    SELECT role_id, u.id, 'super_admin', NULL, ts, ts",
        "    FROM users u",
        f"    WHERE u.employee_no = '{admin_no}';",
        "  END IF;",
        "",
        "  IF NOT EXISTS (",
        "    SELECT 1 FROM user_departments ud",
        "    JOIN users u ON u.id = ud.user_id",
        f"    WHERE u.employee_no = '{admin_no}' AND ud.is_primary = TRUE",
        "  ) THEN",
        "    INSERT INTO user_departments (id, user_id, department_id, is_primary, created_at, updated_at)",
        "    SELECT memb_id, u.id, root_id, TRUE, ts, ts",
        "    FROM users u",
        f"    WHERE u.employee_no = '{admin_no}';",
        "  END IF;",
        "END $$;",
    ]


def build_full_sql(*, schema: str, include_bootstrap: bool) -> str:
    schema_name = validate_schema_name(schema)
    prelude: list[str] = [
        "-- AI-AGENT VastBase / PostgreSQL 完整初始化脚本",
        "-- 生成: backend/scripts/export_vastbase_init_sql.py",
        f"-- 目标 schema: {schema_name}",
        "--",
        "-- 用法 (VastBase / psql):",
        "--   psql -h <host> -p 5432 -U <user> -d <database> -f backend/scripts/sql/init_vastbase_full.sql",
        "--",
        "-- 可选第二步（财务处组织树）:",
        "--   psql ... -f backend/scripts/sql/seed_finance_org_vastbase.sql",
        "--",
        "-- backend/.env 示例:",
        "--   DB_DRIVER=vastbase",
        "--   DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host>:5432/<database>",
        "",
        "-- === 1. Schema 准备 ===",
    ]
    if schema_name != "public":
        prelude.append(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}";')
    prelude.append(f'SET search_path TO "{schema_name}", public;')

    ddl = collect_create_all_sql()

    sections: list[str] = [
        *prelude,
        "",
        f"-- === 2. 枚举 + 建表 + 索引 + 外键（共 {len(ddl)} 条语句，SQLAlchemy create_all 顺序）===",
        *ddl,
        "",
        "-- === 3. 结构补丁（幂等，旧库升级时可单独执行）===",
        *POST_CREATE_SQL_PATCHES,
    ]

    if include_bootstrap:
        sections.extend(["", *build_bootstrap_seed_sql(admin_password_hash=hash_password(settings.DEFAULT_ADMIN_PASSWORD))])

    sections.extend([
        "",
        "-- === 完成 ===",
        "-- 登录: admin / admin123",
        "-- 模板智能体、工作流、Model Hub 等请运行 Python 初始化或 Web 设置向导。",
    ])
    return "\n".join(sections) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export VastBase init SQL to a .sql file")
    parser.add_argument("--schema", default="public")
    parser.add_argument("--output", default=str(ROOT / "scripts" / "sql" / "init_vastbase_full.sql"))
    parser.add_argument("--no-bootstrap", action="store_true", help="Skip admin/root seed block")
    args = parser.parse_args()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    sql = build_full_sql(schema=args.schema, include_bootstrap=not args.no_bootstrap)
    out.write_text(sql, encoding="utf-8")
    line_count = sql.count("\n") + 1
    print(f"Wrote {out} ({line_count} lines, schema={args.schema})")


if __name__ == "__main__":
    main()
