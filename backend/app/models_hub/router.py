"""
ModelRouter - central router for all LLM providers.
Inspired by Dify's model management: supports OpenAI, Anthropic, Ollama, Azure.
"""
import asyncio
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
from app.models_hub.response_style import ResponseStyle, preset_for_style, DEFAULT_STYLE
from app.models_hub.user_credentials import open_secret, resolve_user_credentials, resolve_user_default
from app.schemas.model_inference import ModelInferenceParams

logger = structlog.get_logger(__name__)


class ModelRouter:
    _cache: dict[str, BaseChatModel] = {}
    # 缓存条目绑定创建时的 asyncio 事件循环：Celery 任务每次 asyncio.run() 新建 loop，
    # 复用旧 loop 上的 ChatOpenAI/httpx 异步客户端会抛 Event loop is closed。
    _cache_loop = None  # 持有缓存所属事件循环对象（身份比较，避免 id 回收复用）

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()
        cls._cache_loop = None

    @classmethod
    async def get_llm(
        cls,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        response_style: Optional[str] = None,
        streaming: bool = False,
        base_url: Optional[str] = None,
        inference_params: Optional[dict[str, Any]] = None,
        db: Optional[AsyncSession] = None,
        user_id: Optional[str] = None,
        use_db_config: bool = True,
    ) -> BaseChatModel:
        # 事件循环变更即清缓存，避免跨 loop 复用异步客户端
        try:
            _loop = asyncio.get_running_loop()
        except RuntimeError:
            _loop = None
        if cls._cache_loop is not _loop:
            cls._cache.clear()
            cls._cache_loop = _loop

        explicit_choice = provider is not None or model is not None
        if not explicit_choice:
            default_row = await resolve_user_default(user_id, db)
            if default_row and default_row.model_id:
                provider = default_row.provider
                model = default_row.model_id
        provider = provider or settings.DEFAULT_LLM_PROVIDER
        model = model or settings.DEFAULT_LLM_MODEL

        resolved_base_url = base_url
        resolved_api_key: Optional[str] = None
        api_model = model
        stored = ModelInferenceParams()
        cfg = None
        if use_db_config:
            cfg, stored = await resolve_model_config(provider, model, db)
            matched = bool(
                cfg
                and cfg.provider == str(provider).lower()
                and cfg.model_id == model
            )
            if matched:
                if not base_url and cfg.base_url:
                    resolved_base_url = cfg.base_url
                if cfg.api_key_encrypted:
                    resolved_api_key = open_secret(cfg.api_key_encrypted) or None
                api_model = (cfg.config or {}).get("api_model") or cfg.model_id

        user_key, user_base_url = await resolve_user_credentials(user_id, provider, model, db)
        if user_key:
            resolved_api_key = user_key
        if user_base_url and not base_url:
            resolved_base_url = user_base_url

        merged = merge_inference(stored, inference_params, temperature_override=temperature)
        if response_style:
            try:
                style = ResponseStyle(response_style)
            except ValueError:
                style = DEFAULT_STYLE
            merged.update(preset_for_style(style))
        elif temperature is not None:
            merged["temperature"] = temperature
        elif "temperature" not in merged:
            merged.update(preset_for_style(DEFAULT_STYLE))

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
        if provider in ("openai", "deepseek", "qwen", "glm"):
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
            if api_key:
                token = api_key.removeprefix("Bearer ").strip()
                kwargs["client_kwargs"] = {
                    "headers": {"Authorization": f"Bearer {token}"},
                }
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
