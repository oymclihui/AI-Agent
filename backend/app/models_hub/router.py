"""
ModelRouter - central router for all LLM providers.
Inspired by Dify's model management: supports OpenAI, Anthropic, Ollama, Azure.
"""
from typing import Any, Optional
import structlog
from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models_hub.inference import (
    build_anthropic_kwargs,
    build_ollama_kwargs,
    build_openai_kwargs,
    merge_inference,
)
from app.models_hub.resolver import resolve_model_config
from app.models_hub.user_credentials import resolve_user_credentials
from app.schemas.model_inference import ModelInferenceParams

logger = structlog.get_logger(__name__)


class ModelRouter:
    _cache: dict[str, BaseChatModel] = {}

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()

    @classmethod
    async def get_llm(
        cls,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        streaming: bool = False,
        base_url: Optional[str] = None,
        inference_params: Optional[dict[str, Any]] = None,
        db: Optional[AsyncSession] = None,
        user_id: Optional[str] = None,
        use_db_config: bool = True,
    ) -> BaseChatModel:
        provider = provider or settings.DEFAULT_LLM_PROVIDER
        model = model or settings.DEFAULT_LLM_MODEL

        resolved_base_url = base_url
        resolved_api_key: Optional[str] = None
        api_model = model
        stored = ModelInferenceParams()
        cfg = None
        if use_db_config:
            cfg, stored = await resolve_model_config(provider, model, db)
            if cfg:
                if not base_url and cfg.base_url:
                    resolved_base_url = cfg.base_url
                if cfg.api_key_encrypted:
                    resolved_api_key = cfg.api_key_encrypted
                api_model = (cfg.config or {}).get("api_model") or cfg.model_id

        user_key, user_base_url = await resolve_user_credentials(user_id, provider, model, db)
        if user_key:
            resolved_api_key = user_key
        if user_base_url and not base_url:
            resolved_base_url = user_base_url

        merged = merge_inference(stored, inference_params, temperature_override=temperature)
        if "temperature" not in merged:
            merged["temperature"] = temperature if temperature is not None else 0.7

        cache_key = f"{provider}:{api_model}:{resolved_base_url}:{resolved_api_key}:{user_id}:{streaming}:{sorted(merged.items())}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        llm = cls._create_llm(
            provider, api_model, merged, streaming, resolved_base_url, resolved_api_key,
        )
        cls._cache[cache_key] = llm
        logger.info("llm_created", provider=provider, model=model, params=merged)
        return llm

    @classmethod
    def _create_llm(
        cls,
        provider: str,
        model: str,
        params: dict[str, Any],
        streaming: bool,
        base_url: Optional[str],
        api_key: Optional[str] = None,
    ) -> BaseChatModel:
        if provider == "openai":
            from langchain_openai import ChatOpenAI
            kwargs = build_openai_kwargs(params, streaming)
            if base_url:
                kwargs["base_url"] = base_url
            return ChatOpenAI(
                model=model,
                openai_api_key=api_key or settings.OPENAI_API_KEY,
                **kwargs,
            )

        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            kwargs = build_anthropic_kwargs(params, streaming)
            return ChatAnthropic(
                model=model,
                anthropic_api_key=api_key or settings.ANTHROPIC_API_KEY,
                **kwargs,
            )

        if provider == "ollama":
            from langchain_ollama import ChatOllama
            kwargs = build_ollama_kwargs(params, streaming)
            return ChatOllama(
                model=model,
                base_url=base_url or settings.OLLAMA_BASE_URL,
                **kwargs,
            )

        if provider == "azure":
            from langchain_openai import AzureChatOpenAI
            kwargs = build_openai_kwargs(params, streaming)
            return AzureChatOpenAI(
                azure_deployment=model,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=api_key or settings.AZURE_OPENAI_API_KEY,
                api_version=settings.AZURE_OPENAI_API_VERSION,
                **kwargs,
            )

        logger.warning("unknown_provider_fallback_openai", provider=provider)
        from langchain_openai import ChatOpenAI
        kwargs = build_openai_kwargs(params, streaming)
        return ChatOpenAI(
            model="gpt-4o-mini",
            openai_api_key=api_key or settings.OPENAI_API_KEY,
            **kwargs,
        )

    @classmethod
    async def list_available_models(cls) -> list[dict]:
        """Returns all configured and available models."""
        models = []

        if settings.OPENAI_API_KEY:
            models.extend([
                {"provider": "openai", "model": "gpt-4o", "context_window": 128000},
                {"provider": "openai", "model": "gpt-4o-mini", "context_window": 128000},
                {"provider": "openai", "model": "gpt-4-turbo", "context_window": 128000},
            ])

        if settings.ANTHROPIC_API_KEY:
            models.extend([
                {"provider": "anthropic", "model": "claude-3-5-sonnet-20241022", "context_window": 200000},
                {"provider": "anthropic", "model": "claude-3-haiku-20240307", "context_window": 200000},
            ])

        models.append({
            "provider": "ollama",
            "model": "llama3.2",
            "context_window": 131072,
            "note": "Requires local Ollama server",
        })

        return models
