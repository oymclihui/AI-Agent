"""训练度量计算（P1）——API 实时口径与 Celery 日物化共用同一函数，保证一致。

指标定义（均可用一条 SQL 复算）：
- 反馈采纳率 adoption_rate = (correction + example 反馈数) / 反馈总数
- 金标净增 golden_net_add = 窗口内 data_ask_golden_queries.created_at 落窗条数
- 首次正确率 first_pass_rate = (轨迹总数 - 被纠正轨迹数 - 失败轨迹数) / 轨迹总数
  （被纠正 = ask_feedback.feedback_type='correction' 且 trace_id 非空关联的轨迹）
- 记忆命中率 memory_hit_rate = ask_trace.memory_hits > 0 的轨迹占比
- 评测通过率 eval_pass_rate = 最近一次 done 的 AgentEvalRun: passed / total
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AgentEvalRun,
    AskFeedback,
    AskTrace,
    DataAskGoldenQuery,
)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    return datetime.combine(day, time.min), datetime.combine(day + timedelta(days=1), time.min)


async def corrected_trace_ids(db: AsyncSession, ds: str, start: datetime, end: datetime) -> set[int]:
    res = await db.execute(
        select(AskFeedback.trace_id)
        .where(
            AskFeedback.data_source_id == ds,
            AskFeedback.feedback_type == "correction",
            AskFeedback.trace_id.isnot(None),
            AskFeedback.created_at >= start,
            AskFeedback.created_at < end,
        )
    )
    return {int(t) for (t,) in res.all()}


async def compute_day(db: AsyncSession, ds: str, day: date) -> dict[str, Any]:
    """单日指标（UTC 建库时间为准；与看板实时口径共用本函数）。"""
    start, end = _day_bounds(day)

    fb_counts = {"like": 0, "dislike": 0, "correction": 0, "example": 0}
    res = await db.execute(
        select(AskFeedback.feedback_type, func.count())
        .where(AskFeedback.data_source_id == ds, AskFeedback.created_at >= start, AskFeedback.created_at < end)
        .group_by(AskFeedback.feedback_type)
    )
    for ftype, cnt in res.all():
        fb_counts[str(ftype)] = int(cnt)
    feedback_total = sum(fb_counts.values())

    golden_created = int(
        (
            await db.execute(
                select(func.count())
                .select_from(DataAskGoldenQuery)
                .where(
                    DataAskGoldenQuery.data_source_id == ds,
                    DataAskGoldenQuery.created_at >= start,
                    DataAskGoldenQuery.created_at < end,
                )
            )
        ).scalar() or 0
    )

    trace_total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AskTrace)
                .where(AskTrace.data_source_id == ds, AskTrace.created_at >= start, AskTrace.created_at < end)
            )
        ).scalar() or 0
    )
    trace_success = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AskTrace)
                .where(
                    AskTrace.data_source_id == ds,
                    AskTrace.created_at >= start,
                    AskTrace.created_at < end,
                    AskTrace.success.is_(True),
                )
            )
        ).scalar() or 0
    )
    memory_hits = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AskTrace)
                .where(
                    AskTrace.data_source_id == ds,
                    AskTrace.created_at >= start,
                    AskTrace.created_at < end,
                    AskTrace.memory_hits > 0,
                )
            )
        ).scalar() or 0
    )

    corrected = await corrected_trace_ids(db, ds, start, end)
    failed = trace_total - trace_success
    first_pass = None
    if trace_total > 0:
        first_pass = round(max(trace_total - len(corrected) - failed, 0) / trace_total, 4)

    eval_pass = None
    eval_overall = None
    if trace_total > 0 or feedback_total > 0 or golden_created > 0:
        pass  # 评测按 run.created_at 归日，见下方 _eval_for_day
    res = await db.execute(
        select(AgentEvalRun)
        .where(
            AgentEvalRun.data_source_id == ds,
            AgentEvalRun.status == "done",
            AgentEvalRun.created_at >= start,
            AgentEvalRun.created_at < end,
        )
        .order_by(AgentEvalRun.created_at.desc())
        .limit(1)
    )
    run = res.scalar_one_or_none()
    if run and (run.total or 0) > 0:
        eval_pass = round((run.passed or 0) / run.total, 4)
        eval_overall = float(run.overall_score) if run.overall_score is not None else None

    return {
        "day": day.isoformat(),
        "feedback_total": feedback_total,
        "feedback_like": fb_counts["like"],
        "feedback_dislike": fb_counts["dislike"],
        "feedback_correction": fb_counts["correction"],
        "feedback_example": fb_counts["example"],
        "golden_created": golden_created,
        "trace_total": trace_total,
        "trace_success": trace_success,
        "first_pass_rate": first_pass,
        "memory_hit_rate": round(memory_hits / trace_total, 4) if trace_total else None,
        "eval_pass_rate": eval_pass,
        "eval_overall": eval_overall,
    }


async def compute_window_kpi(db: AsyncSession, ds: str, days: int) -> dict[str, Any]:
    """窗口 KPI（实时直算，可与 series 复算核对）。"""
    end = datetime.utcnow()
    start = end - timedelta(days=days)

    fb_counts = {"like": 0, "dislike": 0, "correction": 0, "example": 0}
    res = await db.execute(
        select(AskFeedback.feedback_type, func.count())
        .where(AskFeedback.data_source_id == ds, AskFeedback.created_at >= start)
        .group_by(AskFeedback.feedback_type)
    )
    for ftype, cnt in res.all():
        fb_counts[str(ftype)] = int(cnt)
    feedback_total = sum(fb_counts.values())

    golden_total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(DataAskGoldenQuery)
                .where(DataAskGoldenQuery.data_source_id == ds)
            )
        ).scalar() or 0
    )
    golden_net_add = int(
        (
            await db.execute(
                select(func.count())
                .select_from(DataAskGoldenQuery)
                .where(
                    DataAskGoldenQuery.data_source_id == ds,
                    DataAskGoldenQuery.created_at >= start,
                )
            )
        ).scalar() or 0
    )

    trace_total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AskTrace)
                .where(AskTrace.data_source_id == ds, AskTrace.created_at >= start)
            )
        ).scalar() or 0
    )
    trace_success = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AskTrace)
                .where(
                    AskTrace.data_source_id == ds,
                    AskTrace.created_at >= start,
                    AskTrace.success.is_(True),
                )
            )
        ).scalar() or 0
    )
    memory_hits = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AskTrace)
                .where(
                    AskTrace.data_source_id == ds,
                    AskTrace.created_at >= start,
                    AskTrace.memory_hits > 0,
                )
            )
        ).scalar() or 0
    )
    corrected = await corrected_trace_ids(db, ds, start, end)
    failed = trace_total - trace_success

    res = await db.execute(
        select(func.count(distinct(AgentEvalRun.id)))
        .where(AgentEvalRun.data_source_id == ds, AgentEvalRun.status == "done", AgentEvalRun.created_at >= start)
    )
    eval_runs = int(res.scalar() or 0)
    res = await db.execute(
        select(AgentEvalRun)
        .where(AgentEvalRun.data_source_id == ds, AgentEvalRun.status == "done")
        .order_by(AgentEvalRun.created_at.desc())
        .limit(1)
    )
    run = res.scalar_one_or_none()
    eval_pass = round((run.passed or 0) / run.total, 4) if run and (run.total or 0) > 0 else None
    eval_overall = float(run.overall_score) if run and run.overall_score is not None else None
    weak: list[str] = []
    if run and run.weak_categories:
        try:
            weak = [str(x) for x in run.weak_categories][:8]
        except Exception:
            weak = []

    return {
        "feedback_total": feedback_total,
        "feedback_like": fb_counts["like"],
        "feedback_dislike": fb_counts["dislike"],
        "feedback_correction": fb_counts["correction"],
        "feedback_example": fb_counts["example"],
        "adoption_rate": round((fb_counts["correction"] + fb_counts["example"]) / feedback_total, 4)
        if feedback_total
        else None,
        "golden_total": golden_total,
        "golden_net_add": golden_net_add,
        "trace_total": trace_total,
        "trace_success": trace_success,
        "first_pass_rate": round(max(trace_total - len(corrected) - failed, 0) / trace_total, 4)
        if trace_total
        else None,
        "memory_hit_rate": round(memory_hits / trace_total, 4) if trace_total else None,
        "eval_runs": eval_runs,
        "eval_pass_rate": eval_pass,
        "eval_overall": eval_overall,
        "eval_weak": weak,
    }


async def materialize_day(db: AsyncSession, ds: str, day: date) -> bool:
    """物化单日一行（upsert by data_source_id + day）。返回是否有数据。"""
    from app.db.models import AgentMetricDaily

    vals = await compute_day(db, ds, day)
    has_data = any(
        vals[k] for k in (
            "feedback_total", "golden_created", "trace_total",
        )
    ) or vals["eval_pass_rate"] is not None
    if not has_data:
        return False
    res = await db.execute(
        select(AgentMetricDaily)
        .where(AgentMetricDaily.data_source_id == ds, AgentMetricDaily.day == day)
    )
    row = res.scalar_one_or_none()
    if not row:
        row = AgentMetricDaily(data_source_id=ds, day=day)
        db.add(row)
    for k in (
        "feedback_total", "feedback_like", "feedback_dislike", "feedback_correction",
        "feedback_example", "golden_created", "trace_total", "trace_success",
        "first_pass_rate", "memory_hit_rate", "eval_pass_rate", "eval_overall",
    ):
        setattr(row, k, vals[k])
    await db.flush()
    return True
