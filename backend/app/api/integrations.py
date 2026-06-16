"""External IM integrations — Feishu / DingTalk webhooks."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth.deps import get_current_user
from app.core.auth.permissions import assert_permission, resolve_data_scope
from app.db.models import User
from app.db.session import get_db
from app.integrations.dingtalk import parse_dingtalk_event, send_dingtalk_session_reply
from app.integrations.feishu import parse_feishu_event, send_feishu_text
from app.integrations.im_bridge import generate_im_group_reply

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/integrations", tags=["Integrations"])


@router.get("/status")
async def integration_status():
    return {
        "feishu": {
            "enabled": settings.FEISHU_ENABLED,
            "configured": bool(settings.FEISHU_APP_ID and settings.FEISHU_APP_SECRET),
            "webhook_path": "/api/v1/integrations/feishu/events",
        },
        "dingtalk": {
            "enabled": settings.DINGTALK_ENABLED,
            "configured": bool(settings.DINGTALK_ROBOT_WEBHOOK or settings.DINGTALK_APP_KEY),
            "webhook_path": "/api/v1/integrations/dingtalk/events",
        },
    }


@router.get("/admin/status")
async def integration_admin_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await resolve_data_scope(db, user)
    assert_permission(scope, "org:manage")
    return {
        "feishu": {
            "enabled": settings.FEISHU_ENABLED,
            "app_id": settings.FEISHU_APP_ID or None,
            "verification_token_set": bool(settings.FEISHU_VERIFICATION_TOKEN),
            "events_url": f"{settings.APP_PUBLIC_URL.rstrip('/')}/api/v1/integrations/feishu/events",
        },
        "dingtalk": {
            "enabled": settings.DINGTALK_ENABLED,
            "robot_webhook_set": bool(settings.DINGTALK_ROBOT_WEBHOOK),
            "events_url": f"{settings.APP_PUBLIC_URL.rstrip('/')}/api/v1/integrations/dingtalk/events",
        },
        "im_bot_user_id": settings.IM_BOT_USER_ID or None,
    }


@router.post("/feishu/events")
async def feishu_events(request: Request, db: AsyncSession = Depends(get_db)):
    if not settings.FEISHU_ENABLED:
        raise HTTPException(status_code=503, detail="Feishu integration disabled")

    body = await request.json()
    parsed = parse_feishu_event(body)
    if not parsed:
        return {"ok": True}

    if parsed.get("type") == "challenge":
        return {"challenge": parsed.get("challenge")}

    text = parsed.get("text") or ""
    chat_id = parsed.get("chat_id")
    sender = parsed.get("sender_id") or "feishu"
    reply = await generate_im_group_reply(
        db,
        text,
        bot_user_id=settings.IM_BOT_USER_ID or None,
        session_key=f"feishu:{sender}",
    )
    await db.commit()

    if chat_id:
        try:
            await send_feishu_text(chat_id, reply)
        except Exception as exc:
            logger.exception("feishu_send_failed", error=str(exc))
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"ok": True}


@router.post("/dingtalk/events")
async def dingtalk_events(request: Request, db: AsyncSession = Depends(get_db)):
    if not settings.DINGTALK_ENABLED:
        raise HTTPException(status_code=503, detail="DingTalk integration disabled")

    body = await request.json()
    parsed = parse_dingtalk_event(body)
    if not parsed:
        return {"ok": True}

    text = parsed.get("text") or ""
    session_key = parsed.get("session_key") or "dingtalk"
    reply = await generate_im_group_reply(
        db,
        text,
        bot_user_id=settings.IM_BOT_USER_ID or None,
        session_key=f"dingtalk:{session_key}",
    )
    await db.commit()

    try:
        await send_dingtalk_session_reply(body, reply)
    except Exception as exc:
        logger.exception("dingtalk_send_failed", error=str(exc))
        # Some callbacks have no session webhook — still accept event
        if body.get("sessionWebhook") or body.get("session_webhook"):
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"ok": True}
