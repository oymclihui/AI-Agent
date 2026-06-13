"""BYD EIS internal LLM gateway — OpenAI-compatible model catalog."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import settings


@dataclass(frozen=True)
class BydModelSpec:
    name: str
    model_id: str
    api_model: str
    base_url: str
    api_key: str
    context_window: int = 65536
    is_default: bool = False
    description: str = ""


def _byd_specs() -> list[BydModelSpec]:
    specs: list[BydModelSpec] = []

    def add(
        env_key: str,
        *,
        name: str,
        model_id: str,
        api_model: str,
        base_url: str,
        is_default: bool = False,
        context_window: int = 65536,
        description: str = "",
    ) -> None:
        key = getattr(settings, env_key, None)
        if not key:
            return
        specs.append(
            BydModelSpec(
                name=name,
                model_id=model_id,
                api_model=api_model,
                base_url=base_url.rstrip("/"),
                api_key=key.strip(),
                context_window=context_window,
                is_default=is_default,
                description=description,
            )
        )

    add(
        "BYD_DEEPSEEK_V4_FLASH_API_KEY",
        name="BYD DeepSeek-V4-Flash",
        model_id="byd-deepseek-v4-flash",
        api_model="deepseek-chat",
        base_url=settings.BYD_DEEPSEEK_V4_FLASH_BASE_URL,
        is_default=False,
        description="DeepSeek V4 Flash via BYD EIS (deepseek-chat)",
    )
    add(
        "BYD_QWEN35_35B_API_KEY",
        name="BYD Qwen3.5-35B-A3B-FP8",
        model_id="byd-qwen35-35b-a3b-fp8",
        api_model="qwen3.5-35b-a3b-fp8",
        base_url=settings.BYD_QWEN35_35B_BASE_URL,
        context_window=32768,
        description="Qwen3.5 35B A3B FP8 via BYD EIS",
    )
    add(
        "BYD_DEEPSEEK_REASONER_API_KEY",
        name="BYD DeepSeek-Reasoner",
        model_id="byd-deepseek-reasoner",
        api_model="deepseek-reasoner",
        base_url=settings.BYD_DEEPSEEK_REASONER_BASE_URL,
        description="DeepSeek reasoning model via BYD EIS",
    )
    add(
        "BYD_DEEPSEEK_32B_API_KEY",
        name="BYD DeepSeek-32B",
        model_id="byd-deepseek-32b",
        api_model="deepseek-chat",
        base_url=settings.BYD_DEEPSEEK_32B_BASE_URL,
        description="DeepSeek 32B stream endpoint via BYD EIS",
    )
    return specs


def byd_catalog_entries() -> dict[tuple[str, str], dict]:
    """Map (provider, model_id) -> ModelConfig kwargs for seeding."""
    default_inference = {"temperature": 0.7, "top_p": 0.9, "max_tokens": 4096}
    entries: dict[tuple[str, str], dict] = {}
    for spec in _byd_specs():
        entries[("openai", spec.model_id)] = dict(
            name=spec.name,
            provider="openai",
            model_id=spec.model_id,
            base_url=spec.base_url,
            api_key_encrypted=spec.api_key,
            is_default=spec.is_default,
            is_active=True,
            context_window=spec.context_window,
            config={
                "api_model": spec.api_model,
                "vendor": "byd-eis",
                "label": spec.description or spec.name,
                "inference": default_inference,
            },
        )
    return entries


def has_byd_models() -> bool:
    return bool(_byd_specs())
