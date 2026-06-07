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
    seed_platform_knowledge_base,
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
        await seed_template_workflows(session)
        await seed_template_skills(session)
        await seed_template_employees(session)
        await seed_platform_knowledge_base(session)
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
        "AI-AGENT - Unified AI Agent Platform combining CrewAI, LangGraph, "
        "LangChain, Dify, n8n, and LangFlow capabilities."
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
async def sqlite_operational_error_handler(_request, exc: OperationalError):
    logger.error("database_operational_error", error=str(exc))
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "数据库繁忙（SQLite 被锁定）。请确保只运行一个后端实例，"
                "然后重新执行 E:\\AIAGNET\\start_backend.ps1"
            ),
        },
    )


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
