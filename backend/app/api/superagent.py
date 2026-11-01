"""超级智能体 · 只读巡检接口（Phase 1）。

展示来源(Source)子系统记录的触发(Trigger)与线程(Thread),用于验证"事件入系统"的留痕。
仅管理员(org:manage)可见。后续阶段(Eval / 工单)会在此基础上扩展。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_user
from app.core.auth.permissions import assert_permission, resolve_data_scope
from app.core.policy import ACCEPT_MODES, get_policy_view, update_policy
from app.core.sources import SOURCE_KINDS, source_label
from app.db.models import (
    SuperagentDecision,
    SuperagentMandate,
    SuperagentThread,
    SuperagentTrigger,
    User,
)
from app.db.session import get_db

router = APIRouter(prefix="/superagent", tags=["Superagent"])


class PolicySourceIn(BaseModel):
    allowlist: list[str] | None = None
    bot_list: list[str] | None = None


class PolicyUpdateIn(BaseModel):
    accept_mode: str | None = None
    rules: list[dict] | None = None
    note: str | None = None
    sources: dict[str, PolicySourceIn] | None = None


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


@router.get("/policy")
async def get_policy(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_admin(user, db)
    return await get_policy_view(db)


@router.put("/policy")
async def put_policy(
    payload: PolicyUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_admin(user, db)
    if payload.accept_mode is not None and payload.accept_mode not in ACCEPT_MODES:
        raise HTTPException(status_code=400, detail=f"accept_mode 必须为 {ACCEPT_MODES} 之一")
    sources = (
        {k: v.model_dump(exclude_none=True) for k, v in payload.sources.items()}
        if payload.sources
        else None
    )
    try:
        return await update_policy(
            db,
            accept_mode=payload.accept_mode,
            rules=payload.rules,
            note=payload.note,
            sources=sources,
            created_by=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/decisions")
async def list_decisions(
    decision: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_admin(user, db)
    stmt = select(SuperagentDecision).order_by(SuperagentDecision.created_at.desc()).limit(limit)
    if decision:
        stmt = stmt.where(SuperagentDecision.decision == decision)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "decisions": [
            {
                "id": d.id,
                "trigger_id": d.trigger_id,
                "thread_id": d.thread_id,
                "source_kind": d.source_kind,
                "policy_version": d.policy_version,
                "strength": d.strength,
                "decision": d.decision,
                "mandate_id": d.mandate_id,
                "reason": d.reason,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in rows
        ]
    }


@router.get("/mandates")
async def list_mandates(
    limit: int = Query(default=50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_admin(user, db)
    stmt = select(SuperagentMandate).order_by(SuperagentMandate.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "mandates": [
            {
                "id": m.id,
                "trigger_id": m.trigger_id,
                "thread_id": m.thread_id,
                "source_kind": m.source_kind,
                "policy_version": m.policy_version,
                "originator": m.originator,
                "strength": m.strength,
                "matched_rules": m.matched_rules,
                "revoked_at": m.revoked_at.isoformat() if m.revoked_at else None,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in rows
        ]
    }
