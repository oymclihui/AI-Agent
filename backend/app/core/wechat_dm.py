"""Personal WeChat direct messages, forwarded in from the ClawBot channel."""
from __future__ import annotations

import hmac
import secrets
from collections import deque
from typing import Any

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.anti_hallucination import anti_hallucination_messages
from app.core.data_ask.credentials import decrypt_secret, encrypt_secret
from app.core.wecom.push import _clip
from app.db.base import generate_uuid
from app.db.models import Conversation, Message, MessageRole, SystemSetting, User
from app.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)

WECHAT_DM_KEY = "wechat_dm"
_seen: deque[str] = deque()
_seen_set: set[str] = set()


def _remember(msgid: str) -> bool:
    if not msgid:
        return False
    if msgid in _seen_set:
        return True
    _seen.append(msgid)
    _seen_set.add(msgid)
    while len(_seen) > 500:
        old = _seen.popleft()
        _seen_set.discard(old)
    return False


async def load_wechat_dm(db: AsyncSession) -> dict[str, Any]:
    row = await db.get(SystemSetting, WECHAT_DM_KEY)
    value = row.value if row and isinstance(row.value, dict) else {}
    return dict(value)


def public_wechat_dm(value: dict[str, Any] | None) -> dict[str, Any]:
    data = value or {}
    raw = data.get("bindings") if isinstance(data.get("bindings"), list) else []
    bindings = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        wechat_id = str(item.get("wechat_id") or "").strip()
        login = str(item.get("login") or "").strip()
        if wechat_id and login:
            bindings.append({"wechat_id": wechat_id, "login": login})
    return {
        "enabled": bool(data.get("enabled")),
        "token_set": bool(data.get("token_enc")),
        "bindings": bindings,
    }


async def ensure_bridge_token(db: AsyncSession) -> str:
    current = await load_wechat_dm(db)
    if current.get("token_enc"):
        return decrypt_secret(str(current["token_enc"]))
    token = secrets.token_urlsafe(24)
    current["token_enc"] = encrypt_secret(token)
    current.setdefault("enabled", True)
    current.setdefault("bindings", [])
    row = await db.get(SystemSetting, WECHAT_DM_KEY)
    if row:
        row.value = current
    else:
        db.add(SystemSetting(key=WECHAT_DM_KEY, value=current))
    await db.commit()
    return token


def token_matches(presented: str, config: dict[str, Any]) -> bool:
    enc = str(config.get("token_enc") or "")
    if not presented or not enc:
        return False
    try:
        real = decrypt_secret(enc)
    except Exception:
        return False
    return hmac.compare_digest(presented, real)


async def save_wechat_dm(db: AsyncSession, *, enabled: bool, bindings: list[dict[str, str]]) -> dict[str, Any]:
    current = await load_wechat_dm(db)
    current["enabled"] = enabled
    current["bindings"] = bindings
    if not current.get("token_enc"):
        current["token_enc"] = encrypt_secret(secrets.token_urlsafe(24))
    row = await db.get(SystemSetting, WECHAT_DM_KEY)
    if row:
        row.value = current
    else:
        db.add(SystemSetting(key=WECHAT_DM_KEY, value=current))
    await db.commit()
    return public_wechat_dm(current)


async def _find_user(db: AsyncSession, sender_id: str, config: dict[str, Any]) -> User | None:
    login = ""
    for item in config.get("bindings") or []:
        if isinstance(item, dict) and str(item.get("wechat_id") or "").strip().casefold() == sender_id.casefold():
            login = str(item.get("login") or "").strip()
            break
    if not login:
        return None
    result = await db.execute(
        select(User).where(
            User.is_active.is_(True),
            or_(User.employee_no == login, User.email == login),
        ).limit(1)
    )
    return result.scalar_one_or_none()


async def _admin(db: AsyncSession) -> User | None:
    result = await db.execute(
        select(User).where(User.is_active.is_(True), User.is_admin.is_(True)).limit(1)
    )
    return result.scalar_one_or_none()


async def _conversation(db: AsyncSession, owner: User, sender_id: str, bound: bool) -> Conversation:
    result = await db.execute(
        select(Conversation)
        .where(Conversation.is_active.is_(True), Conversation.owner_id == owner.id)
        .order_by(Conversation.created_at.desc())
        .limit(300)
    )
    for conv in result.scalars():
        meta = conv.metadata_ if isinstance(conv.metadata_, dict) else {}
        if meta.get("wechat_dm_sender") == sender_id:
            return conv
    title = f"微信单聊 · {sender_id}" if bound else f"微信单聊待绑定 · {sender_id}"
    conv = Conversation(
        id=generate_uuid(),
        owner_id=owner.id,
        title=title[:255],
        memory_type="buffer",
        metadata_={
            "wechat_dm_sender": sender_id,
            "connector_id": "wechat-dm",
            "chat_mode": "single",
            "wechat_bound": bound,
        },
    )
    db.add(conv)
    await db.flush()
    return conv


def _bind_text(sender_id: str) -> str:
    return (
        f"已收到。你的微信身份是 {sender_id}。"
        "管理员把它绑定到平台工号后，这条单聊才会按你的权限回答。群消息不在这里处理。"
    )


async def _answer(db: AsyncSession, conv: Conversation, user: User, question: str) -> str:
    from app.api.chat import _ensure_memory_loaded
    from app.core.dialogue.manager import DialogueManager

    memory = await _ensure_memory_loaded(conv.id, conv.memory_type or "buffer", db)
    dialogue = DialogueManager(memory_manager=memory)
    result = await dialogue.chat(
        session_id=conv.id,
        user_message=question,
        extra_system_messages=anti_hallucination_messages(),
        db=db,
        user_id=user.id,
    )
    return str(result.get("message") or "").strip() or "没有生成回答。"


async def ingest_dm(*, sender_id: str, text: str, message_id: str, is_group: bool) -> str:
    if is_group:
        return "个人微信群暂不支持。请在单聊里发文字。"
    content = (text or "").strip()
    if not content:
        return "目前只处理文字。请直接发送文字。"
    if _remember(message_id):
        return ""
    async with AsyncSessionLocal() as db:
        config = await load_wechat_dm(db)
        if not config.get("enabled", True):
            return "微信单聊还没有启用。"
        bound = await _find_user(db, sender_id, config)
        owner = bound or await _admin(db)
        if owner is None:
            return "平台里还没有可用账号。"
        conv = await _conversation(db, owner, sender_id, bound is not None)
        db.add(Message(
            id=generate_uuid(),
            conversation_id=conv.id,
            role=MessageRole.user,
            content=content,
            metadata_={"wechat_sender": sender_id, "source": "wechat-dm"},
        ))
        await db.flush()
        if bound is None:
            reply = _bind_text(sender_id)
        else:
            try:
                reply = await _answer(db, conv, bound, content)
            except Exception as exc:
                logger.exception("wechat_dm_answer_failed", sender=sender_id)
                reply = f"这条消息已进入平台对话，回答失败：{str(exc)[:180]}"
        reply = _clip(reply)
        db.add(Message(
            id=generate_uuid(),
            conversation_id=conv.id,
            role=MessageRole.assistant,
            content=reply,
            metadata_={"source": "wechat-dm"},
        ))
        await db.commit()
        return reply
