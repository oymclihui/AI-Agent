"""Turn a WeCom bot message into a platform conversation and reply."""
from __future__ import annotations

import re
import uuid
from collections import deque
from typing import Any

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.anti_hallucination import anti_hallucination_messages
from app.core.dialogue.manager import DialogueManager
from app.core.wecom.push import _clip, load_wecom_config
from app.db.base import generate_uuid
from app.db.models import Conversation, Message, MessageRole, User
from app.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)

_seen: deque[str] = deque()
_seen_set: set[str] = set()
_MENTION = re.compile(r"^@\S+\s*")


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


def _text_from_body(body: dict[str, Any]) -> str:
    kind = str(body.get("msgtype") or "")
    if kind == "text":
        text = str((body.get("text") or {}).get("content") or "")
    elif kind == "mixed":
        parts: list[str] = []
        for item in (body.get("mixed") or {}).get("msg_item") or []:
            if isinstance(item, dict) and item.get("msgtype") == "text":
                parts.append(str((item.get("text") or {}).get("content") or ""))
        text = "\n".join(parts)
    else:
        return ""
    return _MENTION.sub("", text).strip()


async def _find_user(db: AsyncSession, userid: str, config: dict[str, Any]) -> User | None:
    login = ""
    for item in config.get("bindings") or []:
        if isinstance(item, dict) and str(item.get("wecom_userid") or "").strip() == userid:
            login = str(item.get("login") or "").strip()
            break
    filters = [User.employee_no == userid, User.email == userid]
    if login:
        filters.extend([User.employee_no == login, User.email == login])
    result = await db.execute(select(User).where(User.is_active.is_(True), or_(*filters)).limit(1))
    return result.scalar_one_or_none()


async def _admin(db: AsyncSession) -> User | None:
    result = await db.execute(
        select(User).where(User.is_active.is_(True), User.is_admin.is_(True)).limit(1)
    )
    return result.scalar_one_or_none()


async def _conversation(db: AsyncSession, owner: User, key: str, userid: str, bound: bool) -> Conversation:
    result = await db.execute(
        select(Conversation)
        .where(Conversation.is_active.is_(True), Conversation.owner_id == owner.id)
        .order_by(Conversation.created_at.desc())
        .limit(300)
    )
    for conv in result.scalars():
        meta = conv.metadata_ if isinstance(conv.metadata_, dict) else {}
        if meta.get("wecom_chat_key") == key:
            return conv
    title = f"企业微信 · {userid}"
    if not bound:
        title = f"企业微信待绑定 · {userid}"
    conv = Conversation(
        id=generate_uuid(),
        owner_id=owner.id,
        title=title[:255],
        memory_type="buffer",
        metadata_={
            "wecom_chat_key": key,
            "wecom_userid": userid,
            "connector_id": "wecom-bot",
            "chat_mode": "single",
            "wecom_bound": bound,
        },
    )
    db.add(conv)
    await db.flush()
    return conv


def _bind_text(userid: str) -> str:
    return (
        f"已收到，并记在平台对话里。你的企业微信 userid 是 {userid}。"
        "请管理员在对话的「企业微信」连接器中把这个 userid 绑定到平台工号或邮箱后，才能继续问答。"
    )


async def _answer(db: AsyncSession, conv: Conversation, user: User, question: str) -> str:
    meta = conv.metadata_ if isinstance(conv.metadata_, dict) else {}
    source_id = str(meta.get("data_source_id") or "").strip()
    if source_id and meta.get("chat_mode") in ("single", "data_ask", None):
        from app.core.data_ask.experience.chat_bridge import format_data_ask_for_chat
        from app.core.data_ask.service import run_data_ask

        result = await run_data_ask(
            db,
            data_source_id=source_id,
            question=question,
            user=user,
            history=[],
        )
        return await format_data_ask_for_chat(result, user)

    from app.api.chat import _ensure_memory_loaded

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


async def ingest_text(*, userid: str, content: str, chattype: str, chatid: str) -> tuple[str, str]:
    """Save the WeCom text into a platform conversation and return (reply, conversation_id)."""
    key = f"{chattype}:{chatid or userid}"
    async with AsyncSessionLocal() as db:
        config = await load_wecom_config(db)
        bound_user = await _find_user(db, userid, config)
        owner = bound_user or await _admin(db)
        if owner is None:
            return "平台里还没有可用账号，暂时无法记下这条对话。", ""
        conv = await _conversation(db, owner, key, userid, bound_user is not None)
        db.add(Message(
            id=generate_uuid(),
            conversation_id=conv.id,
            role=MessageRole.user,
            content=content,
            metadata_={"wecom_userid": userid, "source": "wecom"},
        ))
        await db.flush()
        if bound_user is None:
            reply = _bind_text(userid)
        else:
            try:
                reply = await _answer(db, conv, bound_user, content)
            except Exception as exc:
                logger.exception("wecom_answer_failed", userid=userid)
                reply = f"这条消息已进入平台对话，回答失败：{str(exc)[:180]}"
        reply = _clip(reply)
        db.add(Message(
            id=generate_uuid(),
            conversation_id=conv.id,
            role=MessageRole.assistant,
            content=reply,
            metadata_={"source": "wecom"},
        ))
        await db.commit()
        return reply, conv.id


async def handle_frame(link: Any, frame: dict[str, Any]) -> None:
    cmd = str(frame.get("cmd") or "")
    req_id = str((frame.get("headers") or {}).get("req_id") or "")
    body = frame.get("body") if isinstance(frame.get("body"), dict) else {}
    if cmd == "aibot_event_callback":
        if req_id:
            try:
                await link.reply_welcome(req_id, "你好，直接发文字。对话会进入平台。")
            except Exception as exc:
                logger.warning("wecom_welcome_failed", error=str(exc)[:200])
        return
    if cmd != "aibot_msg_callback" or not req_id:
        return
    msgid = str(body.get("msgid") or "")
    if _remember(msgid):
        return
    sender = body.get("from") if isinstance(body.get("from"), dict) else {}
    userid = str(sender.get("userid") or "").strip() or "unknown"
    chattype = str(body.get("chattype") or "single")
    chatid = str(body.get("chatid") or "")
    content = _text_from_body(body)
    stream_id = f"stream_{uuid.uuid4().hex}"
    if not content:
        note = "目前只接入文字消息。请直接发送文字。"
        await link.reply_stream(req_id, stream_id, note, finish=True)
        return
    try:
        await link.reply_stream(req_id, stream_id, "正在处理…", finish=False)
    except Exception as exc:
        logger.warning("wecom_ack_failed", error=str(exc)[:200])
    reply, _conv_id = await ingest_text(userid=userid, content=content, chattype=chattype, chatid=chatid)
    await link.reply_stream(req_id, stream_id, reply, finish=True)
