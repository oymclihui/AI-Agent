"""
Database initialization: creates all tables and seeds default data.
"""
from sqlalchemy.ext.asyncio import AsyncEngine
from app.db.base import Base, generate_uuid
from app.db import models  # noqa: F401 - ensure all models are registered


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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
