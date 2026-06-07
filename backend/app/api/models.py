from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import ModelConfig
from app.models_hub.router import ModelRouter

router = APIRouter(prefix="/models", tags=["Model Hub"])


@router.get("/available")
async def list_available_models():
    """Lists all configured LLM providers and their models."""
    return await ModelRouter.list_available_models()


@router.get("/configs")
async def list_model_configs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ModelConfig).where(ModelConfig.is_active == True))
    configs = result.scalars().all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "provider": c.provider,
            "model_id": c.model_id,
            "is_default": c.is_default,
            "context_window": c.context_window,
            "cost_per_1k_input": c.cost_per_1k_input,
            "cost_per_1k_output": c.cost_per_1k_output,
        }
        for c in configs
    ]
