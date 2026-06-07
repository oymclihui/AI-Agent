"""
ModelRouter - central router for all LLM providers.
Inspired by Dify's model management: supports OpenAI, Anthropic, Ollama, Azure.
"""
from typing import Optional
import structlog
from langchain_core.language_models import BaseChatModel

from app.config import settings

logger = structlog.get_logger(__name__)


class ModelRouter:
    _cache: dict[str, BaseChatModel] = {}

    @classmethod
    async def get_llm(
        cls,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        streaming: bool = False,
    ) -> BaseChatModel:
        provider = provider or settings.DEFAULT_LLM_PROVIDER
        model = model or settings.DEFAULT_LLM_MODEL
        cache_key = f"{provider}:{model}:{temperature}:{streaming}"

        if cache_key in cls._cache:
            return cls._cache[cache_key]

        llm = cls._create_llm(provider, model, temperature, streaming)
        cls._cache[cache_key] = llm
        logger.info("llm_created", provider=provider, model=model)
        return llm

    @classmethod
    def _create_llm(
        cls,
        provider: str,
        model: str,
        temperature: float,
        streaming: bool,
    ) -> BaseChatModel:
        if provider == "openai":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model,
                temperature=temperature,
                streaming=streaming,
                openai_api_key=settings.OPENAI_API_KEY,
            )

        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=model,
                temperature=temperature,
                streaming=streaming,
                anthropic_api_key=settings.ANTHROPIC_API_KEY,
            )

        elif provider == "ollama":
            from langchain_ollama import ChatOllama
            return ChatOllama(
                model=model,
                temperature=temperature,
                streaming=streaming,
                base_url=settings.OLLAMA_BASE_URL,
            )

        elif provider == "azure":
            from langchain_openai import AzureChatOpenAI
            return AzureChatOpenAI(
                azure_deployment=model,
                temperature=temperature,
                streaming=streaming,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=settings.AZURE_OPENAI_API_KEY,
                api_version=settings.AZURE_OPENAI_API_VERSION,
            )

        else:
            logger.warning("unknown_provider_fallback_openai", provider=provider)
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model="gpt-4o-mini",
                temperature=temperature,
                openai_api_key=settings.OPENAI_API_KEY,
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

        # Always include Ollama as an option
        models.append({
            "provider": "ollama",
            "model": "llama3.2",
            "context_window": 131072,
            "note": "Requires local Ollama server",
        })

        return models
