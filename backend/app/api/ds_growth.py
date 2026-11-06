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
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_user
from app.core.data_ask.govern.access import assert_data_source_access
from app.core.data_ask.intelligence.query_memory import save_golden_query
from app.db.models import (
    AskExample,
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
    AnswerModeStatsOut,
    FeedbackIn,
    FeedbackOut,
    FeedbackStatOut,
    MetricIn,
    MetricOut,
    ModeStatOut,
    ProfileBuildOut,
    ProfileOut,
    ProfileStatusOut,
    TermIn,
    TermOut,
    TopQuestionOut,
    TraceOut,
    TrainTaskOut,
)
from app.schemas.train_center import FeedbackStatusOut, FeedbackStepOut

router = APIRouter(tags=["DsGrowth"])

_EXCEL_DRIVERS = ("excel_folder", "excel_template")
_FEEDBACK_TYPES = ("like", "dislike", "correction", "example", "verbose")


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
            updated = r.updated_at or r.created_at
            if updated is not None and updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if updated is not None and datetime.now(timezone.utc) - updated < timedelta(minutes=30):
                return ProfileBuildOut(
                    profile_id=r.id, version=r.version, status="building",
                    message="画像正在构建中，请稍后查看状态",
                )
            r.status = "failed"
            r.error = "构建超过 30 分钟仍未完成，已重新发起"
            await db.flush()
    next_version = (rows[0].version + 1) if rows else 1
    row = DsSchemaProfile(
        data_source_id=str(sid), version=next_version, status="building", trigger="manual",
    )
    db.add(row)
    await db.flush()
    await db.commit()

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
    trace = None
    if payload.trace_id:
        trace = await db.get(AskTrace, payload.trace_id)
        if trace and trace.data_source_id != str(source.id):
            trace = None
        elif trace and (not question or not original_sql):
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
                .values(adopted=(ftype not in ("dislike", "verbose")))
            )
    except Exception:
        pass

    train_task = None
    if ftype in ("like", "dislike", "correction", "example"):
        train_task = DataAskTrainTask(
            data_source_id=str(source.id), user_id=str(user.id), kind="example",
            status="queued", progress=0, feedback_id=row.id,
            detail={"feedback_type": ftype, "question": question or None},
        )
        db.add(train_task)
        await db.flush()

    saved = False
    if ftype in ("correction", "example"):
        # 仅纠错可覆盖金标口径；"保存示例"只在无金标时补建，避免弱信号回刷旧 SQL
        await save_golden_query(
            db, data_source_id=str(source.id), question=question,
            sql_text=corrected_sql or original_sql, user_id=str(user.id),
            overwrite=(ftype == "correction"),
        )
        saved = True

    # 蓝图 P1-③：点赞 / 采纳写入命中技能的专属示例（无技能或无 SQL 则跳过）
    if ftype in ("like", "example", "correction") and trace is not None and trace.skill_id:
        sql_for_skill = (corrected_sql or original_sql or "").strip()
        first_stmt = sql_for_skill.split(";")[0].strip()
        if question and first_stmt and _is_select(first_stmt):
            try:
                from app.core.data_ask.skill_memory import save_skill_example

                mem = await save_skill_example(
                    db,
                    data_source_id=str(source.id),
                    skill_id=str(trace.skill_id),
                    question=question,
                    sql_text=sql_for_skill,
                    source=ftype,
                    trace_id=int(trace.id) if trace.id is not None else None,
                    note=(payload.comment or "")[:200] or None,
                )
                if mem.get("saved") or mem.get("deduped"):
                    saved = True
            except Exception:
                pass

    if ftype in ("like", "dislike", "correction", "example"):
        try:
            from app.core.cache.redis_cache import cache_delete_prefix

            # 训练反馈改变问答口径：使问数结果缓存失效，重复提问立即走新记忆
            deleted = await cache_delete_prefix("dataask:cache:")
            if train_task is not None:
                train_task.detail = {**(train_task.detail or {}), "cache_invalidated": deleted}
        except Exception:
            pass
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
        task_id=train_task.id if train_task else None,
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


# ────────────────────── 反馈训练状态回执（P1：已入队 / 已蒸馏 / 已生效） ──────────────────────

async def _feedback_status(db: AsyncSession, row: AskFeedback) -> FeedbackStatusOut:
    task = (
        await db.execute(
            select(DataAskTrainTask)
            .where(DataAskTrainTask.feedback_id == row.id)
            .order_by(DataAskTrainTask.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    example = None
    if row.trace_id:
        example = (
            await db.execute(
                select(AskExample)
                .where(
                    AskExample.data_source_id == row.data_source_id,
                    AskExample.trace_id == row.trace_id,
                    AskExample.active.is_(True),
                )
                .order_by(AskExample.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if example is None and row.question:
        example = (
            await db.execute(
                select(AskExample)
                .where(
                    AskExample.data_source_id == row.data_source_id,
                    AskExample.question == row.question,
                    AskExample.active.is_(True),
                )
                .order_by(AskExample.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    queued = bool(task is not None)
    distilled = bool((task is not None and task.status == "done") or example is not None)
    effective = bool(example is not None and example.active and example.indexed)
    if effective:
        message = "已生效：示例已向量化，可被后续问数命中"
    elif distilled:
        message = "已蒸馏：示例已写入知识记忆，等待向量化生效"
    elif queued:
        message = "已入队：等待蒸馏作业执行"
    else:
        message = "未入队：本次反馈不触发训练"
    return FeedbackStatusOut(
        feedback_id=int(row.id),
        data_source_id=row.data_source_id,
        question=row.question,
        feedback_type=row.feedback_type,
        task_id=int(task.id) if task is not None else None,
        task_status=task.status if task is not None else None,
        queued=queued,
        distilled=distilled,
        effective=effective,
        example_id=example.id if example is not None else None,
        example_indexed=bool(example.indexed) if example is not None else False,
        steps=[
            FeedbackStepOut(key="queued", label="已入队", done=queued),
            FeedbackStepOut(key="distilled", label="已蒸馏", done=distilled),
            FeedbackStepOut(key="effective", label="已生效", done=effective),
        ],
        message=message,
        created_at=row.created_at,
    )


@router.get("/data-ask/feedback/{fid}/status", response_model=FeedbackStatusOut)
async def get_feedback_status(
    fid: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await db.get(AskFeedback, int(fid))
    if not row:
        raise HTTPException(status_code=404, detail="反馈不存在")
    source = await _get_source(db, row.data_source_id)
    await assert_data_source_access(db, source, user)
    return await _feedback_status(db, row)


@router.get("/data-ask/feedback/recent", response_model=list[FeedbackStatusOut])
async def list_recent_feedback(
    data_source_id: str = Query(...),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, data_source_id)
    await assert_data_source_access(db, source, user)
    rows = (
        await db.execute(
            select(AskFeedback)
            .where(AskFeedback.data_source_id == str(source.id))
            .order_by(AskFeedback.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [await _feedback_status(db, r) for r in rows]


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
            answer_mode=t.answer_mode, memory_hits=t.memory_hits or 0, duration_ms=t.duration_ms,
            rewrite_ms=t.rewrite_ms, gen_ms=t.gen_ms, exec_ms=t.exec_ms,
            analysis_ms=t.analysis_ms, result_signature=t.result_signature,
            clarification=bool(t.clarification), cached=bool(t.cached),
            created_at=t.created_at,
        )
        for t in res.scalars().all()
    ]


# ────────────────────── 回答模式观测 ──────────────────────

@router.get("/data-sources/{sid}/answer-mode-stats", response_model=AnswerModeStatsOut)
async def answer_mode_stats(
    sid: str,
    days: int = Query(14, ge=1, le=180),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """L1/L2/L3 分布 + 反馈构成 + 高频问句（支撑词表修订与冗长反馈评估）。"""
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    mode_rows = (
        await db.execute(
            select(AskTrace.answer_mode, func.count())
            .where(
                AskTrace.data_source_id == str(sid),
                AskTrace.created_at >= since,
                AskTrace.answer_mode.isnot(None),
                AskTrace.success.is_(True),
            )
            .group_by(AskTrace.answer_mode)
        )
    ).all()
    total = sum(int(n) for _, n in mode_rows)
    modes = [
        ModeStatOut(
            answer_mode=str(mode or "?"),
            count=int(n),
            ratio=round(int(n) / total * 100, 1) if total else 0.0,
        )
        for mode, n in sorted(mode_rows, key=lambda x: str(x[0] or ""))
    ]

    fb_rows = (
        await db.execute(
            select(AskFeedback.feedback_type, func.count())
            .where(AskFeedback.data_source_id == str(sid), AskFeedback.created_at >= since)
            .group_by(AskFeedback.feedback_type)
        )
    ).all()
    feedback = [
        FeedbackStatOut(feedback_type=str(ftype or ""), count=int(n))
        for ftype, n in sorted(fb_rows, key=lambda x: str(x[0] or ""))
    ]

    q_rows = (
        await db.execute(
            select(AskTrace.question, func.count().label("n"))
            .where(
                AskTrace.data_source_id == str(sid),
                AskTrace.created_at >= since,
                AskTrace.question.isnot(None),
                AskTrace.success.is_(True),
            )
            .group_by(AskTrace.question)
            .order_by(func.count().desc())
            .limit(15)
        )
    ).all()
    top_questions = [
        TopQuestionOut(question=str(q or "")[:200], count=int(n)) for q, n in q_rows
    ]

    return AnswerModeStatsOut(
        days=days, total=total, modes=modes, feedback=feedback, top_questions=top_questions,
    )
