"""Feishu (Lark) bot event handler."""
from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}


async def _tenant_access_token() -> str:
    import time

    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]

    if not settings.FEISHU_APP_ID or not settings.FEISHU_APP_SECRET:
        raise RuntimeError("FEISHU_APP_ID / FEISHU_APP_SECRET not configured")

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": settings.FEISHU_APP_ID, "app_secret": settings.FEISHU_APP_SECRET},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(data.get("msg") or "Feishu token error")
        _token_cache["token"] = data["tenant_access_token"]
        _token_cache["expires_at"] = now + int(data.get("expire", 7200))
        return _token_cache["token"]


async def send_feishu_text(chat_id: str, text: str) -> None:
    token = await _tenant_access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://open.feishu.cn/open-apis/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text[:4000]}),
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(data.get("msg") or "Feishu send failed")


def parse_feishu_event(body: dict[str, Any]) -> dict[str, Any] | None:
    if body.get("type") == "url_verification":
        return {"type": "challenge", "challenge": body.get("challenge")}

    header = body.get("header") or {}
    if header.get("token") and settings.FEISHU_VERIFICATION_TOKEN:
        if header["token"] != settings.FEISHU_VERIFICATION_TOKEN:
            raise ValueError("Invalid Feishu verification token")

    event = body.get("event") or {}
    message = event.get("message") or {}
    if message.get("message_type") != "text":
        return None

    content_raw = message.get("content") or "{}"
    try:
        content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
    except json.JSONDecodeError:
        content = {"text": str(content_raw)}

    text = str(content.get("text") or "").strip()
    if not text:
        return None

    return {
        "type": "message",
        "text": text,
        "chat_id": message.get("chat_id"),
        "message_id": message.get("message_id"),
        "sender_id": (event.get("sender") or {}).get("sender_id", {}).get("open_id"),
    }
