"""触发事件入库服务 — 幂等、旁路、绝不影响调用方。

设计要点（见蓝图 Phase 1）：
- 在**独立的 DB 会话**里记录，不参与调用方（IM 回复 / 调度器）的事务，
  因此记录失败也不会破坏现有行为；
- 以 (source_kind, external_id) 唯一键做幂等：同一事件只入库一次，
  来源重试投递或进程重启都不会重放；
- 任何异常都只记日志并返回，不向上抛。
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sources.base import IncomingTrigger
from app.db.models import SuperagentThread, SuperagentTrigger

logger = structlog.get_logger(__name__)


async def _get_or_create_thread(db: AsyncSession, inc: IncomingTrigger) -> SuperagentThread:
    result = await db.execute(
        select(SuperagentThread).where(
            SuperagentThread.source_kind == inc.source_kind,
            SuperagentThread.external_key == inc.thread_external_key,
        )
    )
    thread = result.scalar_one_or_none()
    if thread is not None:
        return thread

    thread = SuperagentThread(
        source_kind=inc.source_kind,
        external_key=inc.thread_external_key[:255],
        kind=inc.thread_kind,
        title=(inc.title[:255] if inc.title else None),
    )
    db.add(thread)
    await db.flush()
    return thread


async def record_trigger(inc: IncomingTrigger) -> bool:
    """幂等记录一个触发事件。返回 True 表示新建，False 表示重复或失败（永不抛异常）。"""
    from app.db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            dup = await db.execute(
                select(SuperagentTrigger.id).where(
                    SuperagentTrigger.source_kind == inc.source_kind,
                    SuperagentTrigger.external_id == inc.external_id,
                )
            )
            if dup.scalar_one_or_none() is not None:
                return False

            thread = await _get_or_create_thread(db, inc)
            db.add(
                SuperagentTrigger(
                    source_kind=inc.source_kind,
                    external_id=inc.external_id[:255],
                    thread_id=thread.id,
                    actor=(inc.actor[:255] if inc.actor else None),
                    kind=inc.kind,
                    payload=inc.payload or {},
                )
            )
            thread.last_trigger_at = datetime.now(timezone.utc)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                return False
            return True
    except Exception as exc:  # 旁路记录绝不影响主流程
        logger.warning(
            "superagent_intake_failed",
            source=inc.source_kind,
            external_id=inc.external_id,
            error=str(exc),
        )
        return False
