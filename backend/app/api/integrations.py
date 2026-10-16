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

# appended by wecom employee push
import re

from pydantic import BaseModel, Field

from app.core.wecom.push import load_wecom_config, public_config, push_markdown, save_wecom_config

_CHAT_ID = re.compile(r"^[\w@.\-]{1,64}$")


class WecomConfigIn(BaseModel):
    enabled: bool = False
    bot_id: str = ""
    secret: str | None = None
    chat_ids: list[str] = Field(default_factory=list)
    bindings: list[str] | None = None


class WecomRelayIn(BaseModel):
    chat_ids: list[str] = Field(default_factory=list)
    content: str = ""


def _clean_chat_ids(items: list[str]) -> list[str]:
    found: list[str] = []
    for raw in items:
        for part in re.split(r"[\s,，]+", raw or ""):
            chat_id = part.strip()
            if not chat_id:
                continue
            if not _CHAT_ID.match(chat_id):
                raise HTTPException(status_code=400, detail=f"接收人格式不正确: {chat_id[:32]}")
            if chat_id not in found:
                found.append(chat_id)
    if len(found) > 20:
        raise HTTPException(status_code=400, detail="接收人不超过 20 个")
    return found


def _clean_bindings(items: list[str] | None) -> list[dict[str, str]] | None:
    if items is None:
        return None
    found: list[dict[str, str]] = []
    for raw in items:
        for part in str(raw or "").splitlines():
            line = part.strip()
            if not line:
                continue
            if "=" not in line and "＝" not in line:
                raise HTTPException(status_code=400, detail=f"绑定格式应为 userid=工号或邮箱: {line[:32]}")
            left, right = re.split(r"[=＝]", line, maxsplit=1)
            wecom_userid, login = left.strip(), right.strip()
            if not wecom_userid or not login:
                raise HTTPException(status_code=400, detail="绑定内容不完整")
            if not _CHAT_ID.match(wecom_userid):
                raise HTTPException(status_code=400, detail=f"userid 格式不正确: {wecom_userid[:32]}")
            row = {"wecom_userid": wecom_userid, "login": login}
            if row not in found:
                found.append(row)
    if len(found) > 50:
        raise HTTPException(status_code=400, detail="绑定不超过 50 条")
    return found


@router.get("/wecom")
async def get_wecom_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await resolve_data_scope(db, user)
    assert_permission(scope, "org:manage")
    from app.core.wecom.listener import wecom_link

    data = public_config(await load_wecom_config(db))
    data["link_status"] = wecom_link.status
    return data


@router.put("/wecom")
async def put_wecom_config(
    payload: WecomConfigIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await resolve_data_scope(db, user)
    assert_permission(scope, "org:manage")
    chats = _clean_chat_ids(payload.chat_ids)
    return await save_wecom_config(
        db,
        enabled=payload.enabled,
        bot_id=payload.bot_id,
        secret=(payload.secret or "").strip() or None,
        chat_ids=chats,
        bindings=_clean_bindings(payload.bindings),
    )


@router.post("/wecom/test")
async def test_wecom_push(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await resolve_data_scope(db, user)
    assert_permission(scope, "org:manage")
    config = public_config(await load_wecom_config(db))
    if not config["enabled"] or not config["bot_id"] or not config["secret_set"]:
        raise HTTPException(status_code=400, detail="请先启用并保存 BotID 和 Secret")
    if not config["chat_ids"]:
        raise HTTPException(status_code=400, detail="请先保存接收人 userid")
    return await push_markdown(db, config["chat_ids"], "数字员工企业微信推送测试")


@router.post("/wecom/relay")
async def relay_wecom(payload: WecomRelayIn, request: Request, db: AsyncSession = Depends(get_db)):
    from app.config import settings
    from app.core.wecom.listener import wecom_link

    token = request.headers.get("x-internal-token") or ""
    if not token or token != settings.SECRET_KEY:
        raise HTTPException(status_code=403, detail="forbidden")
    chats = _clean_chat_ids(payload.chat_ids)
    content = (payload.content or "")[:4000]
    if wecom_link.status == "connected":
        return await wecom_link.send_markdown(chats, content)
    return await push_markdown(db, chats, content)


class WechatDmIn(BaseModel):
    enabled: bool = True
    bindings: list[str] | None = None


class WechatDmMessageIn(BaseModel):
    sender_id: str = ""
    text: str = ""
    message_id: str = ""
    is_group: bool = False


def _clean_wechat_bindings(items: list[str] | None) -> list[dict[str, str]] | None:
    if items is None:
        return None
    found: list[dict[str, str]] = []
    for raw in items:
        for part in str(raw or "").splitlines():
            line = part.strip()
            if not line:
                continue
            if "=" not in line and "＝" not in line:
                raise HTTPException(status_code=400, detail="绑定格式应为 微信身份=工号或邮箱")
            left, right = re.split(r"[=＝]", line, maxsplit=1)
            wechat_id, login = left.strip(), right.strip()
            if not wechat_id or not login:
                raise HTTPException(status_code=400, detail="绑定内容不完整")
            row = {"wechat_id": wechat_id[:128], "login": login[:128]}
            if row not in found:
                found.append(row)
    if len(found) > 50:
        raise HTTPException(status_code=400, detail="绑定不超过 50 条")
    return found


@router.get("/wechat-dm")
async def get_wechat_dm(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await resolve_data_scope(db, user)
    assert_permission(scope, "org:manage")
    from app.core.wechat_dm import load_wechat_dm, public_wechat_dm

    return public_wechat_dm(await load_wechat_dm(db))


@router.put("/wechat-dm")
async def put_wechat_dm(
    payload: WechatDmIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await resolve_data_scope(db, user)
    assert_permission(scope, "org:manage")
    from app.core.wechat_dm import save_wechat_dm

    bindings = _clean_wechat_bindings(payload.bindings)
    if bindings is None:
        from app.core.wechat_dm import load_wechat_dm, public_wechat_dm
        bindings = public_wechat_dm(await load_wechat_dm(db))["bindings"]
    return await save_wechat_dm(db, enabled=payload.enabled, bindings=bindings)


@router.post("/wechat-dm/inbound")
async def wechat_dm_inbound(payload: WechatDmMessageIn, request: Request, db: AsyncSession = Depends(get_db)):
    from app.core.wechat_dm import ingest_dm, load_wechat_dm, token_matches

    config = await load_wechat_dm(db)
    presented = request.headers.get("x-wechat-bridge-token") or ""
    if not token_matches(presented, config):
        raise HTTPException(status_code=403, detail="forbidden")
    reply = await ingest_dm(
        sender_id=(payload.sender_id or "unknown").strip()[:128],
        text=(payload.text or "")[:4000],
        message_id=(payload.message_id or "").strip()[:128],
        is_group=bool(payload.is_group),
    )
    return {"ok": True, "reply": reply, "duplicate": reply == ""}
