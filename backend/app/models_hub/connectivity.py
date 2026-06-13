"""LLM endpoint reachability checks and user-facing error messages."""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog
from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Agent as AgentModel
from app.models_hub.resolver import resolve_model_config
from app.models_hub.router import ModelRouter

logger = structlog.get_logger(__name__)

# Probe order for auto-default: BYD API → OpenAI → local Ollama → other actives
DEFAULT_PROBE_PRIORITY: list[tuple[str, str]] = [
    ("openai", "byd-deepseek-v4-flash"),
    ("openai", "byd-qwen35-35b-a3b-fp8"),
    ("openai", "byd-deepseek-reasoner"),
    ("openai", "byd-deepseek-32b"),
    ("openai", "gpt-4o-mini"),
    ("openai", "gpt-4o"),
    ("ollama", "qwen3.6:35b"),
    ("ollama", "deepseek-v4-flash:cloud"),
    ("ollama", "qwen3.5:cloud"),
    ("ollama", "gemma4:31b"),
    ("ollama", "kimi-k2.6:cloud"),
    ("ollama", "deepseek-v4-pro:cloud"),
]


def _format_test_error(exc: Exception, *, provider: str, model_id: str, endpoint: str | None) -> str:
    raw = str(exc).strip() or repr(exc)
    lower = raw.lower()
    if "not found" in lower or "404" in lower:
        hint = (
            f"请检查 Model ID「{model_id}」与 Base URL 是否正确"
            + (f"（{endpoint}）" if endpoint else "")
        )
        return f"接口或模型不存在（404）。{hint}。详情: {raw[:280]}"
    if "401" in lower or "unauthorized" in lower or "authentication" in lower:
        return f"鉴权失败，请检查 API Key 或在「设置」中配置个人 Key。详情: {raw[:280]}"
    if provider == "ollama":
        return f"Ollama 调用失败: {raw[:400]}"
    return raw[:500]


async def _resolve_base_url(
    provider: str,
    model: str,
    db: AsyncSession | None,
    base_url: str | None = None,
) -> str:
    if base_url:
        return base_url.rstrip("/")
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
    base_url: str | None = None,
) -> tuple[bool, str]:
    """Return (ok, detail) before running an agent task."""
    provider = (provider or settings.DEFAULT_LLM_PROVIDER or "ollama").lower()
    model = model or settings.DEFAULT_LLM_MODEL or ""

    if provider == "ollama":
        base = await _resolve_base_url(provider, model, db, base_url)
        url = f"{base}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return True, base
                return False, f"Ollama 返回 HTTP {resp.status_code}（{base}）"
        except Exception as exc:
            return False, f"无法连接 Ollama（{base}）: {exc}"

    if provider in ("openai", "azure"):
        base = await _resolve_base_url(provider, model, db, base_url)
        if not base:
            return True, provider
        host = urlparse(base).hostname or base
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                await client.get(f"{base.rsplit('/', 1)[0]}/", follow_redirects=True)
            return True, base
        except httpx.ConnectError as exc:
            return False, f"无法连接 LLM 网关（{host}）: {exc}"
        except Exception as exc:
            err = str(exc).lower()
            if "getaddrinfo" in err or "connect" in err or "name or service not known" in err:
                return False, f"无法连接 LLM 网关（{host}）: {exc}"
            return True, base

    if provider == "anthropic":
        return True, "https://api.anthropic.com"

    return True, provider


async def test_model_connection(
    *,
    provider: str,
    model_id: str,
    base_url: str | None = None,
    db: AsyncSession | None = None,
    user_id: str | None = None,
    startup_probe: bool = False,
) -> dict[str, Any]:
    """Ping model endpoint with a minimal generation request."""
    started = time.perf_counter()
    provider = (provider or "").strip().lower()
    model_id = (model_id or "").strip()
    if not provider or not model_id:
        return {
            "ok": False,
            "message": "请填写提供商与模型 ID",
            "latency_ms": 0,
            "endpoint": None,
            "preview": None,
        }

    ok, endpoint = await check_llm_reachable(provider, model_id, db, base_url=base_url)
    if not ok:
        return {
            "ok": False,
            "message": endpoint,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "endpoint": endpoint,
            "preview": None,
        }

    if provider == "ollama":
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"{endpoint}/api/tags")
                if resp.status_code == 200:
                    names = {
                        (m.get("name") or "").split(":")[0]
                        for m in resp.json().get("models", [])
                        if isinstance(m, dict)
                    }
                    target = model_id.split(":")[0]
                    if names and target not in names and model_id not in names:
                        return {
                            "ok": False,
                            "message": f"Ollama 已连通，但未找到模型「{model_id}」。请先执行 ollama pull {model_id}",
                            "latency_ms": int((time.perf_counter() - started) * 1000),
                            "endpoint": endpoint,
                            "preview": None,
                        }
                    if startup_probe:
                        return {
                            "ok": True,
                            "message": "连接成功",
                            "latency_ms": int((time.perf_counter() - started) * 1000),
                            "endpoint": endpoint,
                            "preview": None,
                        }
        except Exception:
            pass

    invoke_timeout = 10 if startup_probe else 20
    max_tokens = 3 if startup_probe else 8
    try:
        llm = await ModelRouter.get_llm(
            provider=provider,
            model=model_id,
            base_url=base_url,
            streaming=False,
            db=db,
            user_id=user_id,
            inference_params={"max_tokens": max_tokens, "timeout": invoke_timeout},
            use_db_config=db is not None,
        )
        resp = await llm.ainvoke([HumanMessage(content="ping")])
        preview = (resp.content or "").strip()[:200] or None
        return {
            "ok": True,
            "message": "连接成功",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "endpoint": endpoint,
            "preview": preview,
        }
    except Exception as exc:
        logger.warning("model_connection_test_failed", provider=provider, model=model_id, error=str(exc))
        return {
            "ok": False,
            "message": _format_test_error(exc, provider=provider, model_id=model_id, endpoint=endpoint),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "endpoint": endpoint,
            "preview": None,
        }


def _ordered_active_configs(active: list) -> list:
    """Return active ModelConfig rows in default-probe priority order."""
    by_key = {(c.provider, c.model_id): c for c in active}
    ordered: list = []
    seen: set[tuple[str, str]] = set()
    for key in DEFAULT_PROBE_PRIORITY:
        cfg = by_key.get(key)
        if cfg and key not in seen:
            ordered.append(cfg)
            seen.add(key)
    for cfg in sorted(active, key=lambda c: (c.provider, c.name or c.model_id)):
        key = (cfg.provider, cfg.model_id)
        if key not in seen:
            ordered.append(cfg)
            seen.add(key)
    return ordered


async def apply_connectivity_default(session: AsyncSession) -> None:
    """Pick the first reachable active model as default (startup / re-probe)."""
    from sqlalchemy import select

    from app.db.models import ModelConfig

    if not settings.AUTO_PICK_DEFAULT_MODEL:
        return

    result = await session.execute(select(ModelConfig).where(ModelConfig.is_active == True))
    active = list(result.scalars().all())
    if not active:
        return

    defaults = [c for c in active if c.is_default]
    if len(defaults) == 1:
        probe = await test_model_connection(
            provider=defaults[0].provider,
            model_id=defaults[0].model_id,
            db=session,
            startup_probe=True,
        )
        if probe["ok"]:
            logger.info(
                "default_model_kept",
                provider=defaults[0].provider,
                model=defaults[0].model_id,
            )
            return

    for cfg in _ordered_active_configs(active):
        probe = await test_model_connection(
            provider=cfg.provider,
            model_id=cfg.model_id,
            db=session,
            startup_probe=True,
        )
        if not probe["ok"]:
            logger.debug(
                "default_model_probe_skip",
                provider=cfg.provider,
                model=cfg.model_id,
                reason=probe.get("message"),
            )
            continue
        for c in active:
            c.is_default = c.id == cfg.id
        logger.info(
            "default_model_auto_selected",
            provider=cfg.provider,
            model=cfg.model_id,
            latency_ms=probe.get("latency_ms"),
        )
        return

    logger.warning("default_model_none_reachable", active_count=len(active))
    if not any(c.is_default for c in active):
        ordered = _ordered_active_configs(active)
        if ordered:
            ordered[0].is_default = True


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
