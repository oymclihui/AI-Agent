"""待人工面板 API（蓝图阶段二/三）：管理台首页只列「需要人」的工单。

口径与企微 /待办 命令同源：
- waiting：person/answer（待回答）、person/review（待确认）
- inflight：queued / working（处理中）
- failed：24h 内失败（可重试）
- outbox_failed：发件箱三连败未投递条数
- observe：准入/主动工作的 observe 记录（本会做什么），供评审后再开 auto
"""
from __future__ import annotations

import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_admin_user
from app.db.models import OutboxMessage, TaskRecord, User
from app.db.session import get_db

router = APIRouter(prefix="/tasks", tags=["Tasks"])

_WAITING = ("person/answer", "person/review")
_INFLIGHT = ("queued", "working")


def _row(t: TaskRecord) -> dict[str, Any]:
    report = t.report if isinstance(t.report, dict) else {}
    return {
        "id": t.id,
        "user_id": t.user_id,
        "channel": t.channel,
        "question": (t.question or "")[:120],
        "status": t.status,
        "stage": report.get("stage") or "",
        "reply": str(report.get("reply") or "")[:200],
        "would_do": str(report.get("would_do") or "")[:200],
        "mandate": report.get("mandate") if isinstance(report.get("mandate"), dict) else None,
        "trace_id": t.trace_id,
        "error": (t.error or "")[:200],
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "ended_at": t.ended_at.isoformat() if t.ended_at else None,
    }


@router.get("/attention")
async def list_attention(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """待人工视图：只返回需要人介入的工单 + 处理中 + 近期失败。"""
    day_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)

    async def _fetch(statuses: tuple[str, ...], n: int, since=None) -> list[TaskRecord]:
        cond = [TaskRecord.status.in_(statuses)]
        if since is not None:
            cond.append(TaskRecord.created_at >= since)
        rows = (
            await db.execute(
                select(TaskRecord).where(*cond).order_by(TaskRecord.created_at.desc()).limit(n)
            )
        ).scalars().all()
        return list(rows)

    waiting = await _fetch(_WAITING, limit)
    inflight = await _fetch(_INFLIGHT, 20)
    failed = await _fetch(("failed",), 20, since=day_ago)
    outbox_failed = int(
        (
            await db.execute(
                select(func.count())
                .select_from(OutboxMessage)
                .where(OutboxMessage.status == "failed")
            )
        ).scalar()
        or 0
    )
    # observe 评审桶：准入被拒/观察模式下「本会做什么」的记录，以及预警规则的 observe 结果
    observe = (
        (
            await db.execute(
                select(TaskRecord)
                .where(func.json_extract_path_text(TaskRecord.report, "stage") == "observe")
                .order_by(TaskRecord.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return {
        "waiting": [_row(t) for t in waiting],
        "inflight": [_row(t) for t in inflight],
        "failed": [_row(t) for t in failed],
        "outbox_failed": outbox_failed,
        "observe": [_row(t) for t in observe],
    }
