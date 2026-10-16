"""
Database initialization: creates all tables and seeds default data.
"""
from sqlalchemy.ext.asyncio import AsyncEngine
from app.db.base import Base, generate_uuid
from app.db import models  # noqa: F401 - ensure all models are registered


async def init_db(engine: AsyncEngine, schema: str | None = None) -> None:
    from sqlalchemy import text

    target_schema = schema if schema and schema != "public" else None
    async with engine.begin() as conn:
        if str(engine.url).startswith("sqlite"):
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            await conn.exec_driver_sql("PRAGMA busy_timeout=30000")
        elif target_schema:
            await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{target_schema}"'))
            await conn.execute(text(f'SET LOCAL search_path TO "{target_schema}", public'))

        def _create_all(sync_conn) -> None:
            Base.metadata.create_all(sync_conn)

        await conn.run_sync(_create_all)
    await _migrate_schema(engine, schema=target_schema)


async def _migrate_schema(engine: AsyncEngine, schema: str | None = None) -> None:
    """Lightweight schema patches (create_all does not alter existing tables)."""
    from sqlalchemy import inspect, text

    async with engine.begin() as conn:
        def _add_skills_config(sync_conn) -> None:
            inspector = inspect(sync_conn)
            if not inspector.has_table("agents", schema=schema):
                return
            cols = {c["name"] for c in inspector.get_columns("agents", schema=schema)}
            if "skills_config" in cols:
                return
            if engine.dialect.name == "sqlite":
                sync_conn.execute(
                    text("ALTER TABLE agents ADD COLUMN skills_config JSON DEFAULT '[]'")
                )
            else:
                sync_conn.execute(
                    text(
                        "ALTER TABLE agents ADD COLUMN IF NOT EXISTS "
                        "skills_config JSONB NOT NULL DEFAULT '[]'::jsonb"
                    )
                )

        await conn.run_sync(_add_skills_config)
        await conn.run_sync(lambda c: _add_conversation_skills_config(c, schema))
        await conn.run_sync(lambda c: _add_user_isolation_columns(c, schema))
        await conn.run_sync(lambda c: _add_org_rbac_columns(c, schema))
        await conn.run_sync(lambda c: _add_users_admin_column(c, schema))
        await conn.run_sync(lambda c: _add_agent_visibility_columns(c, schema))
        await conn.run_sync(_ensure_users_table)
        await conn.run_sync(_ensure_postgres_enum_values)
        await conn.run_sync(_ensure_data_source_grants_table)
        await conn.run_sync(_ensure_knowledge_permissions)
        await conn.run_sync(_ensure_knowledge_quality)
        await conn.run_sync(_ensure_system_settings_table)


def _ensure_system_settings_table(sync_conn) -> None:
    from sqlalchemy import inspect

    inspector = inspect(sync_conn)
    if inspector.has_table("system_settings"):
        return
    from app.db.base import Base

    table = Base.metadata.tables.get("system_settings")
    if table is not None:
        table.create(sync_conn, checkfirst=True)


def _ensure_data_source_grants_table(sync_conn) -> None:
    from sqlalchemy import inspect

    inspector = inspect(sync_conn)
    if inspector.has_table("data_source_grants"):
        return
    from app.db.base import Base

    table = Base.metadata.tables.get("data_source_grants")
    if table is not None:
        table.create(sync_conn, checkfirst=True)


def _add_conversation_skills_config(sync_conn, schema: str | None = None) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    if not inspector.has_table("conversations", schema=schema):
        return
    cols = {c["name"] for c in inspector.get_columns("conversations", schema=schema)}
    if "skills_config" in cols:
        return
    if sync_conn.dialect.name == "sqlite":
        sync_conn.execute(
            text("ALTER TABLE conversations ADD COLUMN skills_config JSON DEFAULT '[]'")
        )
    else:
        sync_conn.execute(
            text(
                "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS "
                "skills_config JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
        )


def _ensure_postgres_enum_values(sync_conn) -> None:
    """Add new enum labels to existing PostgreSQL types (create_all does not alter enums)."""
    from sqlalchemy import text

    if sync_conn.dialect.name != "postgresql":
        return

    patches = {
        "executionstatus": ["awaiting_confirmation"],
        "employeetasktype": ["workflow", "crew"],
    }
    for type_name, labels in patches.items():
        for label in labels:
            row = sync_conn.execute(
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
                sync_conn.execute(
                    text(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{label}'")
                )
            except Exception:
                sync_conn.execute(text(f"ALTER TYPE {type_name} ADD VALUE '{label}'"))


async def seed_default_admin(session) -> None:
    from sqlalchemy import select, func
    from app.db.models import User
    from app.config import settings
    from app.core.auth.security import hash_password

    count = await session.execute(select(func.count()).select_from(User))
    if (count.scalar() or 0) > 0:
        return

    admin = User(
        id=generate_uuid(),
        employee_no=settings.DEFAULT_ADMIN_EMPLOYEE_NO,
        email=settings.DEFAULT_ADMIN_EMAIL,
        password_hash=hash_password(settings.DEFAULT_ADMIN_PASSWORD),
        display_name="Administrator",
        is_active=True,
        is_admin=True,
    )
    session.add(admin)
    await session.commit()


async def seed_org_rbac(session) -> None:
    """Ensure root department, default roles, and admin privileges (idempotent)."""
    from sqlalchemy import select, func
    from app.config import settings
    from app.core.auth.permissions import compute_department_path
    from app.db.models import (
        Department,
        DigitalEmployee,
        User,
        UserDepartment,
        UserRole,
    )

    root = (
        await session.execute(
            select(Department).where(Department.code == "root").limit(1)
        )
    ).scalar_one_or_none()

    if not root:
        root_id = generate_uuid()
        path, level = compute_department_path(None, root_id)
        root = Department(
            id=root_id,
            name="全公司",
            code="root",
            parent_id=None,
            path=path,
            level=level,
            sort_order=0,
            is_active=True,
        )
        session.add(root)
        await session.flush()

    admin_no = settings.DEFAULT_ADMIN_EMPLOYEE_NO
    admin = (
        await session.execute(select(User).where(User.employee_no == admin_no).limit(1))
    ).scalar_one_or_none()
    if admin:
        admin.is_admin = True
        if not admin.primary_department_id:
            admin.primary_department_id = root.id

        has_super = (
            await session.execute(
                select(UserRole.id).where(
                    UserRole.user_id == admin.id,
                    UserRole.role_code == "super_admin",
                ).limit(1)
            )
        ).scalar_one_or_none()
        if not has_super:
            session.add(UserRole(
                id=generate_uuid(),
                user_id=admin.id,
                role_code="super_admin",
                scope_department_id=None,
            ))

        membership = (
            await session.execute(
                select(UserDepartment).where(
                    UserDepartment.user_id == admin.id,
                    UserDepartment.is_primary == True,
                ).limit(1)
            )
        ).scalar_one_or_none()
        if not membership:
            session.add(UserDepartment(
                id=generate_uuid(),
                user_id=admin.id,
                department_id=root.id,
                is_primary=True,
            ))

    users = (await session.execute(select(User))).scalars().all()
    for user in users:
        role_count = (
            await session.execute(
                select(func.count()).select_from(UserRole).where(UserRole.user_id == user.id)
            )
        ).scalar() or 0
        if role_count == 0:
            code = "super_admin" if user.is_admin else "operator"
            session.add(UserRole(
                id=generate_uuid(),
                user_id=user.id,
                role_code=code,
                scope_department_id=root.id if code == "operator" else None,
            ))
        if not user.primary_department_id:
            user.primary_department_id = root.id
            existing = (
                await session.execute(
                    select(UserDepartment).where(
                        UserDepartment.user_id == user.id,
                        UserDepartment.is_primary == True,
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if not existing:
                session.add(UserDepartment(
                    id=generate_uuid(),
                    user_id=user.id,
                    department_id=root.id,
                    is_primary=True,
                ))

    emps = (
        await session.execute(
            select(DigitalEmployee).where(DigitalEmployee.department_id.is_(None))
        )
    ).scalars().all()
    for emp in emps:
        if emp.owner_id:
            owner = await session.get(User, emp.owner_id)
            if owner and owner.primary_department_id:
                emp.department_id = owner.primary_department_id

    await session.commit()


def _add_org_rbac_columns(sync_conn, schema: str | None = None) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    if inspector.has_table("users", schema=schema):
        cols = {c["name"] for c in inspector.get_columns("users", schema=schema)}
        if "primary_department_id" not in cols:
            if sync_conn.dialect.name == "sqlite":
                sync_conn.execute(text("ALTER TABLE users ADD COLUMN primary_department_id VARCHAR(36)"))
            else:
                sync_conn.execute(
                    text("ALTER TABLE users ADD COLUMN IF NOT EXISTS primary_department_id VARCHAR(36)")
                )
                sync_conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_users_primary_department_id ON users (primary_department_id)")
                )

    if inspector.has_table("digital_employees", schema=schema):
        cols = {c["name"] for c in inspector.get_columns("digital_employees", schema=schema)}
        if "department_id" not in cols:
            if sync_conn.dialect.name == "sqlite":
                sync_conn.execute(text("ALTER TABLE digital_employees ADD COLUMN department_id VARCHAR(36)"))
            else:
                sync_conn.execute(
                    text("ALTER TABLE digital_employees ADD COLUMN IF NOT EXISTS department_id VARCHAR(36)")
                )
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_digital_employees_department_id "
                        "ON digital_employees (department_id)"
                    )
                )

    _add_column(
        inspector, sync_conn, "digital_employees", "parent_employee_id", "VARCHAR(36)", schema=schema
    )
    _add_column(
        inspector, sync_conn, "digital_employees", "sort_order", "INTEGER DEFAULT 0 NOT NULL", schema=schema
    )
    if inspector.has_table("digital_employees", schema=schema) and sync_conn.dialect.name != "sqlite":
        sync_conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_digital_employees_parent_employee_id "
                "ON digital_employees (parent_employee_id)"
            )
        )

    _add_column(inspector, sync_conn, "users", "user_tier", "VARCHAR(32) DEFAULT 'staff' NOT NULL", schema=schema)
    _add_column(inspector, sync_conn, "departments", "liaison_user_id", "VARCHAR(36)", schema=schema)
    _add_column(inspector, sync_conn, "departments", "dept_tier", "VARCHAR(32) DEFAULT 'business' NOT NULL", schema=schema)
    _add_column(
        inspector, sync_conn, "data_source_tables", "object_type", "VARCHAR(16) DEFAULT 'table' NOT NULL", schema=schema
    )
    _add_column(inspector, sync_conn, "data_ask_audit_logs", "question", "TEXT", schema=schema)


def _add_column(inspector, sync_conn, table: str, col: str, col_def: str, schema: str | None = None) -> None:
    from sqlalchemy import text

    if not inspector.has_table(table, schema=schema):
        return
    cols = {c["name"] for c in inspector.get_columns(table, schema=schema)}
    if col in cols:
        return
    if sync_conn.dialect.name == "sqlite":
        sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
    else:
        sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_def}"))


def _ensure_users_table(sync_conn) -> None:
    pass  # create_all handles new tables


def _add_users_admin_column(sync_conn, schema: str | None = None) -> None:
    from sqlalchemy import inspect, text
    from app.config import settings

    inspector = inspect(sync_conn)
    if not inspector.has_table("users", schema=schema):
        return
    cols = {c["name"] for c in inspector.get_columns("users", schema=schema)}
    if "is_admin" not in cols:
        if sync_conn.dialect.name == "sqlite":
            sync_conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0 NOT NULL"))
        else:
            sync_conn.execute(
                text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE")
            )
    admin_no = settings.DEFAULT_ADMIN_EMPLOYEE_NO.replace("'", "''")
    sync_conn.execute(
        text(f"UPDATE users SET is_admin = TRUE WHERE employee_no = '{admin_no}' AND is_admin = FALSE")
    )


def _add_user_isolation_columns(sync_conn, schema: str | None = None) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    tables = {
        "agents": "agents",
        "workflows": "workflows",
        "conversations": "conversations",
        "knowledge_bases": "knowledge_bases",
        "skills": "skills",
        "digital_employees": "digital_employees",
    }
    for table in tables.values():
        if not inspector.has_table(table, schema=schema):
            continue
        cols = {c["name"] for c in inspector.get_columns(table, schema=schema)}
        if "owner_id" in cols:
            continue
        if sync_conn.dialect.name == "sqlite":
            sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN owner_id VARCHAR(36)"))
        else:
            sync_conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS owner_id VARCHAR(36)")
            )
            sync_conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_owner_id ON {table} (owner_id)"))


def _add_agent_visibility_columns(sync_conn, schema: str | None = None) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    if not inspector.has_table("agents", schema=schema):
        return
    _add_column(
        inspector,
        sync_conn,
        "agents",
        "visibility",
        "VARCHAR(32) DEFAULT 'private' NOT NULL",
        schema=schema,
    )
    sync_conn.execute(
        text("UPDATE agents SET visibility = 'platform' WHERE owner_id IS NULL")
    )
    sync_conn.execute(
        text(
            "UPDATE agents SET visibility = 'private' "
            "WHERE owner_id IS NOT NULL AND (visibility IS NULL OR visibility = '' OR visibility = 'private')"
        )
    )


async def seed_default_models(session) -> None:
    """Ensure canonical model configs exist and stay correct (idempotent)."""
    from sqlalchemy import select
    from app.db.models import ModelConfig
    from app.config import settings
    from app.models_hub.byd_catalog import byd_catalog_entries

    catalog: dict[tuple[str, str], dict] = {}
    default_inference = {"temperature": 0.7, "top_p": 0.9, "max_tokens": 4096}

    if settings.OPENAI_API_KEY:
        catalog[("openai", "gpt-4o-mini")] = dict(
            name="gpt-4o-mini (default)",
            provider="openai",
            model_id="gpt-4o-mini",
            is_default=False,
            is_active=True,
            context_window=128000,
            cost_per_1k_input=0.00015,
            cost_per_1k_output=0.0006,
            config={"inference": default_inference},
        )
        catalog[("openai", "gpt-4o")] = dict(
            name="gpt-4o",
            provider="openai",
            model_id="gpt-4o",
            is_default=False,
            is_active=True,
            context_window=128000,
            cost_per_1k_input=0.005,
            cost_per_1k_output=0.015,
            config={"inference": default_inference},
        )

    catalog.update(byd_catalog_entries())

    ollama_models = [
        ("qwen3.8-flash", 131072, "Qwen3.8 Flash via LiteLLM"),
        ("deepseek-chat", 131072, "DeepSeek Chat via LiteLLM"),
    ]
    for model_id, ctx, label in ollama_models:
        catalog[("ollama", model_id)] = dict(
            name=f"ollama/{model_id}",
            provider="ollama",
            model_id=model_id,
            base_url=settings.OLLAMA_BASE_URL,
            is_default=False,
            is_active=True,
            context_window=ctx,
            config={"label": label, "inference": default_inference},
        )

    STALE_MODEL_IDS = {"llama3.2"}

    result = await session.execute(select(ModelConfig))
    existing = {(c.provider, c.model_id): c for c in result.scalars().all()}

    for key, spec in catalog.items():
        cfg = existing.get(key)
        if cfg is None:
            session.add(ModelConfig(**spec))
        elif (spec.get("config") or {}).get("vendor") == "byd-eis":
            cfg.base_url = spec.get("base_url")
            cfg.api_key_encrypted = spec.get("api_key_encrypted")
            cfg.is_active = True
            cfg.context_window = spec.get("context_window") or cfg.context_window
            merged_cfg = dict(cfg.config or {})
            merged_cfg.update(spec.get("config") or {})
            cfg.config = merged_cfg
        elif cfg.provider == "ollama" and spec.get("base_url"):
            # Keep Ollama endpoint in sync with OLLAMA_BASE_URL in .env (migration-safe).
            cfg.base_url = spec["base_url"]
            cfg.is_active = True
        # Other existing rows are left unchanged so user edits in Model Hub persist.

    for (provider, model_id), cfg in existing.items():
        if (
            (provider, model_id) not in catalog
            or model_id in STALE_MODEL_IDS
            or ":cloud" in model_id
        ):
            cfg.is_active = False
            cfg.is_default = False

    await session.flush()

    from app.models_hub.connectivity import apply_connectivity_default

    await apply_connectivity_default(session)
    await session.commit()


async def seed_default_excel_parse_template(session) -> None:
    from sqlalchemy import select
    from app.db.models import ExcelParseTemplate

    existing = (
        await session.execute(
            select(ExcelParseTemplate).where(ExcelParseTemplate.id == "bs_template_v1").limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        return

    session.add(
        ExcelParseTemplate(
            id="bs_template_v1",
            owner_id=None,
            name="门店销售额",
            type="XS",
            is_global=True,
            description="Default sample template migrated from excel_parser",
            sheet_mappings=[
                {
                    "sheet_name": "Sheet1",
                    "field_mapping": [
                        {"field_name": "门店名称", "cell_ref": "B2"},
                        {"field_name": "销售", "cell_ref": "C2"},
                    ],
                },
                {
                    "sheet_name": "Sheet2",
                    "field_mapping": {"客单价": "B2"},
                },
            ],
        )
    )
    await session.commit()


async def seed_template_agents(session) -> None:
    from sqlalchemy import select
    from app.db.models import Agent, AgentStatus, AgentVisibility
    from app.config import settings

    result = await session.execute(select(Agent).limit(1))
    if result.scalar_one_or_none():
        return

    provider = settings.DEFAULT_LLM_PROVIDER
    model = settings.DEFAULT_LLM_MODEL

    templates = [
        dict(name="深度研究分析师", role="Senior Research Analyst",
             goal="针对任意主题进行深度网络搜索，整合多来源信息，输出结构化分析报告。",
             backstory="拥有 10 年信息研究经验，擅长从海量信息中提炼核心洞见。",
             tools_config=[{"tool_name": "web_search"}, {"tool_name": "datetime"}], temperature=0.3),
        dict(name="全栈代码助手", role="Full-Stack Software Engineer",
             goal="理解需求后编写高质量代码，涵盖前端、后端、SQL 及 Shell 脚本。",
             backstory="10 年全栈开发经验，精通 Python、TypeScript、SQL。",
             tools_config=[{"tool_name": "calculator"}], temperature=0.2),
        dict(name="营销内容创作官", role="Chief Content & Copywriting Officer",
             goal="撰写高转化率的营销文案、社媒帖子、博客文章和邮件模板。",
             backstory="曾服务 50+ 国内外品牌，精通 AIDA 和故事化营销。",
             tools_config=[{"tool_name": "web_search"}], temperature=0.8),
        dict(name="数据分析专家", role="Data Analyst & Visualization Expert",
             goal="基于真实可溯源的数据进行统计分析、机器学习建模、趋势预测和异常检测，输出可验证的业务洞察与可视化图表。严格禁止编造、填充或臆测任何数据。",
             backstory="统计学硕士，精通 Pandas、NumPy、scikit-learn、statsmodels。擅长：回归分析(线性/逻辑回归)、时间序列预测(ARIMA/指数平滑)、聚类分析(K-Means/DBSCAN)、异常检测(IQR/Z-score/孤立森林)、相关性分析(皮尔逊/斯皮尔曼)、假设检验(t检验/卡方)。坚持数据驱动原则：所有结论必须基于真实数据，数据来源必须可溯源，无法获取数据时如实说明，绝不编造数字。",
             tools_config=[{"tool_name": "web_search"}, {"tool_name": "http_request"}, {"tool_name": "calculator"}, {"tool_name": "datetime"}], temperature=0.2),
        dict(name="网络安全顾问", role="Senior Cybersecurity Consultant",
             goal="审查代码和架构中的安全漏洞，提供修复方案。",
             backstory="CISSP 持证专家，熟悉 OWASP Top 10 和等保合规。",
             tools_config=[{"tool_name": "web_search"}, {"tool_name": "http_request"}], temperature=0.2),
        dict(name="产品经理助手", role="Senior Product Manager",
             goal="梳理产品需求，撰写 PRD、用户故事和验收标准。",
             backstory="曾主导多个 B2B SaaS 从 0→1 项目。",
             tools_config=[{"tool_name": "web_search"}, {"tool_name": "datetime"}], temperature=0.5),
        dict(name="翻译与本地化专家", role="Translation & Localization Specialist",
             goal="提供中英日韩等多语言互译，确保专业术语准确。",
             backstory="母语中文，英语 C2，熟悉 i18n/L10n 工程化流程。",
             tools_config=[], temperature=0.4),
        dict(name="DevOps 自动化工程师", role="DevOps & Site Reliability Engineer",
             goal="设计 CI/CD 流水线、Docker/K8s 编排和监控告警体系。",
             backstory="8 年 DevOps 经验，精通 GitHub Actions、Kubernetes。",
             tools_config=[{"tool_name": "http_request"}, {"tool_name": "calculator"}, {"tool_name": "datetime"}], temperature=0.2),
    ]

    for tpl in templates:
        from app.core.agents.i18n import merge_agent_metadata_i18n
        from app.core.agents.seed_i18n import seed_agent_i18n

        i18n = seed_agent_i18n(tpl["name"])
        session.add(Agent(
            id=generate_uuid(),
            name=tpl["name"],
            role=tpl["role"],
            goal=tpl["goal"],
            backstory=tpl.get("backstory", ""),
            llm_provider=provider,
            llm_model=model,
            temperature=tpl.get("temperature", 0.7),
            max_iterations=10,
            tools_config=tpl.get("tools_config", []),
            memory_config={},
            status=AgentStatus.active,
            visibility=AgentVisibility.platform.value,
            metadata_=merge_agent_metadata_i18n({"template": "seed"}, i18n) if i18n else {},
        ))

    await session.commit()


async def seed_desktop_operator_agent(session) -> None:
    from sqlalchemy import select
    from app.db.models import Agent, AgentStatus, AgentVisibility
    from app.config import settings
    from app.core.agents.i18n import merge_agent_metadata_i18n
    from app.core.agents.seed_i18n import seed_agent_i18n

    result = await session.execute(select(Agent).where(Agent.name == "桌面操作员"))
    if result.scalar_one_or_none():
        return

    tpl = dict(
        name="桌面操作员",
        role="Desktop GUI Automation Operator",
        goal="根据用户目标选择并执行已录制的桌面 GUI 演示，完成 legacy 系统（SAP、Excel 桌面版等）操作；"
             "录制新演示前先确认 Sidecar 在线。",
        backstory="熟悉 Windows 桌面自动化与 GUI 演示回放；"
                  "执行前会列出可用演示，执行后汇报结果与异常。",
        tools_config=[
            {"tool_name": "desktop_list_demos"},
            {"tool_name": "desktop_replay"},
            {"tool_name": "desktop_capture"},
            {"tool_name": "datetime"},
        ],
        temperature=0.3,
    )
    i18n = seed_agent_i18n(tpl["name"])
    session.add(Agent(
        id=generate_uuid(),
        name=tpl["name"],
        role=tpl["role"],
        goal=tpl["goal"],
        backstory=tpl.get("backstory", ""),
        llm_provider=settings.DEFAULT_LLM_PROVIDER,
        llm_model=settings.DEFAULT_LLM_MODEL,
        temperature=tpl.get("temperature", 0.3),
        max_iterations=12,
        tools_config=tpl.get("tools_config", []),
        memory_config={},
        status=AgentStatus.active,
        visibility=AgentVisibility.platform.value,
        metadata_=merge_agent_metadata_i18n({"template": "desktop_automation"}, i18n) if i18n else {"template": "desktop_automation"},
    ))
    await session.commit()


async def seed_template_skills(session) -> None:
    from sqlalchemy import select
    from app.db.models import Skill, SkillStatus

    result = await session.execute(select(Skill).limit(1))
    if result.scalar_one_or_none():
        return

    templates = [
        dict(
            slug="code-review",
            display_name="代码审查",
            description=(
                "Reviews code for quality, security, and maintainability following team standards. "
                "Use when reviewing pull requests, code changes, or when the user asks for a code review."
            ),
            instructions_md="""## Quick Start

When reviewing code:

1. Check correctness and edge cases
2. Verify security (injection, auth, secrets)
3. Assess readability and maintainability
4. Confirm tests cover the change

## Feedback format

- **Critical**: Must fix before merge
- **Suggestion**: Consider improving
- **Nice to have**: Optional enhancement
""",
            status=SkillStatus.active,
            tags=["dev", "review"],
        ),
        dict(
            slug="commit-message",
            display_name="Git 提交信息",
            description=(
                "Generates descriptive commit messages by analyzing git diffs. "
                "Use when the user asks for help writing commit messages or reviewing staged changes."
            ),
            instructions_md="""## Format

Use Conventional Commits:

```
type(scope): short summary

Optional body explaining why and what changed.
```

Types: feat, fix, docs, refactor, test, chore

## Example

Input: Added JWT login endpoint
Output:
```
feat(auth): add JWT login endpoint

Implement token issuance and validation middleware.
```
""",
            status=SkillStatus.active,
            tags=["git", "dev"],
        ),
    ]

    for tpl in templates:
        session.add(Skill(
            id=generate_uuid(),
            slug=tpl["slug"],
            display_name=tpl["display_name"],
            description=tpl["description"],
            instructions_md=tpl["instructions_md"],
            status=tpl["status"],
            scope="global",
            auto_invoke=False,
            tags=tpl.get("tags", []),
        ))

    await session.commit()


async def ensure_bundled_skills(session) -> None:
    from app.core.skills.bundled import ensure_bundled_skills as _ensure
    await _ensure(session)


async def seed_template_employees(session) -> None:
    from sqlalchemy import select
    from app.db.models import (
        Agent, DigitalEmployee, EmployeeScheduledTask,
        EmployeeStatus, ScheduleType, EmployeeTaskType,
    )
    from app.core.employees.schedule import compute_next_run

    result = await session.execute(select(DigitalEmployee).limit(1))
    if result.scalar_one_or_none():
        return

    agent_result = await session.execute(
        select(Agent).where(Agent.name == "深度研究分析师").limit(1)
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        agent = (await session.execute(select(Agent).limit(1))).scalar_one_or_none()
    if not agent:
        return

    emp_id = generate_uuid()
    session.add(DigitalEmployee(
        id=emp_id,
        name="小研",
        title="研究助理",
        description="负责定时信息搜集与简报生成，绑定深度研究分析师智能体。",
        status=EmployeeStatus.active,
        agent_id=agent.id,
        skills_config=[],
        timezone="Asia/Shanghai",
    ))

    task = EmployeeScheduledTask(
        id=generate_uuid(),
        employee_id=emp_id,
        name="工作日早报",
        description="每个工作日上午 9 点生成简要行业动态摘要",
        enabled=True,
        schedule_type=ScheduleType.cron,
        cron_expression="0 9 * * 1-5",
        timezone="Asia/Shanghai",
        task_type=EmployeeTaskType.agent,
        task_config={
            "prompt": "请用 3-5 条要点总结今日 AI 与自动化领域的值得关注动态，中文输出。",
        },
    )
    task.next_run_at = compute_next_run(
        "cron",
        cron_expression=task.cron_expression,
        timezone_name=task.timezone,
    )
    session.add(task)
    await session.commit()


async def seed_template_workflows(session) -> None:
    from sqlalchemy import select
    from app.db.models import Workflow, WorkflowStatus, ProcessType

    result = await session.execute(select(Workflow).limit(1))
    if result.scalar_one_or_none():
        return

    def n(id_, type_, label, x, y, config=None):
        rf_type = {
            "start": "startNode", "end": "endNode", "agent": "agentNode",
            "llm": "llmNode", "tool": "toolNode", "condition": "conditionNode",
            "human": "humanNode", "http": "httpNode", "code": "codeNode", "note": "noteNode",
        }.get(type_, "agentNode")
        return {"id": id_, "type": rf_type, "label": label,
                "position": {"x": x, "y": y}, "config": config or {}}

    def e(src, tgt, label=None):
        return {"id": f"{src}->{tgt}", "source": src, "target": tgt,
                **({"label": label} if label else {})}

    templates = [
        dict(name="深度研究报告生成", description="搜索 → LLM 分析 → 人工确认 → 输出报告",
             process_type="sequential",
             graph=dict(nodes=[
                 n("start", "start", "开始", 250, 40),
                 n("search", "tool", "网络搜索", 250, 160, {"tool_name": "web_search"}),
                 n("llm1", "llm", "综合分析", 250, 280, {"prompt": "基于搜索结果撰写结构化研究报告。"}),
                 n("human", "human", "人工确认", 250, 400, {"prompt": "请检查报告内容"}),
                 n("end", "end", "输出报告", 250, 520),
             ], edges=[e("start", "search"), e("search", "llm1"), e("llm1", "human"), e("human", "end")])),
        dict(name="代码安全审查流水线", description="安全扫描 → 条件路由 → 修复或通过",
             process_type="sequential",
             graph=dict(nodes=[
                 n("start", "start", "输入代码", 260, 40),
                 n("scan", "agent", "安全扫描", 260, 160, {"role": "网络安全顾问"}),
                 n("cond", "condition", "发现漏洞？", 260, 300, {"expression": "'HIGH' in str(state.get('scan_result',''))"}),
                 n("fix", "agent", "生成修复方案", 80, 420, {"role": "全栈代码助手"}),
                 n("pass_", "llm", "生成通过报告", 440, 420, {"prompt": "代码安全审查通过，生成简短报告"}),
                 n("end", "end", "审查完成", 260, 540),
             ], edges=[e("start", "scan"), e("scan", "cond"),
                       e("cond", "fix", "有漏洞"), e("cond", "pass_", "无漏洞"),
                       e("fix", "end"), e("pass_", "end")])),
    ]

    for tpl in templates:
        session.add(Workflow(
            id=generate_uuid(),
            name=tpl["name"],
            description=tpl["description"],
            status=WorkflowStatus.active,
            process_type=ProcessType(tpl["process_type"]),
            graph_definition=tpl["graph"],
            agents_config=[],
            triggers_config=[],
        ))

    await session.commit()


PLATFORM_KB_NAME = "AI-AGENT 平台文档"
PLATFORM_ROADMAP_FILENAME = "platform-roadmap.md"


async def seed_platform_knowledge_base(session) -> None:
    """Seed a knowledge base with platform roadmap / future plans (idempotent)."""
    import hashlib
    import structlog
    from pathlib import Path
    from sqlalchemy import select
    from app.db.models import KnowledgeBase, Document, KBStatus
    from app.knowledge.pipeline import IngestionPipeline
    from app.knowledge.storage import save_document_file
    from app.config import settings

    log = structlog.get_logger(__name__)

    async def _ingest_doc(kb_obj: KnowledgeBase, doc_obj: Document, file_bytes: bytes) -> None:
        pipeline = IngestionPipeline(
            knowledge_base_id=kb_obj.id,
            embedding_model=kb_obj.embedding_model,
            chunk_size=kb_obj.chunk_size,
            chunk_overlap=kb_obj.chunk_overlap,
        )
        chunk_count = await pipeline.ingest_file(
            file_bytes, PLATFORM_ROADMAP_FILENAME, doc_obj.id
        )
        doc_obj.status = KBStatus.ready
        doc_obj.chunk_count = chunk_count
        doc_obj.file_size = len(file_bytes)
        kb_obj.status = KBStatus.ready

    result = await session.execute(
        select(KnowledgeBase).where(KnowledgeBase.name == PLATFORM_KB_NAME).limit(1)
    )
    kb = result.scalar_one_or_none()

    data_path = (
        Path(__file__).resolve().parent.parent
        / "knowledge"
        / "data"
        / PLATFORM_ROADMAP_FILENAME
    )
    if not data_path.is_file():
        log.warning("platform_kb_seed_skipped", reason="roadmap file missing", path=str(data_path))
        return

    file_bytes = data_path.read_bytes()
    content_sha256 = hashlib.sha256(file_bytes).hexdigest()

    if kb:
        doc_result = await session.execute(
            select(Document).where(
                Document.knowledge_base_id == kb.id,
                Document.filename == PLATFORM_ROADMAP_FILENAME,
            ).limit(1)
        )
        existing_doc = doc_result.scalar_one_or_none()
        if existing_doc:
            stored_hash = (existing_doc.metadata_ or {}).get("content_sha256")
            if not existing_doc.storage_path:
                existing_doc.storage_path = save_document_file(
                    kb.id, existing_doc.id, PLATFORM_ROADMAP_FILENAME, file_bytes
                )
                existing_doc.metadata_ = {
                    **(existing_doc.metadata_ or {}),
                    "content_sha256": content_sha256,
                }
                await session.commit()
                log.info("platform_kb_storage_backfilled", doc_id=existing_doc.id)
            if stored_hash == content_sha256 and existing_doc.status == KBStatus.ready:
                return
            try:
                pipeline = IngestionPipeline(
                    knowledge_base_id=kb.id,
                    embedding_model=kb.embedding_model,
                    chunk_size=kb.chunk_size,
                    chunk_overlap=kb.chunk_overlap,
                )
                await pipeline.vector_store.delete_document(existing_doc.id)
            except Exception as exc:
                log.warning("platform_kb_reindex_delete_failed", error=str(exc))
            existing_doc.storage_path = save_document_file(
                kb.id, existing_doc.id, PLATFORM_ROADMAP_FILENAME, file_bytes
            )
            existing_doc.status = KBStatus.processing
            existing_doc.metadata_ = {
                **(existing_doc.metadata_ or {}),
                "seed": "platform-roadmap",
                "content_sha256": content_sha256,
            }
            await session.flush()
            try:
                await _ingest_doc(kb, existing_doc, file_bytes)
                await session.commit()
                log.info(
                    "platform_kb_reindexed",
                    kb_id=kb.id,
                    doc_id=existing_doc.id,
                    chunks=existing_doc.chunk_count,
                )
            except Exception as exc:
                existing_doc.status = KBStatus.error
                existing_doc.metadata_ = {
                    **(existing_doc.metadata_ or {}),
                    "error": str(exc),
                }
                kb.status = KBStatus.error
                await session.commit()
                log.warning(
                    "platform_kb_reindex_failed",
                    kb_id=kb.id,
                    error=str(exc),
                    hint="Ensure Ollama is running for embedding ingestion",
                )
            return
    else:
        kb = KnowledgeBase(
            id=generate_uuid(),
            name=PLATFORM_KB_NAME,
            description="AI-AGENT 产品规划、开发路线与平台说明，供检索与问答参考。",
            status=KBStatus.processing,
            embedding_model=settings.DEFAULT_EMBEDDING_MODEL,
            chunk_size=1000,
            chunk_overlap=200,
            metadata_={"seed": "platform-docs", "category": "roadmap"},
        )
        session.add(kb)
        await session.flush()

    doc_id = generate_uuid()
    doc = Document(
        id=doc_id,
        knowledge_base_id=kb.id,
        filename=PLATFORM_ROADMAP_FILENAME,
        file_type="md",
        file_size=len(file_bytes),
        status=KBStatus.processing,
        storage_path=save_document_file(kb.id, doc_id, PLATFORM_ROADMAP_FILENAME, file_bytes),
        metadata_={"seed": "platform-roadmap", "content_sha256": content_sha256},
    )
    session.add(doc)
    await session.flush()

    try:
        await _ingest_doc(kb, doc, file_bytes)
        kb.document_count = (kb.document_count or 0) + 1
        await session.commit()
        log.info(
            "platform_kb_seeded",
            kb_id=kb.id,
            doc_id=doc_id,
            chunks=doc.chunk_count,
        )
    except Exception as exc:
        doc.status = KBStatus.error
        doc.metadata_ = {**(doc.metadata_ or {}), "error": str(exc)}
        kb.status = KBStatus.error
        await session.commit()
        log.warning(
            "platform_kb_seed_failed",
            kb_id=kb.id,
            error=str(exc),
            hint="Ensure Ollama is running for embedding ingestion",
        )


def _ensure_knowledge_permissions(sync_conn) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    if not inspector.has_table("knowledge_bases"):
        return
    cols = {c["name"] for c in inspector.get_columns("knowledge_bases")}
    if "visibility" not in cols:
        sync_conn.execute(text(
            "ALTER TABLE knowledge_bases ADD COLUMN visibility VARCHAR(32) NOT NULL DEFAULT 'private'"
        ))
        sync_conn.execute(text(
            "UPDATE knowledge_bases SET visibility = 'public' WHERE owner_id IS NULL"
        ))
    if not inspector.has_table("knowledge_base_grants"):
        from app.db.base import Base

        table = Base.metadata.tables.get("knowledge_base_grants")
        if table is not None:
            table.create(sync_conn, checkfirst=True)


def _ensure_knowledge_quality(sync_conn) -> None:
    from sqlalchemy import inspect
    from app.db.base import Base

    inspector = inspect(sync_conn)
    for name in ("knowledge_passages", "knowledge_faq_entries", "knowledge_wecom_sources"):
        if not inspector.has_table(name):
            table = Base.metadata.tables.get(name)
            if table is not None:
                table.create(sync_conn, checkfirst=True)
