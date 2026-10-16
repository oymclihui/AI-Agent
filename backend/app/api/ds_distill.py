"""Agent Evolution 阶段二 API：知识蒸馏 —— 示例库 / 分析模板 / 业务规则。

- GET    /data-sources/{sid}/distill/stats       蒸馏概览统计
- GET    /data-sources/{sid}/examples            示例库列表（正/负例）
- POST   /data-sources/{sid}/examples/distill    从反馈蒸馏示例（Celery 异步）
- DELETE /examples/{eid}                         删除示例（含 Milvus 向量）
- GET    /data-sources/{sid}/templates           分析模板列表
- POST   /data-sources/{sid}/templates/mine      高频问题聚类挖掘模板（Celery 异步）
- PATCH  /templates/{tid}                        编辑 / 启用停用模板
- GET    /data-sources/{sid}/rules               业务规则列表
- POST   /data-sources/{sid}/rules/mine          纠错蒸馏业务规则（Celery 异步）
- PATCH  /rules/{rid}                            编辑规则
- POST   /rules/{rid}/activate                   生效并回写语义层
- POST   /rules/{rid}/reject                     驳回规则
- POST   /data-ask/train/preview                 纠错 SQL 试跑预览（限行只读）
- GET    /data-sources/{sid}/train/metrics       训练度量看板（KPI + 日趋势）
- POST   /data-sources/{sid}/train/metrics/materialize  物化/回补 agent_metric_daily
- POST   /data-sources/{sid}/shadow-compare      影子对比（未更新记忆 vs 已更新记忆，异步）
- GET    /data-sources/{sid}/attribution         效果归因报告（memory_hit_log + 评测前后对比）
- POST   /data-sources/{sid}/evolve              触发单源进化闭环：蒸馏 → 评测 → 晋升/回滚
- GET    /data-ask/train/events                  训练全链路 SSE（蒸馏/评测/晋升进度实时推送）
写操作需数据源 manage 权限。
"""
from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_user
from app.core.data_ask.govern.access import assert_data_source_access
from app.db.models import (
    Agent as AgentModel,
)
from app.db.models import (
    AgentEvalRun,
    AskExample,
    AskFeedback,
    AskTemplate,
    AskTrace,
    DataAskTrainTask,
    DataSource,
    DsBusinessRule,
    MemoryHitLog,
    User,
)
from app.db.session import get_db
from app.schemas.ds_distill import (
    AttributionOut,
    DistillOut,
    DistillStatsOut,
    EvolveOut,
    ExampleOut,
    MaterializeOut,
    RuleOut,
    RuleUpdateIn,
    ShadowCompareIn,
    TemplateOut,
    TemplateUpdateIn,
    TrainDayPoint,
    TrainKpiOut,
    TrainMetricsOut,
    TrainPreviewIn,
    TrainPreviewOut,
)

router = APIRouter(tags=["DsDistill"])


async def _get_source(db: AsyncSession, sid: str) -> DataSource:
    source = await db.get(DataSource, sid)
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return source


def _example_out(row: AskExample) -> ExampleOut:
    return ExampleOut(
        id=row.id, data_source_id=row.data_source_id, question=row.question,
        sql_text=row.sql_text, kind=row.kind, source=row.source,
        quality=float(row.quality or 0), trace_id=row.trace_id,
        use_count=row.use_count or 0, active=bool(row.active),
        indexed=bool(row.indexed), note=row.note, created_at=row.created_at,
    )


def _template_out(row: AskTemplate) -> TemplateOut:
    return TemplateOut(
        id=row.id, data_source_id=row.data_source_id, name=row.name,
        intent=row.intent, framework=row.framework,
        sample_questions=[str(q) for q in (row.sample_questions or [])],
        keywords=[str(k) for k in (row.keywords or [])],
        member_count=row.member_count or 0, hit_count=row.hit_count or 0,
        status=row.status, source=row.source, created_at=row.created_at,
    )


def _rule_out(row: DsBusinessRule) -> RuleOut:
    return RuleOut(
        id=row.id, data_source_id=row.data_source_id, rule_type=row.rule_type,
        name=row.name, rule_text=row.rule_text, applies_to=row.applies_to,
        payload=row.payload, evidence=row.evidence,
        confidence=float(row.confidence or 0), status=row.status,
        source=row.source, materialized_id=row.materialized_id, created_at=row.created_at,
    )


async def _count(db: AsyncSession, model, *where) -> int:
    res = await db.execute(select(func.count()).select_from(model).where(*where))
    return int(res.scalar() or 0)


# ────────────────────── 概览统计 ──────────────────────

@router.get("/data-sources/{sid}/distill/stats", response_model=DistillStatsOut)
async def distill_stats(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    ds = str(sid)
    return DistillStatsOut(
        data_source_id=ds,
        examples_positive=await _count(db, AskExample, AskExample.data_source_id == ds, AskExample.kind == "positive"),
        examples_negative=await _count(db, AskExample, AskExample.data_source_id == ds, AskExample.kind == "negative"),
        examples_indexed=await _count(db, AskExample, AskExample.data_source_id == ds, AskExample.indexed.is_(True)),
        templates_total=await _count(db, AskTemplate, AskTemplate.data_source_id == ds),
        templates_active=await _count(db, AskTemplate, AskTemplate.data_source_id == ds, AskTemplate.status == "active"),
        rules_total=await _count(db, DsBusinessRule, DsBusinessRule.data_source_id == ds),
        rules_active=await _count(db, DsBusinessRule, DsBusinessRule.data_source_id == ds, DsBusinessRule.status == "active"),
        traces_total=await _count(db, AskTrace, AskTrace.data_source_id == ds),
        feedback_total=await _count(db, AskFeedback, AskFeedback.data_source_id == ds),
    )


# ────────────────────── 示例库 ──────────────────────

@router.get("/data-sources/{sid}/examples", response_model=list[ExampleOut])
async def list_examples(
    sid: str,
    kind: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    stmt = select(AskExample).where(AskExample.data_source_id == str(sid))
    if kind in ("positive", "negative"):
        stmt = stmt.where(AskExample.kind == kind)
    stmt = stmt.order_by(AskExample.quality.desc(), AskExample.id.desc()).limit(limit)
    res = await db.execute(stmt)
    return [_example_out(row) for row in res.scalars().all()]


@router.post("/data-sources/{sid}/examples/distill", response_model=DistillOut)
async def distill_examples(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    from app.core.data_ask.distill_tasks import distill_examples_task

    distill_examples_task.delay(str(sid))
    return DistillOut(message="示例库蒸馏任务已启动，稍后刷新查看")


@router.delete("/examples/{eid}")
async def delete_example(
    eid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await db.get(AskExample, eid)
    if not row:
        raise HTTPException(status_code=404, detail="示例不存在")
    source = await _get_source(db, row.data_source_id)
    await assert_data_source_access(db, source, user, require_manage=True)
    ds, example_id = row.data_source_id, row.id
    await db.delete(row)
    await db.flush()
    if row.kind == "positive":
        try:
            from app.core.data_ask.distill import vector_index

            vector_index.delete_example(data_source_id=ds, example_id=example_id)
        except Exception:
            pass
    return {"ok": True}


# ────────────────────── 分析模板 ──────────────────────

@router.get("/data-sources/{sid}/templates", response_model=list[TemplateOut])
async def list_templates(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    res = await db.execute(
        select(AskTemplate)
        .where(AskTemplate.data_source_id == str(sid))
        .order_by(AskTemplate.status.desc(), AskTemplate.member_count.desc())
    )
    return [_template_out(row) for row in res.scalars().all()]


@router.post("/data-sources/{sid}/templates/mine", response_model=DistillOut)
async def mine_templates(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    from app.core.data_ask.distill_tasks import mine_templates_task

    mine_templates_task.delay(str(sid))
    return DistillOut(message="分析模板挖掘任务已启动，稍后刷新查看")


@router.patch("/templates/{tid}", response_model=TemplateOut)
async def update_template(
    tid: str,
    payload: TemplateUpdateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await db.get(AskTemplate, tid)
    if not row:
        raise HTTPException(status_code=404, detail="模板不存在")
    source = await _get_source(db, row.data_source_id)
    await assert_data_source_access(db, source, user, require_manage=True)
    if payload.name is not None:
        row.name = payload.name.strip()[:255]
    if payload.intent is not None:
        row.intent = payload.intent.strip()[:255] or None
    if payload.framework is not None:
        row.framework = payload.framework.strip() or None
    if payload.keywords is not None:
        row.keywords = [str(k).strip() for k in payload.keywords if str(k).strip()][:30]
    if payload.status is not None:
        if payload.status not in ("draft", "active"):
            raise HTTPException(status_code=400, detail="status 必须是 draft/active")
        row.status = payload.status
    await db.flush()
    return _template_out(row)


# ────────────────────── 业务规则 ──────────────────────

@router.get("/data-sources/{sid}/rules", response_model=list[RuleOut])
async def list_rules(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    res = await db.execute(
        select(DsBusinessRule)
        .where(DsBusinessRule.data_source_id == str(sid))
        .order_by(DsBusinessRule.status.desc(), DsBusinessRule.confidence.desc())
    )
    return [_rule_out(row) for row in res.scalars().all()]


@router.post("/data-sources/{sid}/rules/mine", response_model=DistillOut)
async def mine_rules(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    from app.core.data_ask.distill_tasks import mine_rules_task

    mine_rules_task.delay(str(sid))
    return DistillOut(message="业务规则蒸馏任务已启动，稍后刷新查看")


@router.patch("/rules/{rid}", response_model=RuleOut)
async def update_rule(
    rid: str,
    payload: RuleUpdateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await db.get(DsBusinessRule, rid)
    if not row:
        raise HTTPException(status_code=404, detail="规则不存在")
    source = await _get_source(db, row.data_source_id)
    await assert_data_source_access(db, source, user, require_manage=True)
    if payload.name is not None:
        row.name = payload.name.strip()[:255]
    if payload.rule_text is not None:
        row.rule_text = payload.rule_text.strip()
    if payload.applies_to is not None:
        row.applies_to = payload.applies_to.strip()[:255] or None
    if payload.payload is not None:
        row.payload = payload.payload
    await db.flush()
    return _rule_out(row)


@router.post("/rules/{rid}/activate", response_model=RuleOut)
async def activate_rule(
    rid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await db.get(DsBusinessRule, rid)
    if not row:
        raise HTTPException(status_code=404, detail="规则不存在")
    source = await _get_source(db, row.data_source_id)
    await assert_data_source_access(db, source, user, require_manage=True)
    from app.core.data_ask.distill.rule_miner import activate_rule as _activate

    await _activate(db, row)
    return _rule_out(row)


@router.post("/rules/{rid}/reject", response_model=RuleOut)
async def reject_rule(
    rid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await db.get(DsBusinessRule, rid)
    if not row:
        raise HTTPException(status_code=404, detail="规则不存在")
    source = await _get_source(db, row.data_source_id)
    await assert_data_source_access(db, source, user, require_manage=True)
    row.status = "rejected"
    await db.flush()
    return _rule_out(row)


# ────────────────────── P1：SQL 试跑预览 ──────────────────────

@router.post("/data-ask/train/preview", response_model=TrainPreviewOut)
async def train_preview(
    payload: TrainPreviewIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """纠错 SQL 试跑：仅允许单条 SELECT/WITH，限行只读执行，供纠错面板保存前确认结果。"""
    source = await _get_source(db, payload.data_source_id)
    await assert_data_source_access(db, source, user)

    sql = (payload.sql or "").strip().rstrip(";").strip()
    if not sql:
        raise HTTPException(status_code=400, detail="SQL 不能为空")
    lowered = sql.lstrip("(").strip().lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise HTTPException(status_code=400, detail="仅允许 SELECT / WITH 查询语句")
    for kw in (";", "--", "/*"):
        if kw in sql:
            raise HTTPException(status_code=400, detail=f"SQL 中不允许包含 {kw!r}")
    if any(k in lowered for k in ("insert ", "update ", "delete ", "drop ", "alter ", "truncate ", "grant ", "create ")):
        raise HTTPException(status_code=400, detail="仅允许只读查询语句")

    from app.core.data_ask.connectors.factory import build_connector_from_source

    conn = build_connector_from_source(source)
    t0 = _time.monotonic()
    try:
        qr = await conn.execute_select(sql, limit=payload.limit, timeout_s=25)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"试跑失败：{str(exc)[:400]}")
    finally:
        try:
            await conn.close()
        except Exception:
            pass
    cols = [str(c) for c in (qr.columns or [])]
    rows = [list(r) for r in (qr.rows or [])]
    return TrainPreviewOut(
        sql=sql,
        columns=cols,
        rows=rows,
        row_count=int(qr.row_count or len(rows)),
        truncated=bool(qr.truncated),
        duration_ms=int((_time.monotonic() - t0) * 1000),
    )


# ────────────────────── P1：训练度量看板 ──────────────────────

@router.get("/data-sources/{sid}/train/metrics", response_model=TrainMetricsOut)
async def train_metrics(
    sid: str,
    days: int = Query(default=30, ge=1, le=120),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """实时直算 KPI + 日趋势（与 agent_metric_daily 物化共用 compute_day，口径一致可复核）。"""
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)

    from app.core.data_ask.train_metrics import compute_day, compute_window_kpi

    kpi = await compute_window_kpi(db, str(sid), days)
    today = datetime.utcnow().date()
    series = []
    for i in range(days - 1, -1, -1):
        day_vals = await compute_day(db, str(sid), today - timedelta(days=i))
        series.append(TrainDayPoint(**day_vals))
    return TrainMetricsOut(data_source_id=str(sid), days=days, kpi=TrainKpiOut(**kpi), series=series)


@router.post("/data-sources/{sid}/train/metrics/materialize", response_model=MaterializeOut)
async def materialize_metrics(
    sid: str,
    days: int = Query(default=7, ge=1, le=120),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """回补最近 N 天的 agent_metric_daily（Celery 每日 03:10 自动物化前一日）。"""
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)

    from app.core.data_ask.train_metrics import materialize_day

    today = datetime.utcnow().date()
    upserted = 0
    for i in range(days - 1, -1, -1):
        if await materialize_day(db, str(sid), today - timedelta(days=i)):
            upserted += 1
    await db.commit()
    return MaterializeOut(message=f"已物化最近 {days} 天", day=today.isoformat(), upserted=upserted)


# ────────────── P2：影子对比 / 效果归因 / 自动晋升 / 训练 SSE ──────────────


@router.post("/data-sources/{sid}/shadow-compare")
async def shadow_compare(
    sid: str,
    payload: ShadowCompareIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """影子对比：同一问题分别用「未更新记忆 / 已更新记忆」生成（异步任务）。

    结果写入 data_ask_train_tasks(kind=shadow)，复用 GET /data-ask/train/tasks/{id} 轮询。
    """
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    question = payload.question.strip()
    task = DataAskTrainTask(
        data_source_id=str(source.id), user_id=str(user.id), kind="shadow",
        status="queued", progress=0, detail={"question": question},
    )
    db.add(task)
    await db.flush()
    try:
        from app.core.data_ask.distill_tasks import shadow_compare_task

        shadow_compare_task.delay(str(source.id), question, int(task.id))
    except Exception as exc:
        task.status = "failed"
        task.error = str(exc)[:1000]
    return {"task_id": int(task.id), "status": task.status, "message": "影子对比已启动"}


@router.get("/data-sources/{sid}/attribution", response_model=AttributionOut)
async def attribution(
    sid: str,
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """效果归因报告（P2 验收核心）：memory_hit_log 直算 + 评测通过率 before/after。

    结论可复算：命中/采纳计数来自 memory_hit_log；通过率来自 agent_eval_run
    最近两次 done 运行的 passed/total；每项均可用一条 SQL 直查复现。
    """
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    ds = str(source.id)
    since = datetime.utcnow() - timedelta(days=days)

    # 归属智能体与生产版本（训练能力下沉到智能体层级的可见性）
    agent_info: dict | None = None
    if source.agent_id:
        agent = await db.get(AgentModel, str(source.agent_id))
        if agent is not None:
            prod_v = None
            try:
                from app.core.data_ask.factory.versioning import active_version

                prod = await active_version(db, str(source.agent_id))
                prod_v = int(prod.version) if prod else None
            except Exception:
                prod_v = None
            agent_info = {
                "id": str(source.agent_id),
                "name": getattr(agent, "name", None),
                "production_version": prod_v,
            }

    # ── 记忆命中与采纳（memory_hit_log 直算）──
    base_where = [MemoryHitLog.data_source_id == ds, MemoryHitLog.created_at >= since]
    hit_total = int((await db.execute(
        select(func.count(MemoryHitLog.id)).where(*base_where)
    )).scalar() or 0)
    hit_traces = int((await db.execute(
        select(func.count(func.distinct(MemoryHitLog.trace_id))).where(*base_where)
    )).scalar() or 0)
    adopted_true = int((await db.execute(
        select(func.count(MemoryHitLog.id)).where(*base_where, MemoryHitLog.adopted.is_(True))
    )).scalar() or 0)
    adopted_false = int((await db.execute(
        select(func.count(MemoryHitLog.id)).where(*base_where, MemoryHitLog.adopted.is_(False))
    )).scalar() or 0)
    judged = adopted_true + adopted_false
    adopt_rate = round(adopted_true / judged, 4) if judged else None

    # 采纳证据明细（最近 20 条已判定命中，附反馈类型）
    evidence: list[dict] = []
    ev_rows = (
        await db.execute(
            select(MemoryHitLog)
            .where(*base_where, MemoryHitLog.adopted.is_not(None))
            .order_by(MemoryHitLog.id.desc())
            .limit(20)
        )
    ).scalars().all()
    trace_ids = [int(r.trace_id) for r in ev_rows if r.trace_id]
    fb_map: dict[int, str] = {}
    if trace_ids:
        fb_rows = (
            await db.execute(
                select(AskFeedback.trace_id, AskFeedback.feedback_type)
                .where(AskFeedback.trace_id.in_(trace_ids), AskFeedback.data_source_id == ds)
                .order_by(AskFeedback.id.desc())
            )
        ).all()
        for tid, ftype in fb_rows:
            fb_map.setdefault(int(tid), str(ftype or ""))
    for r in ev_rows:
        matched = r.matched if isinstance(r.matched, list) else []
        top = matched[0] if matched else {}
        evidence.append({
            "trace_id": r.trace_id,
            "question": (r.question or "")[:120],
            "ref": str(top.get("ref") or ""),
            "ref_type": str(top.get("ref_type") or ""),
            "ref_question": str(top.get("question") or "")[:120],
            "score": float(top.get("score") or 0),
            "match_score": float(r.match_score or 0),
            "adopted": bool(r.adopted),
            "feedback_type": fb_map.get(int(r.trace_id), ""),
        })

    # ── 评测通过率 before / after（最近两次 done 运行）──
    runs = (
        await db.execute(
            select(AgentEvalRun)
            .where(AgentEvalRun.data_source_id == ds, AgentEvalRun.status == "done", AgentEvalRun.total > 0)
            .order_by(AgentEvalRun.id.desc())
            .limit(2)
        )
    ).scalars().all()
    eval_info: dict = {"has_comparison": False}
    before_r = runs[1] if len(runs) >= 2 else None
    after_r = runs[0] if runs else None

    def _pr(row) -> float | None:
        if row is None or not row.total:
            return None
        return round(float(row.passed or 0) / float(row.total), 4)

    after_pr = _pr(after_r)
    before_pr = _pr(before_r)
    if after_r is not None:
        eval_info = {
            "has_comparison": before_r is not None,
            "after_run_id": int(after_r.id),
            "after_pass_rate": after_pr,
            "after_overall": float(after_r.overall_score) if after_r.overall_score is not None else None,
            "after_at": after_r.created_at.isoformat() if after_r.created_at else None,
            "before_run_id": int(before_r.id) if before_r else None,
            "before_pass_rate": before_pr,
            "before_overall": float(before_r.overall_score) if before_r and before_r.overall_score is not None else None,
            "before_at": before_r.created_at.isoformat() if before_r and before_r.created_at else None,
            "delta_pp": (round((after_pr - before_pr) * 100, 2) if (after_pr is not None and before_pr is not None) else None),
        }

    # ── 可复算结论 ──
    parts: list[str] = []
    parts.append(f"近 {days} 天问数命中问数记忆 {hit_total} 次（涉及 {hit_traces} 轮问答）")
    if judged:
        parts.append(f"其中被用户采纳 {adopted_true} 次、点踩 {adopted_false} 次（采纳率 {round(adopt_rate * 100, 1)}%）")
    else:
        parts.append("尚无用户对命中记忆的采纳反馈")
    if eval_info.get("has_comparison"):
        d = eval_info["delta_pp"]
        arrow = "提升" if d > 0 else ("下降" if d < 0 else "持平")
        parts.append(
            f"本轮训练后回归评测通过率由 {round(before_pr * 100, 1)}% 变为 {round(after_pr * 100, 1)}%"
            f"（{arrow} {abs(d)} 个百分点）"
        )
    elif after_r is not None:
        parts.append(f"最近一轮评测通过率 {round((after_pr or 0) * 100, 1)}%（暂无前一轮可比）")
    else:
        parts.append("暂无已完成的回归评测")
    conclusion = "；".join(parts) + "。"

    return AttributionOut(
        data_source_id=ds, days=days, agent=agent_info,
        memory={
            "hit_total": hit_total,
            "hit_traces": hit_traces,
            "adopted_true": adopted_true,
            "adopted_false": adopted_false,
            "pending": max(hit_total - judged, 0),
            "adopt_rate": adopt_rate,
        },
        adoption_evidence=evidence,
        eval=eval_info,
        conclusion=conclusion,
    )


@router.post("/data-sources/{sid}/evolve", response_model=EvolveOut)
async def evolve_source(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """手动触发单源进化闭环：蒸馏 → 考题库 → 候选版本 → 回归评测 → 晋升/回滚（异步）。"""
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    task = DataAskTrainTask(
        data_source_id=str(source.id), user_id=str(user.id), kind="promote",
        status="queued", progress=0, detail={"trigger": "manual"},
    )
    db.add(task)
    await db.flush()
    try:
        from app.core.data_ask.distill_tasks import evolve_source_task

        evolve_source_task.delay(str(source.id), int(task.id))
    except Exception as exc:
        task.status = "failed"
        task.error = str(exc)[:1000]
    return EvolveOut(
        message="进化闭环已启动：蒸馏 → 评测 → 晋升/回滚",
        task_id=int(task.id),
    )


@router.get("/data-ask/train/events")
async def train_events(
    request: Request,
    sid: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """训练全链路 SSE：蒸馏 / 影子对比 / 评测 / 晋升任务 + 最近评测运行，2s 快照流。"""
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    ds = str(source.id)

    import asyncio
    import json as _json

    from fastapi.responses import StreamingResponse

    async def _gen():
        last_sig: str | None = None
        tick = 0
        while True:
            try:
                if request is not None and await request.is_disconnected():
                    break
                db.expire_all()
                tasks = (
                    await db.execute(
                        select(DataAskTrainTask)
                        .where(DataAskTrainTask.data_source_id == ds)
                        .order_by(DataAskTrainTask.id.desc())
                        .limit(8)
                    )
                ).scalars().all()
                runs = (
                    await db.execute(
                        select(AgentEvalRun)
                        .where(AgentEvalRun.data_source_id == ds)
                        .order_by(AgentEvalRun.id.desc())
                        .limit(3)
                    )
                ).scalars().all()
                snap = {
                    "event": "snapshot",
                    "data_source_id": ds,
                    "tasks": [
                        {
                            "id": t.id, "kind": t.kind, "status": t.status,
                            "progress": t.progress or 0, "detail": t.detail,
                            "error": t.error,
                            "created_at": t.created_at.isoformat() if t.created_at else None,
                        }
                        for t in tasks
                    ],
                    "eval_runs": [
                        {
                            "id": r.id, "trigger": r.trigger, "status": r.status,
                            "total": r.total, "passed": r.passed,
                            "overall_score": r.overall_score,
                            "created_at": r.created_at.isoformat() if r.created_at else None,
                        }
                        for r in runs
                    ],
                }
                sig = _json.dumps(snap, sort_keys=True, ensure_ascii=False, default=str)
                if sig != last_sig:
                    last_sig = sig
                    yield f"data: {_json.dumps(snap, ensure_ascii=False, default=str)}\n\n"
                elif tick % 10 == 0:
                    yield ": ping\n\n"
                tick += 1
            except asyncio.CancelledError:
                break
            except Exception:
                logging.getLogger("ds_distill").exception("train_events_snapshot_failed")
                yield ": err\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        _gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
