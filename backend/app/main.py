"""
AIAGNET Platform - Main FastAPI Application
"""
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.router import api_router
from app.db.session import engine
from app.db.init_db import init_db, seed_default_models, seed_template_agents, seed_template_workflows
from app.db.session import AsyncSessionLocal
from app.core.tools.registry import ToolRegistry

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
    logger.info("default_models_seeded")

    # Pre-load tool registry
    ToolRegistry.get_instance()
    logger.info("tool_registry_loaded")

    yield

    logger.info("aiagnet_shutdown")
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "AIAGNET - Unified AI Agent Platform combining CrewAI, LangGraph, "
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


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
