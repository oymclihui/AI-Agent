"""DingTalk bot / stream webhook handler."""
from __future__ import annotations

import json
import time
from typing import Any

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


def parse_dingtalk_event(body: dict[str, Any]) -> dict[str, Any] | None:
    msgtype = body.get("msgtype") or body.get("MsgType")
    if msgtype == "text":
        text = str((body.get("text") or {}).get("content") or body.get("Content") or "").strip()
        session = body.get("conversationId") or body.get("chatbotUserId") or body.get("senderId") or "default"
        return {"type": "message", "text": text, "session_key": str(session)}

    # Enterprise internal app robot callback
    if body.get("msgtype") == "text" or body.get("msgType") == "text":
        text = str((body.get("text") or {}).get("content") or "").strip()
        session = body.get("conversationId") or body.get("senderStaffId") or "default"
        return {"type": "message", "text": text, "session_key": str(session)}

    return None


async def send_dingtalk_text(session_webhook: str | None, text: str) -> None:
    webhook = session_webhook or settings.DINGTALK_ROBOT_WEBHOOK
    if not webhook:
        raise RuntimeError("DINGTALK_ROBOT_WEBHOOK not configured")

    payload = {"msgtype": "text", "text": {"content": text[:4000]}}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(webhook, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") not in (0, None):
            raise RuntimeError(data.get("errmsg") or "DingTalk send failed")


async def send_dingtalk_session_reply(body: dict[str, Any], text: str) -> None:
    webhook = body.get("sessionWebhook") or body.get("session_webhook")
    await send_dingtalk_text(webhook, text)
