"""LLM endpoint reachability checks and user-facing error messages."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Agent as AgentModel
from app.models_hub.resolver import resolve_model_config

logger = structlog.get_logger(__name__)


async def _resolve_base_url(
    provider: str,
    model: str,
    db: AsyncSession | None,
) -> str:
    cfg, _ = await resolve_model_config(provider, model, db)
    if cfg and cfg.base_url:
        return cfg.base_url.rstrip("/")

    if provider == "ollama":
        return settings.OLLAMA_BASE_URL.rstrip("/")
    if provider == "openai" and model and "byd" in model.lower():
        if "qwen" in model.lower():
            return settings.BYD_QWEN35_35B_BASE_URL.rstrip("/")
        if "reasoner" in model.lower():
            return settings.BYD_DEEPSEEK_REASONER_BASE_URL.rstrip("/")
        return settings.BYD_DEEPSEEK_V4_FLASH_BASE_URL.rstrip("/")
    return ""


async def check_llm_reachable(
    provider: str | None,
    model: str | None,
    db: AsyncSession | None = None,
) -> tuple[bool, str]:
    """Return (ok, detail) before running an agent task."""
    provider = (provider or settings.DEFAULT_LLM_PROVIDER or "ollama").lower()
    model = model or settings.DEFAULT_LLM_MODEL or ""

    if provider == "ollama":
        base = await _resolve_base_url(provider, model, db)
        url = f"{base}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return True, base
                return False, f"Ollama 返回 HTTP {resp.status_code}（{base}）"
        except Exception as exc:
            return False, f"无法连接 Ollama（{base}）: {exc}"

    if provider == "openai":
        base = await _resolve_base_url(provider, model, db)
        if not base:
            return True, "openai"
        host = urlparse(base).hostname or base
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                await client.get(f"{base.rsplit('/', 1)[0]}/", follow_redirects=True)
            return True, base
        except httpx.ConnectError as exc:
            return False, f"无法连接 LLM 网关（{host}）: {exc}"
        except Exception as exc:
            # DNS / TLS errors still mean unreachable for our purposes
            err = str(exc).lower()
            if "getaddrinfo" in err or "connect" in err or "name or service not known" in err:
                return False, f"无法连接 LLM 网关（{host}）: {exc}"
            return True, base

    return True, provider


def format_llm_task_error(exc: Exception, agent: AgentModel) -> str:
    raw = str(exc).strip() or repr(exc)
    provider = (agent.llm_provider or settings.DEFAULT_LLM_PROVIDER or "").lower()
    model = agent.llm_model or settings.DEFAULT_LLM_MODEL or ""
    lower = raw.lower()

    is_connection = (
        "connection error" in lower
        or "connecterror" in lower
        or "getaddrinfo" in lower
        or "connection refused" in lower
        or "name or service not known" in lower
    )
    if not is_connection:
        return raw[:4000]

    if provider == "openai" and ("byd" in model.lower() or "eisapi.byd.com" in lower):
        return (
            f"无法连接 BYD 内网 LLM（{model}）。请连接公司 VPN 后重试，"
            f"或在「智能体」页将该角色模型改为本地 Ollama（如 ollama / qwen3.6:35b，"
            f"地址 {settings.OLLAMA_BASE_URL}）。详情: {raw}"
        )[:4000]

    if provider == "ollama":
        return (
            f"无法连接 Ollama（{settings.OLLAMA_BASE_URL}）。"
            f"请确认 Ollama 已启动，且 backend/.env 中 OLLAMA_BASE_URL 正确。详情: {raw}"
        )[:4000]

    return f"LLM 连接失败（{provider}/{model}）: {raw}"[:4000]
