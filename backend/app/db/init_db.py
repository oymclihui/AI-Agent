"""
Database initialization: creates all tables and seeds default data.
"""
from sqlalchemy.ext.asyncio import AsyncEngine
from app.db.base import Base, generate_uuid
from app.db import models  # noqa: F401 - ensure all models are registered


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        if str(engine.url).startswith("sqlite"):
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            await conn.exec_driver_sql("PRAGMA busy_timeout=30000")
        await conn.run_sync(Base.metadata.create_all)
    await _migrate_schema(engine)


async def _migrate_schema(engine: AsyncEngine) -> None:
    """Lightweight schema patches for SQLite (create_all does not alter existing tables)."""
    if not str(engine.url).startswith("sqlite"):
        return
    async with engine.begin() as conn:
        result = await conn.exec_driver_sql("PRAGMA table_info(agents)")
        cols = {row[1] for row in result.fetchall()}
        if "skills_config" not in cols:
            await conn.exec_driver_sql(
                "ALTER TABLE agents ADD COLUMN skills_config JSON DEFAULT '[]'"
            )


async def seed_default_models(session) -> None:
    """Ensure canonical model configs exist and stay correct (idempotent)."""
    from sqlalchemy import select
    from app.db.models import ModelConfig
    from app.config import settings

    catalog: dict[tuple[str, str], dict] = {}

    if settings.OPENAI_API_KEY:
        catalog[("openai", "gpt-4o-mini")] = dict(
            name="gpt-4o-mini (default)",
            provider="openai",
            model_id="gpt-4o-mini",
            is_default=True,
            is_active=True,
            context_window=128000,
            cost_per_1k_input=0.00015,
            cost_per_1k_output=0.0006,
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
        )

    ollama_models = [
        ("qwen3.6:35b", True, 32768, "Qwen3.6 35B local"),
        ("gemma4:31b", False, 32768, "Gemma4 31B local"),
        ("kimi-k2.6:cloud", False, 131072, "Kimi K2.6 cloud-routed"),
        ("deepseek-v4-pro:cloud", False, 65536, "DeepSeek V4 Pro cloud-routed"),
        ("deepseek-v4-flash:cloud", False, 65536, "DeepSeek V4 Flash cloud-routed"),
        ("qwen3.5:cloud", False, 32768, "Qwen3.5 cloud-routed"),
    ]
    for model_id, is_default, ctx, label in ollama_models:
        catalog[("ollama", model_id)] = dict(
            name=f"ollama/{model_id}",
            provider="ollama",
            model_id=model_id,
            base_url=settings.OLLAMA_BASE_URL,
            is_default=is_default and not bool(settings.OPENAI_API_KEY),
            is_active=True,
            context_window=ctx,
            config={"label": label},
        )

    STALE_MODEL_IDS = {"llama3.2"}

    result = await session.execute(select(ModelConfig))
    existing = {(c.provider, c.model_id): c for c in result.scalars().all()}

    for key, spec in catalog.items():
        cfg = existing.get(key)
        if cfg is None:
            session.add(ModelConfig(**spec))
        else:
            for field, value in spec.items():
                setattr(cfg, field, value)

    for (provider, model_id), cfg in existing.items():
        if (provider, model_id) not in catalog or model_id in STALE_MODEL_IDS:
            cfg.is_active = False
            cfg.is_default = False

    active = [c for c in existing.values() if c.is_active]
    defaults = [c for c in active if c.is_default]
    if not defaults:
        target_key = ("openai", "gpt-4o-mini") if settings.OPENAI_API_KEY else ("ollama", "qwen3.6:35b")
        target = existing.get(target_key)
        if target:
            target.is_default = True
    elif len(defaults) > 1:
        keep = ("openai", "gpt-4o-mini") if settings.OPENAI_API_KEY else ("ollama", "qwen3.6:35b")
        for cfg in defaults:
            cfg.is_default = (cfg.provider, cfg.model_id) == keep

    await session.commit()


async def seed_template_agents(session) -> None:
    from sqlalchemy import select
    from app.db.models import Agent, AgentStatus
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
             goal="进行统计分析、趋势识别和异常检测，输出业务解读。",
             backstory="统计学硕士，精通 Pandas、NumPy、Matplotlib。",
             tools_config=[{"tool_name": "calculator"}, {"tool_name": "datetime"}], temperature=0.3),
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
    import structlog
    from pathlib import Path
    from sqlalchemy import select
    from app.db.models import KnowledgeBase, Document, KBStatus
    from app.knowledge.pipeline import IngestionPipeline
    from app.knowledge.storage import save_document_file
    from app.config import settings

    log = structlog.get_logger(__name__)

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

    if kb:
        doc_result = await session.execute(
            select(Document).where(
                Document.knowledge_base_id == kb.id,
                Document.filename == PLATFORM_ROADMAP_FILENAME,
            ).limit(1)
        )
        existing_doc = doc_result.scalar_one_or_none()
        if existing_doc:
            if not existing_doc.storage_path:
                file_bytes = data_path.read_bytes()
                existing_doc.storage_path = save_document_file(
                    kb.id, existing_doc.id, PLATFORM_ROADMAP_FILENAME, file_bytes
                )
                await session.commit()
                log.info("platform_kb_storage_backfilled", doc_id=existing_doc.id)
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

    file_bytes = data_path.read_bytes()
    doc_id = generate_uuid()
    doc = Document(
        id=doc_id,
        knowledge_base_id=kb.id,
        filename=PLATFORM_ROADMAP_FILENAME,
        file_type="md",
        file_size=len(file_bytes),
        status=KBStatus.processing,
        storage_path=save_document_file(kb.id, doc_id, PLATFORM_ROADMAP_FILENAME, file_bytes),
        metadata_={"seed": "platform-roadmap"},
    )
    session.add(doc)
    await session.flush()

    try:
        pipeline = IngestionPipeline(
            knowledge_base_id=kb.id,
            embedding_model=kb.embedding_model,
            chunk_size=kb.chunk_size,
            chunk_overlap=kb.chunk_overlap,
        )
        chunk_count = await pipeline.ingest_file(
            file_bytes, PLATFORM_ROADMAP_FILENAME, doc_id
        )
        doc.status = KBStatus.ready
        doc.chunk_count = chunk_count
        kb.document_count = (kb.document_count or 0) + 1
        kb.status = KBStatus.ready
        await session.commit()
        log.info(
            "platform_kb_seeded",
            kb_id=kb.id,
            doc_id=doc_id,
            chunks=chunk_count,
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
