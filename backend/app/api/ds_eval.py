"""Agent Evolution 阶段四 L4 API：回归评估与持续进化闭环。

- GET    /data-sources/{sid}/eval/set        考题库列表
- POST   /data-sources/{sid}/eval/set        手工补题（真实业务问题，manage）
- POST   /data-sources/{sid}/eval/set/build  从 golden 查询 + 正例自动构建/扩充（幂等，manage）
- PATCH  /eval-set/{qid}                     编辑 / 停用考题（manage）
- DELETE /eval-set/{qid}                     删除考题（manage）
- POST   /data-sources/{sid}/eval/run        触发一轮回归评估（Celery 异步，manage）
- GET    /data-sources/{sid}/eval/runs       评估运行历史
- GET    /eval-runs/{rid}                    单轮评估详情（逐题明细）
- GET    /data-sources/{sid}/eval/quality    质量看板聚合（最新分 / 趋势 / 弱项）
- GET    /data-sources/{sid}/eval/gaps       主动学习缺口（类目覆盖巡检）
- POST   /eval/weekly                        手动触发每周进化闭环（Celery 异步）
写操作需数据源 manage 权限。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_user
from app.core.data_ask.evaluation.builder import build_eval_set
from app.core.data_ask.evaluation.categories import classify_question
from app.core.data_ask.evaluation.gaps import coverage_gaps
from app.core.data_ask.evaluation.runner import (
    MIN_EVAL_SET,
    PROMOTE_CONSISTENCY,
    PROMOTE_SQL_SUCCESS,
)
from app.core.data_ask.govern.access import assert_data_source_access
from app.db.models import AgentEvalRun, AgentEvalSet, DataSource, User
from app.db.session import get_db
from app.schemas.ds_eval import (
    EvalGapsOut,
    EvalQualityOut,
    EvalRunDetailOut,
    EvalRunOut,
    EvalRunTriggerOut,
    EvalSetBuildOut,
    EvalSetItemIn,
    EvalSetItemOut,
    EvalSetItemUpdateIn,
    EvalTrendPoint,
)

router = APIRouter(tags=["DsEval"])


async def _get_source(db: AsyncSession, sid: str) -> DataSource:
    source = await db.get(DataSource, sid)
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return source


def _set_out(row: AgentEvalSet) -> EvalSetItemOut:
    return EvalSetItemOut(
        id=row.id, data_source_id=row.data_source_id, agent_id=row.agent_id,
        question=row.question, expected_sql=row.expected_sql,
        expected_signature=row.expected_signature, signature_source=row.signature_source,
        expected_row_count=row.expected_row_count, expected_chart=row.expected_chart,
        category=row.category or "aggregation", source=row.source or "manual",
        difficulty=row.difficulty or "medium", active=bool(row.active),
        note=row.note, created_at=row.created_at,
    )


def _run_out(row: AgentEvalRun) -> EvalRunOut:
    return EvalRunOut(
        id=int(row.id), data_source_id=row.data_source_id, agent_id=row.agent_id,
        agent_version_id=row.agent_version_id, agent_version=row.agent_version,
        trigger=row.trigger or "manual", status=row.status or "pending",
        total=row.total or 0, passed=row.passed or 0,
        sql_success_rate=row.sql_success_rate, consistency_rate=row.consistency_rate,
        judge_score=row.judge_score, overall_score=row.overall_score,
        weak_categories=list(row.weak_categories or []),
        error_message=row.error_message, duration_ms=row.duration_ms,
        note=row.note, created_at=row.created_at,
    )


# ─── 考题库 ───

@router.get("/data-sources/{sid}/eval/set", response_model=list[EvalSetItemOut])
async def list_eval_set(
    sid: str,
    include_inactive: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    stmt = select(AgentEvalSet).where(AgentEvalSet.data_source_id == str(source.id))
    if not include_inactive:
        stmt = stmt.where(AgentEvalSet.active.is_(True))
    stmt = stmt.order_by(AgentEvalSet.created_at.asc())
    rows = (await db.execute(stmt)).scalars().all()
    return [_set_out(r) for r in rows]


@router.post("/data-sources/{sid}/eval/set", response_model=EvalSetItemOut)
async def create_eval_item(
    sid: str,
    payload: EvalSetItemIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    row = AgentEvalSet(
        data_source_id=str(source.id),
        agent_id=str(source.agent_id) if source.agent_id else None,
        question=payload.question.strip(),
        expected_sql=payload.expected_sql,
        expected_row_count=payload.expected_row_count,
        expected_chart=payload.expected_chart,
        category=payload.category or classify_question(payload.question),
        source="manual",
        difficulty=payload.difficulty or "medium",
        note=(payload.note or "")[:500] or None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _set_out(row)


@router.post("/data-sources/{sid}/eval/set/build", response_model=EvalSetBuildOut)
async def build_eval_set_api(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    result = await build_eval_set(db, source)
    await db.commit()
    return EvalSetBuildOut(**result)


@router.patch("/eval-set/{qid}", response_model=EvalSetItemOut)
async def update_eval_item(
    qid: str,
    payload: EvalSetItemUpdateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await db.get(AgentEvalSet, qid)
    if not row:
        raise HTTPException(status_code=404, detail="考题不存在")
    source = await _get_source(db, row.data_source_id)
    await assert_data_source_access(db, source, user, require_manage=True)
    data = payload.model_dump(exclude_unset=True)
    if "question" in data and data["question"]:
        row.question = data["question"].strip()
        if "category" not in data:
            row.category = classify_question(row.question)
    for field in ("expected_sql", "expected_row_count", "expected_chart", "category", "difficulty", "active"):
        if field in data:
            setattr(row, field, data[field])
    if "note" in data:
        row.note = (data["note"] or "")[:500] or None
    # 题目被修改后，旧签名基线失效，下轮评估重建
    if "question" in data or "expected_sql" in data:
        row.expected_signature = None
        row.signature_source = None
    await db.commit()
    await db.refresh(row)
    return _set_out(row)


@router.delete("/eval-set/{qid}")
async def delete_eval_item(
    qid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await db.get(AgentEvalSet, qid)
    if not row:
        raise HTTPException(status_code=404, detail="考题不存在")
    source = await _get_source(db, row.data_source_id)
    await assert_data_source_access(db, source, user, require_manage=True)
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ─── 评估运行 ──

@router.post("/data-sources/{sid}/eval/run", response_model=EvalRunTriggerOut)
async def trigger_eval_run(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    set_size = int((
        await db.execute(
            select(func.count(AgentEvalSet.id)).where(
                AgentEvalSet.data_source_id == str(source.id), AgentEvalSet.active.is_(True),
            )
        )
    ).scalar() or 0)
    if set_size == 0:
        raise HTTPException(status_code=400, detail="考题库为空：请先构建或手工补题")

    from app.core.data_ask.factory.versioning import active_version

    version_row = None
    if source.agent_id:
        version_row = await active_version(db, str(source.agent_id))
    run_row = AgentEvalRun(
        data_source_id=str(source.id),
        agent_id=str(source.agent_id) if source.agent_id else None,
        agent_version_id=int(version_row.id) if version_row else None,
        agent_version=int(version_row.version) if version_row else None,
        trigger="manual",
        status="pending",
    )
    db.add(run_row)
    await db.commit()
    await db.refresh(run_row)

    from app.worker import celery_app
    celery_app.send_task("ds_eval.run_evaluation", args=[str(source.id), int(run_row.id)])
    return EvalRunTriggerOut(
        run_id=int(run_row.id), status="pending",
        message=f"回归评估已提交异步执行（{set_size} 题）",
    )


@router.get("/data-sources/{sid}/eval/runs", response_model=list[EvalRunOut])
async def list_eval_runs(
    sid: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    rows = (
        await db.execute(
            select(AgentEvalRun)
            .where(AgentEvalRun.data_source_id == str(source.id))
            .order_by(AgentEvalRun.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_run_out(r) for r in rows]


@router.get("/eval-runs/{rid}", response_model=EvalRunDetailOut)
async def get_eval_run(
    rid: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await db.get(AgentEvalRun, int(rid))
    if not row:
        raise HTTPException(status_code=404, detail="评估运行不存在")
    source = await _get_source(db, row.data_source_id)
    await assert_data_source_access(db, source, user)
    out = _run_out(row)
    return EvalRunDetailOut(**out.model_dump(), items=list(row.items or []))


# ─── 质量看板 ──

@router.get("/data-sources/{sid}/eval/quality", response_model=EvalQualityOut)
async def eval_quality(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    ds = str(source.id)

    set_size = int((
        await db.execute(
            select(func.count(AgentEvalSet.id)).where(
                AgentEvalSet.data_source_id == ds, AgentEvalSet.active.is_(True),
            )
        )
    ).scalar() or 0)

    done_runs = (
        await db.execute(
            select(AgentEvalRun)
            .where(AgentEvalRun.data_source_id == ds, AgentEvalRun.status == "done")
            .order_by(AgentEvalRun.id.desc())
            .limit(10)
        )
    ).scalars().all()
    latest = done_runs[0] if done_runs else None
    trend = [
        EvalTrendPoint(
            run_id=int(r.id), created_at=r.created_at, agent_version=r.agent_version,
            overall_score=r.overall_score, sql_success_rate=r.sql_success_rate,
            consistency_rate=r.consistency_rate, judge_score=r.judge_score,
        )
        for r in reversed(done_runs)
    ]
    return EvalQualityOut(
        data_source_id=ds,
        eval_set_size=set_size,
        latest_run=_run_out(latest) if latest else None,
        trend=trend,
        weak_categories=list(latest.weak_categories or []) if latest else [],
        promotion_gate={
            "sql_success_rate": PROMOTE_SQL_SUCCESS,
            "consistency_rate": PROMOTE_CONSISTENCY,
            "min_eval_set_size": MIN_EVAL_SET,
        },
    )


@router.get("/data-sources/{sid}/eval/gaps", response_model=EvalGapsOut)
async def eval_gaps(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    result = await coverage_gaps(db, source)
    return EvalGapsOut(**result)


# ─── 每周进化闭环 ──

@router.post("/eval/weekly")
async def trigger_weekly_evolution(
    user: User = Depends(get_current_user),
):
    from app.worker import celery_app
    celery_app.send_task("ds_eval.weekly_evolution")
    return {"ok": True, "message": "每周进化闭环已提交异步执行（蒸馏→候选版本→回归评估→达标晋升）"}
