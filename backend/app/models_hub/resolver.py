"""Resolve ModelConfig rows from the database for LLM routing."""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ModelConfig
from app.db.session import AsyncSessionLocal
from app.schemas.model_inference import extract_inference_params, ModelInferenceParams


async def resolve_model_config(
    provider: str | None,
    model: str | None,
    db: AsyncSession | None = None,
) -> tuple[Optional[ModelConfig], ModelInferenceParams]:
    """Find active ModelConfig by provider+model_id, else fall back to default."""
    if not provider and not model:
        cfg = await _fetch_default(db)
        return cfg, extract_inference_params(cfg.config if cfg else None)

    async def _lookup(session: AsyncSession) -> Optional[ModelConfig]:
        if provider and model:
            result = await session.execute(
                select(ModelConfig).where(
                    ModelConfig.is_active == True,
                    ModelConfig.provider == provider.lower(),
                    ModelConfig.model_id == model,
                ).limit(1)
            )
            found = result.scalar_one_or_none()
            if found:
                return found
        return await _fetch_default(session)

    if db is not None:
        cfg = await _lookup(db)
    else:
        async with AsyncSessionLocal() as session:
            cfg = await _lookup(session)

    return cfg, extract_inference_params(cfg.config if cfg else None)


async def _fetch_default(db: AsyncSession | None) -> Optional[ModelConfig]:
    async def _query(session: AsyncSession) -> Optional[ModelConfig]:
        result = await session.execute(
            select(ModelConfig).where(
                ModelConfig.is_active == True,
                ModelConfig.is_default == True,
            ).limit(1)
        )
        return result.scalar_one_or_none()

    if db is not None:
        return await _query(db)
    async with AsyncSessionLocal() as session:
        return await _query(session)
