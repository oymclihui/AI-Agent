"""Push a finished digital-employee report to WeCom over the bot long connection."""
from __future__ import annotations

import asyncio
import json
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
_MAX_BYTES = 3500


def _clip(text: str) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= _MAX_BYTES:
        return text
    return raw[:_MAX_BYTES].decode("utf-8", errors="ignore")


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
) -> dict[str, Any]:
    current = await load_wecom_config(db)
    secret_enc = current.get("secret_enc") or ""
    if secret:
        secret_enc = encrypt_secret(secret)
    if bindings is None:
        bindings = current.get("bindings") if isinstance(current.get("bindings"), list) else []
    payload = {
        "enabled": enabled,
        "bot_id": bot_id.strip(),
        "secret_enc": secret_enc,
        "chat_ids": chat_ids,
        "bindings": bindings,
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
