# -*- coding: utf-8 -*-
"""
Redis 缓存与限流工具（专用 DB1）
- 应用缓存：问数结果短期缓存（dataask:cache:*）
- 限流计数：固定窗口 INCR+EXPIRE（ratelimit:*）
设计原则：Redis 不可用时全部自动降级（缓存视为未命中 / 限流放行），绝不阻塞主业务；
失败后 30 秒熔断，期间不再尝试连接，避免每个请求都等待超时。
"""
import os
import json
import time
import hashlib
import logging

logger = logging.getLogger(__name__)


def _resolve_url() -> str:
    """REDIS_CACHE_URL 环境变量 → settings.REDIS_CACHE_URL → 从 REDIS_URL 推导 DB1 → 默认值"""
    url = (os.getenv("REDIS_CACHE_URL") or "").strip()
    if url:
        return url
    try:
        from app.config import settings
        url = (getattr(settings, "REDIS_CACHE_URL", "") or "").strip()
        if url:
            return url
        base = (settings.REDIS_URL or "").strip()
        if base:
            return base.rsplit("/", 1)[0] + "/1"
    except Exception:
        pass
    return "redis://:Redis%40123456@172.16.120.119:6379/1"


_CACHE_URL = _resolve_url()
DATAASK_CACHE_TTL = int(os.getenv("DATAASK_CACHE_TTL", "300"))
DATAASK_RATELIMIT_PER_MIN = int(os.getenv("DATAASK_RATELIMIT_PER_MIN", "10"))
API_RATELIMIT_PER_MIN = int(os.getenv("API_RATELIMIT_PER_MIN", "120"))

_client = None
_client_loop = None  # 持有创建该客户端的事件循环对象（身份比较，避免跨 loop 复用）
_failed_until = 0.0
_FAIL_BACKOFF = 30.0


def _mark_failed():
    global _failed_until
    _failed_until = time.time() + _FAIL_BACKOFF


async def _get_client():
    """懒加载 redis.asyncio 客户端；初始化失败或熔断期内返回 None"""
    global _client, _client_loop, _failed_until
    if time.time() < _failed_until:
        return None
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    # 事件循环已切换（Celery 每次 asyncio.run 新建 loop）时丢弃旧连接，避免 Event loop is closed
    if _client is not None and _client_loop is not loop:
        _client = None
    if _client is None:
        try:
            import redis.asyncio as aioredis
            _client = aioredis.from_url(
                _CACHE_URL,
                socket_timeout=2,
                socket_connect_timeout=2,
                decode_responses=True,
                health_check_interval=30,
            )
            _client_loop = loop
            logger.info("redis_cache_connected url=%s", _CACHE_URL.rsplit("@", 1)[-1])
        except Exception as exc:
            logger.warning("redis_cache_init_failed: %s", exc)
            _mark_failed()
            return None
    return _client


# ── 通用缓存 ──

async def cache_get_json(key: str):
    """读取 JSON 缓存；未命中或 Redis 不可用返回 None"""
    cli = await _get_client()
    if cli is None:
        return None
    try:
        raw = await cli.get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.warning("cache_get_failed: %s", exc)
        _mark_failed()
        return None


async def cache_set_json(key: str, value, ttl: int = None) -> bool:
    """写入 JSON 缓存（default=str 兜底 datetime/Decimal 等类型）；失败静默"""
    cli = await _get_client()
    if cli is None:
        return False
    try:
        await cli.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=int(ttl or DATAASK_CACHE_TTL))
        return True
    except Exception as exc:
        logger.warning("cache_set_failed: %s", exc)
        _mark_failed()
        return False


# ── 限流（固定窗口） ──

async def rate_limit_check(key: str, limit: int = None, window: int = 60):
    """固定窗口限流。返回 (allowed, count)；Redis 不可用 → (True, 0) 放行"""
    limit = int(limit or API_RATELIMIT_PER_MIN)
    cli = await _get_client()
    if cli is None:
        return True, 0
    try:
        bucket = f"{key}:{int(time.time() // window)}"
        cnt = await cli.incr(bucket)
        await cli.expire(bucket, window)
        return (cnt <= limit), cnt
    except Exception as exc:
        logger.warning("rate_limit_failed: %s", exc)
        _mark_failed()
        return True, 0


# ── 问数缓存 key ──

def make_dataask_cache_key(*, data_source_id, question, sql_override=None,
                           llm_provider=None, llm_model=None, execute=None, history=None) -> str:
    raw = json.dumps({
        "ds": str(data_source_id),
        "q": question,
        "sql": sql_override or "",
        "prov": llm_provider or "",
        "model": llm_model or "",
        "exec": bool(execute),
        "hist": history or [],
    }, ensure_ascii=False, sort_keys=True, default=str)
    return "dataask:cache:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
