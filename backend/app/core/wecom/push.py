"""Push a finished digital-employee report to WeCom over the bot long connection."""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any

import structlog
import websockets
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.credentials import decrypt_secret, encrypt_secret
from app.db.models import SystemSetting

logger = structlog.get_logger(__name__)

WECOM_SETTING_KEY = "wecom_bot"
WS_URL = "wss://openws.work.weixin.qq.com"
# 流式消息官方上限是 20480 字节。按 5000 字发送，汉字约 15000 字节，落在上限内。
WECOM_MAX_CHARS = 5000
WECOM_MAX_BYTES = 20480
_MAX_BYTES = WECOM_MAX_BYTES
_CLIP_TAIL = "\n\n……（内容过长，完整结果请在平台对话中查看）"

_THEMES = ("blue", "green", "purple", "orange", "dark")
_SIZES = ("small", "medium", "large")
_CHART_TYPES = ("auto", "bar", "barh", "line", "area", "pie")
_DEFAULT_TEMPLATE = "{结论}\n\n{分析}\n{建议}\n{行数}"


def _int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(number, high))


def _num(value: Any, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(number, high))


_RATE_PATTERN = re.compile(r"^[-+]?\d+%$")


def _voice_rate(value: Any) -> str:
    r"""edge-tts 语速/音量格式：[-+]?\d+%（如 -20%、+0%）。"""
    text = str(value or "").strip()
    if _RATE_PATTERN.fullmatch(text):
        return text
    return "+0%"


_PITCH_PATTERN = re.compile(r"^[-+]?\d+Hz$")


def _voice_pitch(value: Any) -> str:
    r"""edge-tts 音调格式：[-+]?\d+Hz（如 -5Hz、+0Hz）。"""
    text = str(value or "").strip()
    if _PITCH_PATTERN.fullmatch(text):
        return text
    return "+0Hz"


def normalize_style(value: Any) -> dict[str, Any]:
    """表格/图表/文本显示样式，非法值回落到默认。"""
    data = value if isinstance(value, dict) else {}
    theme = str(data.get("theme") or "blue")
    size = str(data.get("font_size") or "medium")
    ctype = str(data.get("chart_type") or "auto").lower()
    return {
        # 表格外观
        "theme": theme if theme in _THEMES else "blue",
        "font_size": size if size in _SIZES else "medium",
        "zebra": bool(data.get("zebra", True)),
        "show_title": bool(data.get("show_title", True)),
        "show_table": bool(data.get("show_table", True)),
        "show_chart": bool(data.get("show_chart", True)),
        "table_max_rows": _int(data.get("table_max_rows"), 0, 0, 1000),
        "table_dpi": _int(data.get("table_dpi"), 200, 100, 400),
        "table_max_width": _num(data.get("table_max_width"), 10.0, 4.0, 20.0),
        "show_thousands": bool(data.get("show_thousands", True)),
        "truncate_hint": str(data.get("truncate_hint") or "仅显示前 {n} 行")[:80],
        # 图表外观
        "chart_type": ctype if ctype in _CHART_TYPES else "auto",
        "show_value_labels": bool(data.get("show_value_labels", True)),
        "show_legend": bool(data.get("show_legend", True)),
        "chart_width": _num(data.get("chart_width"), 7.6, 4.0, 14.0),
        "chart_height": _num(data.get("chart_height"), 4.4, 2.5, 10.0),
        "chart_dpi": _int(data.get("chart_dpi"), 200, 100, 400),
        "chart_max_labels": _int(data.get("chart_max_labels"), 0, 0, 200),
        "show_chart_title": bool(data.get("show_chart_title", False)),
        # 文本
        "text_template": str(data.get("text_template") or "")[:400],
        "clip_bytes": _clip_bytes_setting(data.get("clip_bytes")),
        "chat_limit": _int(data.get("chat_limit"), 20, 1, 100),
        "show_analysis": bool(data.get("show_analysis", True)),
        # 交互文案
        "bind_hint": str(data.get("bind_hint") or "")[:300],
        "empty_hint": str(data.get("empty_hint") or "")[:120],
        "feedback_card": bool(data.get("feedback_card", True)),
        # 语音播报（把文字回答同步合成语音发送）
        "voice_reply": bool(data.get("voice_reply", False)),
        "voice_name": str(data.get("voice_name") or "zh-CN-XiaoxiaoNeural")[:60],
        "voice_max_chars": _int(data.get("voice_max_chars"), 260, 40, 400),
        "voice_rate": _voice_rate(data.get("voice_rate")),
        "voice_volume": _voice_rate(data.get("voice_volume")),
        "voice_pitch": _voice_pitch(data.get("voice_pitch")),
        # 静音时段（整点，-1 表示不启用；支持跨夜，如 22 点至 8 点）
        "voice_quiet_from": _int(data.get("voice_quiet_from"), -1, -1, 23),
        "voice_quiet_to": _int(data.get("voice_quiet_to"), -1, -1, 23),
        # 问数运行参数
        "preview_rows": _int(data.get("preview_rows"), 200, 20, 500),
        "ask_temperature": _num(data.get("ask_temperature"), -1.0, -1.0, 1.0),
        "cache_ttl": _int(data.get("cache_ttl"), 300, 0, 3600),
    }


def _clip_bytes_setting(value) -> int:
    """旧版把阈值写死在 3400/3500 字节，中文一千多字就被截断。这两个值升到官方字节上限。"""
    number = _int(value, WECOM_MAX_BYTES, 500, WECOM_MAX_BYTES)
    if 3400 <= number <= 3500:
        return WECOM_MAX_BYTES
    return number


def _clip(text: str, max_bytes: int = _MAX_BYTES, max_chars: int = WECOM_MAX_CHARS) -> str:
    """裁到 5000 字，同时不超过企业微信单条 20480 字节。超长时按整行截断。"""
    text = text or ""
    max_bytes = min(int(max_bytes or WECOM_MAX_BYTES), WECOM_MAX_BYTES)
    max_chars = min(int(max_chars or WECOM_MAX_CHARS), WECOM_MAX_CHARS)
    if len(text) <= max_chars and len(text.encode("utf-8")) <= max_bytes:
        return text
    tail = _CLIP_TAIL
    budget_bytes = max(0, max_bytes - len(tail.encode("utf-8")))
    budget_chars = max(0, max_chars - len(tail))
    kept: list[str] = []
    used_bytes = 0
    used_chars = 0
    for line in text.splitlines() or [text]:
        size = len(line.encode("utf-8")) + 1
        chars = len(line) + 1
        if kept and (used_bytes + size > budget_bytes or used_chars + chars > budget_chars):
            break
        if not kept and (size > budget_bytes or chars > budget_chars):
            raw = line.encode("utf-8")[:budget_bytes].decode("utf-8", errors="ignore")[:budget_chars]
            for sep in ("。", "！", "？", ".", "!", "?"):
                idx = raw.rfind(sep)
                if idx >= int(len(raw) * 0.6):
                    raw = raw[: idx + 1]
                    break
            return raw.rstrip() + tail
        kept.append(line)
        used_bytes += size
        used_chars += chars
    return "\n".join(kept).strip() + tail


def public_config(value: dict[str, Any] | None) -> dict[str, Any]:
    data = value or {}
    chats = data.get("chat_ids") if isinstance(data.get("chat_ids"), list) else []
    raw_bindings = data.get("bindings") if isinstance(data.get("bindings"), list) else []
    bindings = []
    for item in raw_bindings:
        if not isinstance(item, dict):
            continue
        wecom_userid = str(item.get("wecom_userid") or "").strip()
        login = str(item.get("login") or "").strip()
        if wecom_userid and login:
            bindings.append({"wecom_userid": wecom_userid, "login": login})
    return {
        "enabled": bool(data.get("enabled")),
        "bot_id": str(data.get("bot_id") or ""),
        "secret_set": bool(data.get("secret_enc")),
        "chat_ids": [str(item) for item in chats if str(item).strip()],
        "bindings": bindings,
        "corp_id": str(data.get("corp_id") or ""),
        "corp_secret_set": bool(data.get("corp_secret_enc")),
        "auto_sync": bool(data.get("auto_sync")),
        "last_sync": data.get("last_sync") if isinstance(data.get("last_sync"), dict) else {},
        "style": normalize_style(data.get("style")),
    }


async def load_wecom_config(db: AsyncSession) -> dict[str, Any]:
    row = await db.get(SystemSetting, WECOM_SETTING_KEY)
    value = row.value if row and isinstance(row.value, dict) else {}
    return dict(value)


async def save_wecom_config(
    db: AsyncSession,
    *,
    enabled: bool,
    bot_id: str,
    secret: str | None,
    chat_ids: list[str],
    bindings: list[dict[str, str]] | None = None,
    corp_id: str | None = None,
    corp_secret: str | None = None,
    auto_sync: bool | None = None,
    style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = await load_wecom_config(db)
    secret_enc = current.get("secret_enc") or ""
    if secret:
        secret_enc = encrypt_secret(secret)
    if bindings is None:
        bindings = current.get("bindings") if isinstance(current.get("bindings"), list) else []
    corp_secret_enc = current.get("corp_secret_enc") or ""
    if corp_secret:
        corp_secret_enc = encrypt_secret(corp_secret)
    payload = {
        "enabled": enabled,
        "bot_id": bot_id.strip(),
        "secret_enc": secret_enc,
        "chat_ids": chat_ids,
        "bindings": bindings,
        "corp_id": (corp_id if corp_id is not None else str(current.get("corp_id") or "")).strip(),
        "corp_secret_enc": corp_secret_enc,
        "auto_sync": bool(auto_sync) if auto_sync is not None else bool(current.get("auto_sync")),
        "last_sync": current.get("last_sync") if isinstance(current.get("last_sync"), dict) else {},
        "style": normalize_style(style if style is not None else current.get("style")),
    }
    row = await db.get(SystemSetting, WECOM_SETTING_KEY)
    if row:
        row.value = payload
    else:
        db.add(SystemSetting(key=WECOM_SETTING_KEY, value=payload))
    await db.commit()
    try:
        from app.core.wecom.listener import wecom_link

        wecom_link.request_reconnect()
    except Exception:
        logger.warning("wecom_reconnect_notify_failed")
    return public_config(payload)


def _targets(employee: Any, config: dict[str, Any]) -> list[str]:
    meta = getattr(employee, "metadata_", None) or {}
    own = meta.get("wecom_chat_ids") if isinstance(meta, dict) else None
    source = own if isinstance(own, list) and any(str(item).strip() for item in own) else config.get("chat_ids")
    if not isinstance(source, list):
        return []
    seen: list[str] = []
    for item in source:
        chat_id = str(item).strip()
        if chat_id and chat_id not in seen:
            seen.append(chat_id)
    return seen[:20]


def _markdown(employee: Any, task: Any, run: Any) -> str:
    data = run.output_data if isinstance(getattr(run, "output_data", None), dict) else {}
    body = data.get("output") or ""
    if not isinstance(body, str):
        body = str(body)
    body = body.strip() or "任务已完成。"
    title = f"**{getattr(employee, 'name', '数字员工')}** · {getattr(task, 'name', '定时任务')}"
    return _clip(f"{title}\n\n{body}")


async def _send_markdown(bot_id: str, secret: str, chat_ids: list[str], content: str) -> tuple[list[str], list[dict[str, str]]]:
    sent: list[str] = []
    errors: list[dict[str, str]] = []
    async with websockets.connect(WS_URL, open_timeout=8, close_timeout=3, ping_interval=None) as ws:
        sub_id = f"aibot_subscribe_{uuid.uuid4().hex}"
        await ws.send(json.dumps({
            "cmd": "aibot_subscribe",
            "headers": {"req_id": sub_id},
            "body": {"bot_id": bot_id, "secret": secret},
        }))
        auth = json.loads(await asyncio.wait_for(ws.recv(), 12))
        if auth.get("errcode") != 0:
            raise RuntimeError(auth.get("errmsg") or "企业微信认证失败")
        for chat_id in chat_ids:
            req_id = f"aibot_send_msg_{uuid.uuid4().hex}"
            await ws.send(json.dumps({
                "cmd": "aibot_send_msg",
                "headers": {"req_id": req_id},
                "body": {
                    "chatid": chat_id,
                    "msgtype": "markdown",
                    "markdown": {"content": content},
                },
            }))
            ack = json.loads(await asyncio.wait_for(ws.recv(), 12))
            if ack.get("errcode") != 0:
                errors.append({"chat_id": chat_id, "error": str(ack.get("errmsg") or "发送失败")[:200]})
            else:
                sent.append(chat_id)
    return sent, errors


async def _relay_push(chat_ids: list[str], content: str) -> dict[str, Any] | None:
    import os

    url = os.getenv("WECOM_RELAY_URL", "").strip()
    if not url or os.getenv("RUN_WECOM_LINK", "1") != "0":
        return None
    from app.config import settings

    payload = json.dumps({"chat_ids": chat_ids, "content": content}).encode()

    def _post() -> dict[str, Any]:
        import urllib.request

        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Internal-Token": settings.SECRET_KEY,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as resp:
            return json.loads(resp.read().decode())

    try:
        return await asyncio.to_thread(_post)
    except Exception as exc:
        logger.warning("wecom_relay_failed", error=str(exc)[:200])
        return None


async def push_markdown(db: AsyncSession, chat_ids: list[str], content: str) -> dict[str, Any]:
    config = await load_wecom_config(db)
    bot_id = str(config.get("bot_id") or "").strip()
    secret = decrypt_secret(str(config.get("secret_enc") or "")) if config.get("secret_enc") else ""
    if not config.get("enabled") or not bot_id or not secret:
        return {"ok": False, "skipped": True, "reason": "not_configured"}
    if not chat_ids:
        return {"ok": False, "skipped": True, "reason": "no_targets"}
    body = _clip(content)
    try:
        from app.core.wecom.listener import wecom_link

        if wecom_link.status == "connected":
            return await wecom_link.send_markdown(chat_ids, body)
        relayed = await _relay_push(chat_ids, body)
        if relayed is not None:
            return relayed
        sent, errors = await _send_markdown(bot_id, secret, chat_ids, body)
    except Exception as exc:
        logger.warning("wecom_send_failed", error=str(exc)[:300])
        return {"ok": False, "skipped": False, "error": str(exc)[:300]}
    return {"ok": not errors and bool(sent), "sent": sent, "errors": errors}


async def push_employee_report(db: AsyncSession, *, employee: Any, task: Any, run: Any) -> dict[str, Any]:
    meta = getattr(employee, "metadata_", None) or {}
    if isinstance(meta, dict) and meta.get("wecom_push") is False:
        return {"ok": False, "skipped": True, "reason": "employee_disabled"}
    config = await load_wecom_config(db)
    if not config.get("enabled"):
        return {"ok": False, "skipped": True, "reason": "disabled"}
    targets = _targets(employee, config)
    if not targets:
        return {"ok": False, "skipped": True, "reason": "no_targets"}
    return await push_markdown(db, targets, _markdown(employee, task, run))
