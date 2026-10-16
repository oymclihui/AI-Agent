"""主动学习缺口推荐：真实问数类目录 × 考题库覆盖 → 补题方向。

数据真实性红线：
- 覆盖统计只来自真实问数轨迹（ask_trace）与真实考题库（agent_eval_set）。
- sample_metrics 仅取语义层已沉淀的真实指标名（ds_semantic_metric），作为人工补题参考，
  绝不自动合成考题入库；无指标沉淀时返回空列表。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.evaluation.categories import CANONICAL_CATEGORIES, classify_question
from app.db.models import AgentEvalSet, AskTrace, DataSource, DsSemanticMetric

logger = logging.getLogger("agent_eval_gaps")

_WINDOW_DAYS = 90


async def coverage_gaps(db: AsyncSession, source: DataSource) -> dict[str, Any]:
    """六大基础类目覆盖巡检：用户在问但考题库没覆盖 = eval_gap；都没碰过 = unexplored。"""
    ds = str(source.id)
    since = datetime.now(timezone.utc) - timedelta(days=_WINDOW_DAYS)

    # 真实问数轨迹的类目分布（仅统计成功问答，user_id 非空 = 真实用户，排除任何系统流量）
    trace_rows = (
        await db.execute(
            select(AskTrace.question)
            .where(
                AskTrace.data_source_id == ds,
                AskTrace.success.is_(True),
                AskTrace.question.isnot(None),
                AskTrace.user_id.isnot(None),
                AskTrace.created_at >= since,
            )
            .order_by(AskTrace.id.desc())
            .limit(1000)
        )
    ).scalars().all()
    trace_cats: dict[str, int] = {}
    for question in trace_rows:
        cat = classify_question(question or "")
        trace_cats[cat] = trace_cats.get(cat, 0) + 1

    # 考题库类目分布
    eval_rows = (
        await db.execute(
            select(AgentEvalSet.category, func.count())
            .where(AgentEvalSet.data_source_id == ds, AgentEvalSet.active.is_(True))
            .group_by(AgentEvalSet.category)
        )
    ).all()
    eval_cats: dict[str, int] = {str(c): int(n) for c, n in eval_rows}

    # 语义层真实指标名（人工补题参考素材）
    metric_names = (
        await db.execute(
            select(DsSemanticMetric.name)
            .where(DsSemanticMetric.data_source_id == ds)
            .order_by(DsSemanticMetric.use_count.desc(), DsSemanticMetric.created_at.desc())
            .limit(20)
        )
    ).scalars().all()
    metrics = [str(m) for m in metric_names if m]

    categories: list[dict[str, Any]] = []
    for cat in CANONICAL_CATEGORIES:
        trace_n = trace_cats.get(cat, 0)
        eval_n = eval_cats.get(cat, 0)
        if eval_n > 0:
            status = "covered"
        elif trace_n > 0:
            status = "eval_gap"      # 用户在问，考题库没覆盖 → 优先补题
        else:
            status = "unexplored"    # 还没问过也没考题 → 业务待探索
        categories.append({
            "category": cat,
            "trace_count": trace_n,
            "eval_count": eval_n,
            "status": status,
            "sample_metrics": metrics[:5] if status != "covered" else [],
        })
    # 缺口排前，其次按真实问数热度
    rank = {"eval_gap": 0, "unexplored": 1, "covered": 2}
    categories.sort(key=lambda c: (rank[c["status"]], -c["trace_count"]))

    eval_set_size = sum(eval_cats.values())
    suggestions: list[str] = []
    gap_cats = [c for c in categories if c["status"] == "eval_gap"]
    if gap_cats:
        suggestions.append(
            f"{len(gap_cats)} 类问题用户常问但考题库未覆盖，请通过问数反馈或手工补题补齐"
        )
    if eval_set_size < 5:
        suggestions.append(f"考题库仅 {eval_set_size} 题（回归评估建议 ≥5）")
    if not trace_rows:
        suggestions.append("近 90 天无真实问数轨迹，先在业务中使用问数积累信号")

    return {
        "data_source_id": ds,
        "window_days": _WINDOW_DAYS,
        "trace_count": len(trace_rows),
        "eval_set_size": eval_set_size,
        "categories": categories,
        "suggestions": suggestions,
    }
