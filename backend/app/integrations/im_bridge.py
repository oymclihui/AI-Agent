"""IM bot bridge — route Feishu / DingTalk messages into platform chat."""
from __future__ import annotations

import os
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dialogue.manager import DialogueManager
from app.core.group_chat.orchestrator import GroupChatConfig, GroupChatOrchestrator
from app.core.memory.manager import MemoryManager
from app.db.models import User, Conversation
from app.db.base import generate_uuid

logger = structlog.get_logger(__name__)


def _im_group_agent_ids() -> list[str] | None:
    raw = os.environ.get("IM_GROUP_CHAT_AGENT_IDS", "").strip()
    if not raw:
        return None
    ids = [x.strip() for x in raw.split(",") if x.strip()]
    return ids if len(ids) >= 2 else None


async def resolve_im_bot_user(db: AsyncSession, preferred_user_id: str | None = None) -> User | None:
    if preferred_user_id:
        user = await db.get(User, preferred_user_id)
        if user and user.is_active:
            return user
    result = await db.execute(
        select(User).where(User.is_active == True).order_by(User.is_admin.desc()).limit(1)  # noqa: E712
    )
    return result.scalar_one_or_none()


async def generate_im_reply(
    db: AsyncSession,
    user_message: str,
    *,
    bot_user_id: str | None = None,
    session_key: str,
) -> str:
    user = await resolve_im_bot_user(db, bot_user_id)
    if not user:
        return "AI-AGENT 未配置可用用户，请联系管理员。"

    memory = MemoryManager()
    dialogue = DialogueManager(memory_manager=memory)
    session_id = f"im:{session_key}"

    try:
        result = await dialogue.chat(
            session_id=session_id,
            user_message=user_message,
            db=db,
            user_id=user.id,
        )
        return str(result.get("message") or "").strip() or "(空回复)"
    except Exception as exc:
        logger.exception("im_reply_failed", session=session_key, error=str(exc))
        return f"处理失败：{exc}"


async def generate_im_group_reply(
    db: AsyncSession,
    user_message: str,
    *,
    bot_user_id: str | None = None,
    session_key: str,
    lang: str = "zh",
) -> str:
    """Agent Room for IM bots when IM_GROUP_CHAT_AGENT_IDS is configured."""
    user = await resolve_im_bot_user(db, bot_user_id)
    if not user:
        return "AI-AGENT 未配置可用用户，请联系管理员。"

    agent_ids = _im_group_agent_ids()
    if not agent_ids:
        return await generate_im_reply(db, user_message, bot_user_id=bot_user_id, session_key=session_key)

    conv = Conversation(
        id=generate_uuid(),
        owner_id=user.id,
        title=f"IM群聊 {session_key[:16]}",
        metadata_={
            "chat_mode": "group",
            "group": GroupChatConfig(
                agent_ids=agent_ids,
                orchestration="round_robin",
                max_rounds=1,
                lang=lang,
            ).to_dict(),
            "source": "im_bot",
        },
    )
    db.add(conv)
    await db.flush()

    orchestrator = GroupChatOrchestrator(
        db,
        conv,
        user,
        GroupChatConfig(agent_ids=agent_ids, max_rounds=1, lang=lang),
    )
    synthesis = ""
    try:
        async for ev in orchestrator.stream(user_message):
            if ev.get("event") == "agent_done" and ev.get("is_synthesis"):
                synthesis = str(ev.get("content") or "")
            if ev.get("event") == "done":
                break
        await db.commit()
        return synthesis.strip() or "(空回复)"
    except Exception as exc:
        logger.exception("im_group_reply_failed", session=session_key, error=str(exc))
        return f"群聊处理失败：{exc}"
