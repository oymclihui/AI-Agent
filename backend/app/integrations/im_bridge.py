"""IM bot bridge — route Feishu / DingTalk messages into platform chat."""
from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dialogue.manager import DialogueManager
from app.core.memory.manager import MemoryManager
from app.db.models import User

logger = structlog.get_logger(__name__)


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
