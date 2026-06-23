"""Response style presets: precise / balanced / creative."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class ResponseStyle(str, Enum):
    precise = "precise"
    balanced = "balanced"
    creative = "creative"


STYLE_PRESETS: dict[ResponseStyle, dict[str, float | int]] = {
    ResponseStyle.precise: {
        "temperature": 0.15,
        "top_p": 0.85,
        "top_k": 40,
    },
    ResponseStyle.balanced: {
        "temperature": 0.65,
        "top_p": 0.90,
        "top_k": 80,
    },
    ResponseStyle.creative: {
        "temperature": 0.90,
        "top_p": 0.95,
        "top_k": 100,
    },
}

DEFAULT_STYLE = ResponseStyle.balanced


def preset_for_style(style: ResponseStyle | str | None) -> dict[str, Any]:
    if style is None:
        style = DEFAULT_STYLE
    if isinstance(style, str):
        try:
            style = ResponseStyle(style)
        except ValueError:
            style = DEFAULT_STYLE
    return dict(STYLE_PRESETS.get(style, STYLE_PRESETS[DEFAULT_STYLE]))


def temperature_to_style(temperature: float | None) -> ResponseStyle:
    if temperature is None:
        return DEFAULT_STYLE
    if temperature <= 0.35:
        return ResponseStyle.precise
    if temperature <= 0.75:
        return ResponseStyle.balanced
    return ResponseStyle.creative


def resolve_conversation_style(
    meta: dict[str, Any] | None,
    *,
    agent_temperature: float | None = None,
    task_lock: ResponseStyle | None = None,
) -> ResponseStyle:
    if task_lock is not None:
        return task_lock
    meta = meta or {}
    chat_mode = str(meta.get("chat_mode") or "single")
    if chat_mode == "data_ask":
        return ResponseStyle.precise
    raw = meta.get("response_style")
    if raw in {s.value for s in ResponseStyle}:
        return ResponseStyle(str(raw))
    if agent_temperature is not None:
        return temperature_to_style(agent_temperature)
    return DEFAULT_STYLE


def style_is_locked(meta: dict[str, Any] | None) -> bool:
    meta = meta or {}
    return str(meta.get("chat_mode") or "single") == "data_ask"
