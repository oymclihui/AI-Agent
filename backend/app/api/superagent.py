"""超级智能体 · 只读巡检接口（Phase 1）。

展示来源(Source)子系统记录的触发(Trigger)与线程(Thread),用于验证"事件入系统"的留痕。
仅管理员(org:manage)可见。后续阶段(Eval / 工单)会在此基础上扩展。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_user
from app.core.auth.permissions import assert_permission, resolve_data_scope
from app.core.sources import SOURCE_KINDS, source_label
from app.db.models import SuperagentThread, SuperagentTrigger, User
from app.db.session import get_db

router = APIRouter(prefix="/superagent", tags=["Superagent"])


async def _require_admin(user: User, db: AsyncSession) -> None:
    scope = await resolve_data_scope(db, user)
    assert_permission(scope, "org:manage")


@router.get("/sources")
async def list_sources(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_admin(user, db)
    counts = dict(
        (
            await db.execute(
                select(SuperagentTrigger.source_kind, func.count())
                .group_by(SuperagentTrigger.source_kind)
            )
        ).all()
    )
    return {
        "sources": [
            {"kind": kind, "label": label, "trigger_count": int(counts.get(kind, 0))}
            for kind, label in SOURCE_KINDS.items()
        ]
    }


@router.get("/triggers")
async def list_triggers(
    source_kind: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_admin(user, db)
    stmt = select(SuperagentTrigger).order_by(SuperagentTrigger.created_at.desc()).limit(limit)
    if source_kind:
        stmt = stmt.where(SuperagentTrigger.source_kind == source_kind)
    rows = (await db.execute(stmt)).scalars().all()
    total = (
        await db.execute(select(func.count()).select_from(SuperagentTrigger))
    ).scalar_one()
    return {
        "total": int(total),
        "triggers": [
            {
                "id": t.id,
                "source_kind": t.source_kind,
                "source_label": source_label(t.source_kind),
                "external_id": t.external_id,
                "thread_id": t.thread_id,
                "actor": t.actor,
                "kind": t.kind,
                "payload": t.payload,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in rows
        ],
    }


@router.get("/threads")
async def list_threads(
    limit: int = Query(default=50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_admin(user, db)
    stmt = (
        select(SuperagentThread)
        .order_by(SuperagentThread.last_trigger_at.desc().nullslast())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "threads": [
            {
                "id": th.id,
                "source_kind": th.source_kind,
                "source_label": source_label(th.source_kind),
                "external_key": th.external_key,
                "kind": th.kind,
                "title": th.title,
                "last_trigger_at": th.last_trigger_at.isoformat() if th.last_trigger_at else None,
                "created_at": th.created_at.isoformat() if th.created_at else None,
            }
            for th in rows
        ]
    }
