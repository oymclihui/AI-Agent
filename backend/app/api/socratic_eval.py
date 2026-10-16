"""S4 苏格拉底反问评估 API"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_user
from app.core.socratic.evaluation import (
    MIN_SOCRATIC_EVAL_SET,
    PROMOTE_CLARIFY_ACCURACY,
    PROMOTE_DIRECT_ACCURACY,
    build_socratic_eval_set,
    run_socratic_eval,
    socratic_quality_metrics,
)
from app.db.models import Agent, SocraticEvalRun, SocraticEvalSet, User
from app.db.session import get_db
from app.schemas.socratic_eval import (
    SocraticEvalRunDetailOut,
    SocraticEvalRunOut,
    SocraticEvalRunTriggerOut,
    SocraticEvalSetBuildOut,
    SocraticEvalSetItemIn,
    SocraticEvalSetItemOut,
    SocraticEvalSetItemUpdateIn,
    SocraticQualityOut,
    SocraticWeeklyOut,
)

logger = logging.getLogger("socratic_eval_api")
router = APIRouter(tags=["SocraticEval"])


def _set_out(row: SocraticEvalSet) -> SocraticEvalSetItemOut:
    return SocraticEvalSetItemOut(
        id=row.id, agent_id=row.agent_id, question=row.question,
        expected_behavior=row.expected_behavior,
        expected_domains=list(row.expected_domains or []),
        difficulty=row.difficulty, active=bool(row.active), note=row.note,
        source=getattr(row, "source", None), created_at=row.created_at,
    )


def _run_out(row: SocraticEvalRun) -> SocraticEvalRunOut:
    return SocraticEvalRunOut(
        id=int(row.id), agent_id=row.agent_id, status=row.status or "pending",
        total=row.total or 0, passed=row.passed or 0,
        clarify_accuracy=row.clarify_accuracy, direct_accuracy=row.direct_accuracy,
        avg_rounds=row.avg_rounds, duration_ms=row.duration_ms,
        created_at=row.created_at,
    )


# ── 考题库 CRUD ──

@router.get("/agents/socratic/eval/set", response_model=list[SocraticEvalSetItemOut])
async def list_eval_set(
    agent_id: str | None = Query(None),
    active_only: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(SocraticEvalSet)
    if agent_id:
        q = q.where(SocraticEvalSet.agent_id == agent_id)
    if active_only:
        q = q.where(SocraticEvalSet.active.is_(True))
    rows = (await db.execute(q.order_by(SocraticEvalSet.created_at.desc()))).scalars().all()
    return [_set_out(r) for r in rows]


@router.post("/agents/socratic/eval/set", response_model=SocraticEvalSetItemOut)
async def create_eval_set_item(
    body: SocraticEvalSetItemIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = SocraticEvalSet(
        agent_id=body.agent_id, question=body.question,
        expected_behavior=body.expected_behavior,
        expected_domains=body.expected_domains, difficulty=body.difficulty,
        note=body.note, source="manual",
    )
    db.add(row)
    await db.flush()
    await db.commit()
    return _set_out(row)


@router.post("/agents/socratic/eval/set/build", response_model=SocraticEvalSetBuildOut)
async def build_eval_set(
    agent_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await build_socratic_eval_set(db, agent_id=agent_id)
    await db.commit()
    return SocraticEvalSetBuildOut(**result)


@router.patch("/socratic-eval-set/{qid}", response_model=SocraticEvalSetItemOut)
async def update_eval_set_item(
    qid: str,
    body: SocraticEvalSetItemUpdateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await db.get(SocraticEvalSet, qid)
    if not row:
        raise HTTPException(404, "考题不存在")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    await db.commit()
    return _set_out(row)


@router.delete("/socratic-eval-set/{qid}")
async def delete_eval_set_item(
    qid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await db.get(SocraticEvalSet, qid)
    if not row:
        raise HTTPException(404, "考题不存在")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ── 回归评估 ──

@router.post("/agents/socratic/eval/run", response_model=SocraticEvalRunTriggerOut)
async def trigger_eval_run(
    agent_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    run_row = SocraticEvalRun(agent_id=agent_id, status="pending")
    db.add(run_row)
    await db.flush()
    await db.commit()

    # 同步执行（考题量小，秒级完成）
    try:
        await run_socratic_eval(db, run_row, agent_id=agent_id)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        run_row.status = "failed"
        run_row.note = str(exc)[:300]
        await db.commit()
        raise HTTPException(500, f"评估失败: {exc}")

    return SocraticEvalRunTriggerOut(run_id=int(run_row.id), message="评估完成")


@router.get("/agents/socratic/eval/runs", response_model=list[SocraticEvalRunOut])
async def list_eval_runs(
    agent_id: str | None = Query(None),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(SocraticEvalRun)
    if agent_id:
        q = q.where(SocraticEvalRun.agent_id == agent_id)
    rows = (await db.execute(q.order_by(SocraticEvalRun.id.desc()).limit(limit))).scalars().all()
    return [_run_out(r) for r in rows]


@router.get("/socratic-eval-runs/{rid}", response_model=SocraticEvalRunDetailOut)
async def get_eval_run_detail(
    rid: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await db.get(SocraticEvalRun, rid)
    if not row:
        raise HTTPException(404, "评估运行不存在")
    detail = _run_out(row).model_dump()
    detail["items"] = list(row.items or [])
    return SocraticEvalRunDetailOut(**detail)


# ── 质量看板 ──

@router.get("/agents/socratic/quality", response_model=SocraticQualityOut)
async def socratic_quality(
    agent_id: str | None = Query(None),
    window_days: int = Query(30, ge=1, le=180),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    metrics = await socratic_quality_metrics(db, agent_id=agent_id, window_days=window_days)
    metrics["agent_id"] = agent_id
    metrics["gates"] = {
        "misclarify_rate_max": 1 - PROMOTE_DIRECT_ACCURACY,
        "clarify_accuracy_min": PROMOTE_CLARIFY_ACCURACY,
        "min_eval_set_size": MIN_SOCRATIC_EVAL_SET,
    }
    return SocraticQualityOut(**metrics)


# ── 每周进化闭环 ──

@router.post("/agents/socratic/weekly", response_model=SocraticWeeklyOut)
async def socratic_weekly(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # 1. 从轨迹蒸馏考题库
    build = await build_socratic_eval_set(db, agent_id=None)
    # 2. 跑一轮回归评估
    run_row = SocraticEvalRun(agent_id=None, status="pending")
    db.add(run_row)
    await db.flush()
    try:
        await run_socratic_eval(db, run_row, agent_id=None)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        return SocraticWeeklyOut(ok=False, message=f"评估失败: {exc}")

    metrics = await socratic_quality_metrics(db, agent_id=None)
    return SocraticWeeklyOut(
        ok=True, message="每周反问质量巡检完成",
        eval_run_id=int(run_row.id), metrics=metrics,
    )
