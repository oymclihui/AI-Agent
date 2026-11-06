"""企微问数运行时参数：用 contextvars 注入，避免穿透多层函数签名。

调用方（企微 inbound）在 run_data_ask 之前 set，下游（nl2sql / cache）读取。
未设置时全部走原有默认值，不影响平台站内对话行为。
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_preview_rows: ContextVar[int | None] = ContextVar("ask_preview_rows", default=None)
_temperature: ContextVar[float | None] = ContextVar("ask_temperature", default=None)
_cache_ttl: ContextVar[int | None] = ContextVar("ask_cache_ttl", default=None)
_progress: ContextVar[Any] = ContextVar("ask_progress", default=None)


def set_progress(callback: Any) -> Any:
    """注册过程回调（async def cb(text: str)），返回 reset token；不注册则完全不推送。"""
    return _progress.set(callback)


def reset_progress(token: Any) -> None:
    _progress.reset(token)


def current_progress() -> Any:
    return _progress.get()


def apply_runtime(preview_rows: int | None = None, temperature: float | None = None,
                  cache_ttl: int | None = None) -> None:
    """设置当前上下文的问数参数。temperature < 0 表示不干预，交回模型默认。"""
    if isinstance(preview_rows, int) and preview_rows > 0:
        _preview_rows.set(preview_rows)
    if isinstance(temperature, (int, float)) and temperature >= 0:
        _temperature.set(float(temperature))
    if isinstance(cache_ttl, int) and cache_ttl >= 0:
        _cache_ttl.set(cache_ttl)


def current_preview_rows(default: int = 200) -> int:
    value = _preview_rows.get()
    return value if isinstance(value, int) and value > 0 else default


def current_temperature(default: float | None = None) -> float | None:
    value = _temperature.get()
    return value if isinstance(value, (int, float)) else default


def current_cache_ttl(default: int = 300) -> int:
    value = _cache_ttl.get()
    return value if isinstance(value, int) and value >= 0 else default
