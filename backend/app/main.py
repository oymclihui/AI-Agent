"""
AI-AGENT Platform - Main FastAPI Application
"""
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
    seed_desktop_operator_agent, seed_org_rbac,
)
from app.db.session import AsyncSessionLocal
from app.core.tools.registry import ToolRegistry
from app.core.employees.scheduler import EmployeeScheduler

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("aiagnet_startup", version=settings.APP_VERSION)

    # Initialize database tables
    await init_db(engine)
    logger.info("database_initialized")

    # Seed default model configs
    async with AsyncSessionLocal() as session:
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
    logger.info("default_models_seeded")

    # Pre-load tool registry
    ToolRegistry.get_instance()
    logger.info("tool_registry_loaded")

    await EmployeeScheduler.get_instance().start()
    logger.info("employee_scheduler_started")

    yield

    await EmployeeScheduler.get_instance().stop()
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

app.include_router(api_router)


@app.exception_handler(OperationalError)
async def database_operational_error_handler(_request, exc: OperationalError):
    logger.error("database_operational_error", error=str(exc))
    if settings.DATABASE_URL.startswith("sqlite"):
        detail = (
            "数据库繁忙（SQLite 被锁定）。请确保只运行一个后端实例，"
            "然后重新执行 start_backend.ps1；或改用 PostgreSQL（配置 DB_HOST / DATABASE_URL）。"
        )
    else:
        detail = "数据库连接异常，请检查 PostgreSQL / VastBase 是否可达以及 DATABASE_URL / DB_* 配置是否正确。"
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
