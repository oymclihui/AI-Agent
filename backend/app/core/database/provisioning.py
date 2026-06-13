"""Test connections, detect existing tables, and safe schema initialization."""
from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.database.env_config import validate_schema_name
from app.database_url import build_database_url, DB_DRIVER_VASTBASE, DB_DRIVER_POSTGRESQL
from app.db.base import Base
from app.db import models  # noqa: F401
from app.db.init_db import init_db, seed_default_admin, seed_default_models, seed_desktop_operator_agent
from app.db.init_db import seed_org_rbac, seed_platform_knowledge_base, seed_template_agents
from app.db.init_db import seed_template_employees, seed_template_skills, seed_template_workflows
from app.db.init_db import ensure_bundled_skills

logger = structlog.get_logger(__name__)

INIT_SEED_STEPS: list[dict[str, str]] = [
    {"zh": "写入默认 LLM 模型配置（Model Hub）", "en": "Seed default LLM model configs (Model Hub)"},
    {"zh": "导入模板智能体", "en": "Seed template agents"},
    {"zh": "创建「桌面操作员」智能体", "en": "Seed desktop operator agent"},
    {"zh": "导入模板工作流", "en": "Seed template workflows"},
    {"zh": "导入模板技能与 bundled 技能", "en": "Seed template and bundled skills"},
    {"zh": "导入模板数字员工", "en": "Seed template digital employees"},
    {"zh": "初始化平台知识库文档（需 embedding 服务）", "en": "Seed platform knowledge base (needs embedding service)"},
    {"zh": "创建默认管理员账号（若尚无用户）", "en": "Create default admin user (if no users exist)"},
    {"zh": "初始化组织 RBAC（根部门、角色）", "en": "Seed org RBAC (root department, roles)"},
]

POST_CREATE_SQL_PATCHES: list[str] = [
    "-- agents.skills_config（缺列时）",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS skills_config JSONB NOT NULL DEFAULT '[]'::jsonb;",
    "-- conversations.skills_config（缺列时）",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS skills_config JSONB NOT NULL DEFAULT '[]'::jsonb;",
    "-- users / digital_employees 组织字段（缺列时，按实际检测结果追加 ALTER）",
    "-- executionstatus / employeetasktype 枚举新值（缺值时）",
    "ALTER TYPE executionstatus ADD VALUE IF NOT EXISTS 'awaiting_confirmation';",
    "ALTER TYPE employeetasktype ADD VALUE IF NOT EXISTS 'workflow';",
    "ALTER TYPE employeetasktype ADD VALUE IF NOT EXISTS 'crew';",
]

DB_PRESETS: dict[str, dict] = {
    DB_DRIVER_POSTGRESQL: {
        "driver": DB_DRIVER_POSTGRESQL,
        "label_zh": "PostgreSQL",
        "label_en": "PostgreSQL",
        "port": 5432,
        "schema": "public",
        "ssl": "prefer",
        "hint_zh": "本地或云端 PostgreSQL，适合在家开发测试。",
        "hint_en": "Local or cloud PostgreSQL — good for home dev/test.",
    },
    DB_DRIVER_VASTBASE: {
        "driver": DB_DRIVER_VASTBASE,
        "label_zh": "VastBase 海量",
        "label_en": "VastBase",
        "port": 5432,
        "schema": "public",
        "ssl": "prefer",
        "hint_zh": "单位 VastBase（PostgreSQL 兼容协议），与 PG 使用相同连接方式。",
        "hint_en": "Corporate VastBase (PostgreSQL-compatible wire protocol).",
    },
}


def app_table_names() -> list[str]:
    return sorted(t.name for t in Base.metadata.sorted_tables)


def build_init_sql_preview(*, schema: str, seed_test_data: bool = True) -> dict:
    """Return DDL + notes shown before admin runs one-click initialize."""
    schema_name = validate_schema_name(schema)
    dialect = postgresql.dialect()
    prelude: list[str] = []
    if schema_name != "public":
        prelude.append(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}";')
    prelude.append(f'SET search_path TO "{schema_name}", public;')

    create_table_sql: list[str] = []
    for table in Base.metadata.sorted_tables:
        create_table_sql.append(f"{CreateTable(table).compile(dialect=dialect)};")

    sections: list[str] = [
        "-- AI-AGENT 一键建表预览（未执行，仅供查看）",
        f"-- Target schema: {schema_name}",
        f"-- Tables: {len(create_table_sql)}",
        "",
        "-- === 1. Schema 准备 ===",
        *prelude,
        "",
        "-- === 2. CREATE TABLE（SQLAlchemy Base.metadata.create_all）===",
        "-- 表在上方 search_path 指定的 schema 中创建",
        *create_table_sql,
        "",
        "-- === 3. 结构补丁（create_all 之后，仅缺列/缺枚举时执行，幂等）===",
        *POST_CREATE_SQL_PATCHES,
    ]

    seed_steps = INIT_SEED_STEPS if seed_test_data else []
    sections.extend([
        "",
        "-- === 4. 种子数据（Python ORM 写入，非 SQL 脚本）===",
    ])
    if seed_test_data:
        for idx, step in enumerate(INIT_SEED_STEPS, start=1):
            sections.append(f"--   {idx}. {step['zh']}")
    else:
        sections.append("--   （已选择「仅建表」，跳过种子数据）")

    sections.extend([
        "",
        "-- === 安全策略 ===",
        "-- 若目标 schema 中已存在任意业务表，初始化会中止，不会执行建表或种子数据。",
        "-- 保存 backend/.env 后需重启后端；一键建表使用当前表单中的连接参数。",
    ])

    return {
        "schema": schema_name,
        "table_count": len(create_table_sql),
        "seed_test_data": seed_test_data,
        "prelude_sql": prelude,
        "create_table_sql": create_table_sql,
        "post_create_sql": POST_CREATE_SQL_PATCHES,
        "seed_steps": seed_steps,
        "full_sql": "\n".join(sections),
    }


def build_engine_kwargs(driver: str, ssl: str, schema: str) -> dict:
    kwargs: dict = {"pool_pre_ping": True, "pool_size": 2, "max_overflow": 0}
    connect_args: dict = {}
    if ssl == "disable":
        connect_args["ssl"] = False
    elif ssl == "require":
        import ssl as ssl_mod

        connect_args["ssl"] = ssl_mod.create_default_context()
    schema_name = validate_schema_name(schema)
    connect_args.setdefault("server_settings", {})["search_path"] = f"{schema_name},public"
    if driver == DB_DRIVER_VASTBASE:
        connect_args["server_settings"]["application_name"] = "aiagnet"
    kwargs["connect_args"] = connect_args
    return kwargs


def make_database_url(
    *,
    driver: str,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    ssl: str,
) -> str:
    resolved = DB_DRIVER_VASTBASE if driver == DB_DRIVER_VASTBASE else DB_DRIVER_POSTGRESQL
    return build_database_url(
        driver=resolved,
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        ssl=ssl,
        async_driver=True,
    )


async def test_connection(
    *,
    driver: str,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    ssl: str,
    schema: str = "public",
) -> tuple[bool, str]:
    url = make_database_url(
        driver=driver,
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        ssl=ssl,
    )
    engine = create_async_engine(url, **build_engine_kwargs(driver, ssl, schema))
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, "Connection OK"
    except Exception as exc:
        return False, str(exc)[:500]
    finally:
        await engine.dispose()


async def list_existing_app_tables(
    engine: AsyncEngine,
    schema: str,
) -> list[str]:
    schema_name = validate_schema_name(schema)
    known = set(app_table_names())

    def _scan(sync_conn) -> list[str]:
        inspector = inspect(sync_conn)
        existing = set(inspector.get_table_names(schema=schema_name))
        return sorted(existing & known)

    async with engine.connect() as conn:
        return await conn.run_sync(_scan)


@dataclass
class InitResult:
    status: str  # created | conflict | error
    message: str
    schema: str = "public"
    existing_tables: list[str] = field(default_factory=list)
    tables_created: int = 0
    seeds_run: bool = False


async def run_test_seeds(session) -> None:
    """Idempotent demo seeds — safe to run on empty or partially filled DB."""
    await seed_default_models(session)
    await seed_template_agents(session)
    await seed_desktop_operator_agent(session)
    await seed_template_workflows(session)
    from app.core.workflow.templates.loader import ensure_workflow_templates

    await ensure_workflow_templates(session)
    await seed_template_skills(session)
    await ensure_bundled_skills(session)
    await seed_template_employees(session)
    await seed_platform_knowledge_base(session)
    await seed_default_admin(session)
    await seed_org_rbac(session)
    await session.commit()


async def initialize_database(
    *,
    driver: str,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    ssl: str,
    schema: str,
    seed_test_data: bool = True,
) -> InitResult:
    schema_name = validate_schema_name(schema)
    url = make_database_url(
        driver=driver,
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        ssl=ssl,
    )
    engine = create_async_engine(url, **build_engine_kwargs(driver, ssl, schema_name))
    try:
        existing = await list_existing_app_tables(engine, schema_name)
        if existing:
            return InitResult(
                status="conflict",
                message=(
                    f"Schema「{schema_name}」中已存在 {len(existing)} 张业务表，未执行建表。"
                    "请更换 schema 名称（如 aiagnet_dev）后重试，避免覆盖原系统数据。"
                ),
                schema=schema_name,
                existing_tables=existing,
            )

        async with engine.begin() as conn:
            if schema_name != "public":
                await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
            await conn.execute(text(f'SET LOCAL search_path TO "{schema_name}", public'))

        await init_db(engine, schema=schema_name if schema_name != "public" else None)

        if seed_test_data:
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with session_factory() as session:
                await run_test_seeds(session)

        created_count = len(app_table_names())
        return InitResult(
            status="created",
            message=f"已在 schema「{schema_name}」创建 {created_count} 张表"
            + ("，并写入测试种子数据。" if seed_test_data else "。"),
            schema=schema_name,
            tables_created=created_count,
            seeds_run=seed_test_data,
        )
    except Exception as exc:
        logger.exception("database_initialize_failed", error=str(exc))
        return InitResult(status="error", message=str(exc)[:500], schema=schema_name)
    finally:
        await engine.dispose()
