"""Resolve LLM from conversation SessionContext (model_config_id + user keys)."""
from __future__ import annotations

from typing import Any, Optional

from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, ModelConfig
from app.models_hub.router import ModelRouter


async def get_llm_for_conversation(
    db: AsyncSession,
    conv: Conversation,
    user_id: str,
    *,
    temperature: float | None = None,
    response_style: str | None = None,
    streaming: bool = False,
) -> BaseChatModel:
    meta = conv.metadata_ or {}
    style = response_style or meta.get("response_style")
    personal_provider = meta.get("personal_provider")
    personal_model = meta.get("personal_model_id")
    if personal_provider and personal_model:
        return await ModelRouter.get_llm(
            provider=str(personal_provider),
            model=str(personal_model),
            db=db,
            user_id=user_id,
            temperature=temperature,
            response_style=style,
            streaming=streaming,
        )
    model_config_id = meta.get("model_config_id")
    if model_config_id:
        cfg = await db.get(ModelConfig, str(model_config_id))
        if cfg and cfg.is_active:
            inference = dict((cfg.config or {}).get("inference") or {})
            if temperature is not None:
                inference["temperature"] = temperature
            return await ModelRouter.get_llm(
                provider=cfg.provider,
                model=cfg.model_id,
                db=db,
                user_id=user_id,
                temperature=temperature,
                response_style=style,
                streaming=streaming,
                base_url=cfg.base_url,
                inference_params=inference or None,
            )
    return await ModelRouter.get_llm(
        db=db,
        user_id=user_id,
        temperature=temperature,
        response_style=style,
        streaming=streaming,
    )


async def model_label_for_conversation(
    db: AsyncSession,
    conv: Conversation,
) -> dict[str, Any]:
    meta = conv.metadata_ or {}
    if meta.get("personal_provider") and meta.get("personal_model_id"):
        return {
            "id": None,
            "name": f"我的 {meta.get('personal_provider')}/{meta.get('personal_model_id')}",
            "provider": meta.get("personal_provider"),
            "model_id": meta.get("personal_model_id"),
        }
    model_config_id = meta.get("model_config_id")
    if model_config_id:
        cfg = await db.get(ModelConfig, str(model_config_id))
        if cfg:
            return {"id": cfg.id, "name": cfg.name, "provider": cfg.provider, "model_id": cfg.model_id}
    from app.config import settings

    return {
        "id": None,
        "name": f"{settings.DEFAULT_LLM_PROVIDER}/{settings.DEFAULT_LLM_MODEL}",
        "provider": settings.DEFAULT_LLM_PROVIDER,
        "model_id": settings.DEFAULT_LLM_MODEL,
    }
