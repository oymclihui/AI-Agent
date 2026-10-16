"""Agent Evolution 阶段一 API：Schema 画像 / 业务语义层 / 问数反馈 / 问数轨迹。

- POST /data-sources/{sid}/profile/build   触发画像构建（Celery 异步，防重）
- GET  /data-sources/{sid}/profile         最新 ready 画像
- GET  /data-sources/{sid}/profile/status  最新状态（前端轮询）
- 术语词典 /data-sources/{sid}/terms       CRUD（写操作需 manage 权限）
- 指标口径 /data-sources/{sid}/metrics     CRUD（写操作需 manage 权限）
- POST /data-ask/feedback                  赞/踩/纠正SQL/保存示例（纠正与示例写 golden_queries）
- GET  /data-ask/traces                    问数轨迹列表
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_user
from app.core.data_ask.govern.access import assert_data_source_access
from app.core.data_ask.intelligence.query_memory import save_golden_query
from app.db.models import (
    AskFeedback,
    AskTrace,
    DataAskTrainTask,
    DataSource,
    DsSchemaProfile,
    DsSemanticMetric,
    DsSemanticTerm,
    User,
)
from app.db.session import get_db
from app.schemas.ds_growth import (
    FeedbackIn,
    FeedbackOut,
    MetricIn,
    MetricOut,
    ProfileBuildOut,
    ProfileOut,
    ProfileStatusOut,
    TermIn,
    TermOut,
    TraceOut,
    TrainTaskOut,
)

router = APIRouter(tags=["DsGrowth"])

_EXCEL_DRIVERS = ("excel_folder", "excel_template")
_FEEDBACK_TYPES = ("like", "dislike", "correction", "example")


async def _get_source(db: AsyncSession, sid: str) -> DataSource:
    source = await db.get(DataSource, sid)
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return source


def _is_select(sql: str) -> bool:
    s = sql.strip().lstrip("(").strip().lower()
    return s.startswith("select") or s.startswith("with")


# ────────────────────── Schema 画像 ──────────────────────

@router.post("/data-sources/{sid}/profile/build", response_model=ProfileBuildOut)
async def build_profile(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    if str(source.driver) in _EXCEL_DRIVERS:
        raise HTTPException(status_code=400, detail="Excel 类数据源暂不支持 Schema 画像（阶段一仅覆盖数据库类数据源）")

    # 防重：已有 building 状态的画像直接返回
    res = await db.execute(
        select(DsSchemaProfile)
        .where(DsSchemaProfile.data_source_id == str(sid))
        .order_by(DsSchemaProfile.version.desc())
    )
    rows = list(res.scalars().all())
    for r in rows:
        if r.status == "building":
            return ProfileBuildOut(
                profile_id=r.id, version=r.version, status="building",
                message="画像正在构建中，请稍后查看状态",
            )
    next_version = (rows[0].version + 1) if rows else 1
    row = DsSchemaProfile(
        data_source_id=str(sid), version=next_version, status="building", trigger="manual",
    )
    db.add(row)
    await db.flush()

    from app.core.data_ask.profile_tasks import build_profile_task

    build_profile_task.delay(str(sid), trigger="manual", profile_id=row.id)
    return ProfileBuildOut(
        profile_id=row.id, version=next_version, status="building",
        message="画像构建任务已启动",
    )


@router.get("/data-sources/{sid}/profile", response_model=ProfileOut)
async def get_profile(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    from app.core.data_ask.profile import get_latest_profile

    row = await get_latest_profile(db, str(sid))
    if not row:
        raise HTTPException(status_code=404, detail="尚无可用画像，请先触发构建")
    return ProfileOut(
        id=row.id, data_source_id=row.data_source_id, version=row.version,
        status=row.status, trigger=row.trigger, profile=row.profile,
        table_count=row.table_count, column_count=row.column_count,
        row_counts=row.row_counts, duration_ms=row.duration_ms, error=row.error,
        created_at=row.created_at,
    )


@router.get("/data-sources/{sid}/profile/status", response_model=ProfileStatusOut)
async def profile_status(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    res = await db.execute(
        select(DsSchemaProfile)
        .where(DsSchemaProfile.data_source_id == str(sid))
        .order_by(DsSchemaProfile.version.desc())
        .limit(1)
    )
    row = res.scalar_one_or_none()
    if not row:
        return ProfileStatusOut(status="none")
    return ProfileStatusOut(
        status=row.status, profile_id=row.id, version=row.version,
        error=row.error, duration_ms=row.duration_ms, updated_at=row.updated_at,
    )


# ────────────────────── 术语词典 CRUD ──────────────────────

@router.get("/data-sources/{sid}/terms", response_model=list[TermOut])
async def list_terms(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    res = await db.execute(
        select(DsSemanticTerm)
        .where(DsSemanticTerm.data_source_id == str(sid))
        .order_by(DsSemanticTerm.created_at.desc())
    )
    return [
        TermOut(
            id=t.id, term=t.term, definition=t.definition, column_ref=t.column_ref,
            synonyms=t.synonyms or [], source=t.source, use_count=t.use_count or 0,
            created_at=t.created_at,
        )
        for t in res.scalars().all()
    ]


@router.post("/data-sources/{sid}/terms", response_model=TermOut)
async def create_term(
    sid: str,
    payload: TermIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    row = DsSemanticTerm(
        data_source_id=str(sid), term=payload.term.strip(),
        definition=(payload.definition or "").strip() or None,
        column_ref=(payload.column_ref or "").strip() or None,
        synonyms=[s.strip() for s in (payload.synonyms or []) if s.strip()][:20],
        source="manual",
    )
    db.add(row)
    await db.flush()
    return TermOut(
        id=row.id, term=row.term, definition=row.definition, column_ref=row.column_ref,
        synonyms=row.synonyms or [], source=row.source, use_count=0, created_at=row.created_at,
    )


@router.put("/data-sources/{sid}/terms/{tid}", response_model=TermOut)
async def update_term(
    sid: str,
    tid: str,
    payload: TermIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    row = await db.get(DsSemanticTerm, tid)
    if not row or row.data_source_id != str(sid):
        raise HTTPException(status_code=404, detail="术语不存在")
    row.term = payload.term.strip()
    row.definition = (payload.definition or "").strip() or None
    row.column_ref = (payload.column_ref or "").strip() or None
    row.synonyms = [s.strip() for s in (payload.synonyms or []) if s.strip()][:20]
    await db.flush()
    return TermOut(
        id=row.id, term=row.term, definition=row.definition, column_ref=row.column_ref,
        synonyms=row.synonyms or [], source=row.source, use_count=row.use_count or 0,
        created_at=row.created_at,
    )


@router.delete("/data-sources/{sid}/terms/{tid}")
async def delete_term(
    sid: str,
    tid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    row = await db.get(DsSemanticTerm, tid)
    if not row or row.data_source_id != str(sid):
        raise HTTPException(status_code=404, detail="术语不存在")
    await db.delete(row)
    return {"deleted": True}


# ────────────────────── 指标口径 CRUD ──────────────────────

@router.get("/data-sources/{sid}/metrics", response_model=list[MetricOut])
async def list_metrics(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    res = await db.execute(
        select(DsSemanticMetric)
        .where(DsSemanticMetric.data_source_id == str(sid))
        .order_by(DsSemanticMetric.created_at.desc())
    )
    return [
        MetricOut(
            id=m.id, name=m.name, expr=m.expr, dimensions=m.dimensions or [],
            default_filters=m.default_filters or [], description=m.description,
            source=m.source, use_count=m.use_count or 0, created_at=m.created_at,
        )
        for m in res.scalars().all()
    ]


@router.post("/data-sources/{sid}/metrics", response_model=MetricOut)
async def create_metric(
    sid: str,
    payload: MetricIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    row = DsSemanticMetric(
        data_source_id=str(sid), name=payload.name.strip(), expr=payload.expr.strip(),
        dimensions=[d.strip() for d in (payload.dimensions or []) if d.strip()][:20],
        default_filters=[f.strip() for f in (payload.default_filters or []) if f.strip()][:20],
        description=(payload.description or "").strip() or None, source="manual",
    )
    db.add(row)
    await db.flush()
    return MetricOut(
        id=row.id, name=row.name, expr=row.expr, dimensions=row.dimensions or [],
        default_filters=row.default_filters or [], description=row.description,
        source=row.source, use_count=0, created_at=row.created_at,
    )


@router.put("/data-sources/{sid}/metrics/{mid}", response_model=MetricOut)
async def update_metric(
    sid: str,
    mid: str,
    payload: MetricIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    row = await db.get(DsSemanticMetric, mid)
    if not row or row.data_source_id != str(sid):
        raise HTTPException(status_code=404, detail="指标不存在")
    row.name = payload.name.strip()
    row.expr = payload.expr.strip()
    row.dimensions = [d.strip() for d in (payload.dimensions or []) if d.strip()][:20]
    row.default_filters = [f.strip() for f in (payload.default_filters or []) if f.strip()][:20]
    row.description = (payload.description or "").strip() or None
    await db.flush()
    return MetricOut(
        id=row.id, name=row.name, expr=row.expr, dimensions=row.dimensions or [],
        default_filters=row.default_filters or [], description=row.description,
        source=row.source, use_count=row.use_count or 0, created_at=row.created_at,
    )


@router.delete("/data-sources/{sid}/metrics/{mid}")
async def delete_metric(
    sid: str,
    mid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    row = await db.get(DsSemanticMetric, mid)
    if not row or row.data_source_id != str(sid):
        raise HTTPException(status_code=404, detail="指标不存在")
    await db.delete(row)
    return {"deleted": True}


# ────────────────────── 问数反馈 ──────────────────────

@router.post("/data-ask/feedback", response_model=FeedbackOut)
async def submit_feedback(
    payload: FeedbackIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ftype = (payload.feedback_type or "").strip().lower()
    if ftype not in _FEEDBACK_TYPES:
        raise HTTPException(status_code=400, detail=f"feedback_type 必须是 {'/'.join(_FEEDBACK_TYPES)}")
    source = await _get_source(db, payload.data_source_id)
    await assert_data_source_access(db, source, user)

    question = (payload.question or "").strip()
    original_sql = (payload.original_sql or "").strip()
    corrected_sql = (payload.corrected_sql or "").strip()

    # 从 trace 回填问题与原 SQL（前端只传 trace_id 时也能闭环）
    if payload.trace_id and (not question or not original_sql):
        trace = await db.get(AskTrace, payload.trace_id)
        if trace and trace.data_source_id == str(source.id):
            question = question or (trace.question or "")
            original_sql = original_sql or (trace.sql_text or "")

    if ftype in ("correction", "example"):
        sql_to_save = corrected_sql or original_sql
        if not sql_to_save:
            raise HTTPException(status_code=400, detail="纠正 / 保存示例需要提供 SQL")
        if not _is_select(sql_to_save):
            raise HTTPException(status_code=400, detail="仅支持 SELECT 查询写入示例库")
        if not question:
            raise HTTPException(status_code=400, detail="缺少问题文本，无法保存示例")

    row = AskFeedback(
        trace_id=payload.trace_id, data_source_id=str(source.id), user_id=str(user.id),
        question=question or None, original_sql=original_sql or None,
        corrected_sql=corrected_sql or None, feedback_type=ftype,
        comment=(payload.comment or "")[:2000] or None,
    )
    db.add(row)
    await db.flush()

    # P2 归因链回填：本次反馈对记忆命中的采纳判定（like/correction/example=采纳，dislike=未采纳）
    try:
        if payload.trace_id:
            from sqlalchemy import update as _sa_update

            from app.db.models import MemoryHitLog

            await db.execute(
                _sa_update(MemoryHitLog)
                .where(
                    MemoryHitLog.trace_id == int(payload.trace_id),
                    MemoryHitLog.adopted.is_(None),
                )
                .values(adopted=(ftype != "dislike"))
            )
    except Exception:
        pass

    train_task = DataAskTrainTask(
        data_source_id=str(source.id), user_id=str(user.id), kind="example",
        status="queued", progress=0, feedback_id=row.id,
        detail={"feedback_type": ftype, "question": question or None},
    )
    db.add(train_task)
    await db.flush()

    saved = False
    if ftype in ("correction", "example"):
        await save_golden_query(
            db, data_source_id=str(source.id), question=question,
            sql_text=corrected_sql or original_sql, user_id=str(user.id),
        )
        saved = True

    if ftype in ("like", "dislike", "correction", "example"):
        try:
            from app.core.data_ask.distill_tasks import distill_examples_task

            distill_examples_task.delay(str(source.id), task_id=train_task.id)
        except Exception as exc:
            train_task.status = "failed"
            train_task.error = str(exc)[:1000]
            await db.commit()

    return FeedbackOut(
        id=row.id, saved_example=saved,
        message="反馈已保存" + ("，示例已加入问数记忆" if saved else ""),
        task_id=train_task.id,
    )


# ────────────────────── 对话内训练任务状态 ──────────────────────

@router.get("/data-ask/train/tasks/{task_id}", response_model=TrainTaskOut)
async def get_train_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await db.get(DataAskTrainTask, task_id)
    if not row:
        raise HTTPException(status_code=404, detail="训练任务不存在")
    source = await _get_source(db, row.data_source_id)
    await assert_data_source_access(db, source, user)
    return TrainTaskOut(
        id=row.id, data_source_id=row.data_source_id, kind=row.kind, status=row.status,
        progress=row.progress or 0, detail=row.detail, feedback_id=row.feedback_id,
        error=row.error, created_at=row.created_at, updated_at=row.updated_at,
    )


# ────────────────────── 问数轨迹 ──────────────────────

@router.get("/data-ask/traces", response_model=list[TraceOut])
async def list_traces(
    data_source_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, data_source_id)
    await assert_data_source_access(db, source, user)
    res = await db.execute(
        select(AskTrace)
        .where(AskTrace.data_source_id == str(data_source_id))
        .order_by(AskTrace.id.desc())
        .limit(limit)
    )
    return [
        TraceOut(
            id=t.id, data_source_id=t.data_source_id, user_id=t.user_id,
            question=t.question, standalone_question=t.standalone_question,
            sql_text=t.sql_text, row_count=t.row_count, success=t.success,
            error_message=t.error_message, analysis_mode=t.analysis_mode,
            memory_hits=t.memory_hits or 0, duration_ms=t.duration_ms,
            rewrite_ms=t.rewrite_ms, gen_ms=t.gen_ms, exec_ms=t.exec_ms,
            analysis_ms=t.analysis_ms, result_signature=t.result_signature,
            clarification=bool(t.clarification), cached=bool(t.cached),
            created_at=t.created_at,
        )
        for t in res.scalars().all()
    ]
