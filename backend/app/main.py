"""
AI-AGENT Platform - Main FastAPI Application
"""
import asyncio

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.api.router import api_router
from app.db.session import engine
from app.db.init_db import (
    init_db, seed_default_models, seed_template_agents,
    seed_template_workflows, seed_template_skills, seed_template_employees,
    seed_platform_knowledge_base, ensure_bundled_skills, seed_default_admin,
    seed_desktop_operator_agent, seed_org_rbac, seed_default_excel_parse_template,
    seed_runbooks, seed_analysis_operators,
)
from app.db.session import AsyncSessionLocal
from app.core.tools.registry import ToolRegistry
from app.core.employees.scheduler import EmployeeScheduler
from app.core.wecom.listener import wecom_link
from app.knowledge.wecom_docs import wecom_doc_sync

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("aiagnet_startup", version=settings.APP_VERSION)

    db_ready = False
    db_schema = settings.DB_SCHEMA if settings.DB_SCHEMA and settings.DB_SCHEMA != "public" else None
    try:
        await init_db(engine, schema=db_schema)
        logger.info("database_initialized")
        db_ready = True
    except Exception as exc:
        logger.warning(
            "database_startup_deferred",
            error=str(exc),
            hint="Open /setup in the browser to configure PostgreSQL or VastBase.",
        )

    if db_ready:
        try:
            async with AsyncSessionLocal() as session:
                await seed_default_models(session)
                await seed_default_excel_parse_template(session)
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
                await seed_runbooks(session)
                await seed_analysis_operators(session)
            logger.info("default_models_seeded")
        except Exception as exc:
            logger.warning("database_seed_deferred", error=str(exc))

    ToolRegistry.get_instance()
    logger.info("tool_registry_loaded")

    if db_ready:
        try:
            await EmployeeScheduler.get_instance().start()
            logger.info("employee_scheduler_started")
        except Exception as exc:
            logger.warning("employee_scheduler_start_failed", error=str(exc))
        try:
            wecom_link.start()
            logger.info("wecom_link_started")
            wecom_doc_sync.start()
        except Exception as exc:
            logger.warning("wecom_link_start_failed", error=str(exc))
        try:
            # 发件箱派遣循环：pending 消息保序发送、退避重试、重启补发
            from app.core.tasks.outbox import start_outbox_dispatcher

            start_outbox_dispatcher()
        except Exception as exc:
            logger.warning("outbox_dispatcher_start_failed", error=str(exc))
        try:
            # 任务化恢复：收尾上次进程遗留的 queued/working 任务并通知用户
            from app.core.wecom.inbound import recover_interrupted_tasks

            asyncio.create_task(recover_interrupted_tasks())
        except Exception as exc:
            logger.warning("task_recover_start_failed", error=str(exc))
        try:
            # 主动工作引擎（蓝图阶段三）：定时规则跑 observe/auto
            from app.core.proactive import start_proactive_engine

            start_proactive_engine()
            logger.info("proactive_engine_started")
        except Exception as exc:
            logger.warning("proactive_engine_start_failed", error=str(exc))
        try:
            # 问数热点预计算（蓝图一期 L4）：定时回填结果缓存，首次提问即命中
            from app.core.data_ask.prewarm import start_prewarm_engine

            start_prewarm_engine()
            logger.info("dataask_prewarm_started")
        except Exception as exc:
            logger.warning("dataask_prewarm_start_failed", error=str(exc))

    yield

    try:
        from app.core.proactive import stop_proactive_engine

        await stop_proactive_engine()
    except Exception:
        pass
    try:
        from app.core.tasks.outbox import stop_outbox_dispatcher

        await stop_outbox_dispatcher()
    except Exception:
        pass
    try:
        await wecom_doc_sync.stop()
        await wecom_link.stop()
    except Exception:
        pass
    try:
        await EmployeeScheduler.get_instance().stop()
    except Exception:
        pass
    logger.info("aiagnet_shutdown")
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "AI-AGENT — Digital employees connect thinking, skills, workflows, "
        "knowledge, and scheduled tasks into one complete AI workforce pipeline."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Redis IP 级 API 限流中间件（Redis 不可用时自动放行，不阻塞业务）──
@app.middleware("http")
async def api_rate_limit_middleware(request, call_next):
    import os as _os
    if _os.getenv("API_RATELIMIT_ENABLED", "true").strip().lower() in ("1", "true", "yes"):
        try:
            if request.url.path.startswith("/api/"):
                from app.core.cache.redis_cache import rate_limit_check, API_RATELIMIT_PER_MIN
                _ip = (
                    request.headers.get("x-real-ip")
                    or ((request.headers.get("x-forwarded-for") or "").split(",")[0].strip())
                    or (request.client.host if request.client else "unknown")
                )
                _ok, _cnt = await rate_limit_check(f"ratelimit:ip:{_ip}", limit=API_RATELIMIT_PER_MIN)
                if not _ok:
                    return JSONResponse(
                        status_code=429,
                        content={"detail": f"请求过于频繁（每 IP 每分钟限 {API_RATELIMIT_PER_MIN} 次），请稍后再试"},
                    )
        except Exception:
            pass
    return await call_next(request)


app.include_router(api_router)


@app.exception_handler(OperationalError)
async def database_operational_error_handler(_request, exc: OperationalError):
    logger.error("database_operational_error", error=str(exc))
    detail = (
        "数据库连接异常，请检查 PostgreSQL / VastBase 是否可达，"
        "以及 DATABASE_URL / DB_HOST 等配置是否正确。"
    )
    return JSONResponse(status_code=503, content={"detail": detail})


@app.get("/health")
async def health_check():
    from app.config import settings as app_settings
    from sqlalchemy import text

    db_status = "unknown"
    db_backend = app_settings.resolved_db_driver
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:
        db_status = f"error: {exc}"

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "database": {"backend": db_backend, "status": db_status},
    }
