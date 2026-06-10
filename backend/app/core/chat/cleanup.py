"""Auto-delete conversations older than retention policy."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from app.config import settings
from app.db.models import Conversation
from app.db.session import AsyncSessionLocal
from app.core.chat.storage import delete_conversation_uploads

logger = structlog.get_logger(__name__)

_last_cleanup: datetime | None = None


async def cleanup_stale_conversations(force: bool = False) -> int:
    """Delete conversations older than CONVERSATION_RETENTION_DAYS. Returns count deleted."""
    global _last_cleanup
    now = datetime.now(timezone.utc)
    if not force and _last_cleanup and (now - _last_cleanup).total_seconds() < 3600:
        return 0

    cutoff = now - timedelta(days=settings.CONVERSATION_RETENTION_DAYS)
    deleted = 0

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Conversation).where(Conversation.created_at < cutoff)
        )
        convs = result.scalars().all()
        for conv in convs:
            delete_conversation_uploads(conv.id)
            await session.delete(conv)
            deleted += 1
        if deleted:
            await session.commit()
            logger.info(
                "conversations_cleaned",
                deleted=deleted,
                retention_days=settings.CONVERSATION_RETENTION_DAYS,
            )

    _last_cleanup = now
    return deleted
