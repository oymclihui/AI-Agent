"""重放语料：历史问答轨迹（问题 → SQL → 结果 → 反馈）+ 金标查询。

全部来自库内真实数据直查，不构造、不填充（数据真实性红线）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AskFeedback, AskTrace, DataAskGoldenQuery, DataSource


async def build_replay_corpus(
    db: AsyncSession,
    *,
    data_source_id: str,
    limit: int = 500,
) -> dict[str, Any]:
    """构建重放语料：轨迹（含反馈归并）+ 金标查询。按时间倒序取最近 limit 条轨迹。

    source.metadata_.replay_exclude_traces（[trace_id,...]）用于剔除测试伪迹轨迹
    （如 P0-C 旋钮注入验证 run：clarify 被故意关闭，重放按默认策略比对会产生假差异）。
    """
    source = await db.get(DataSource, str(data_source_id))
    meta = dict(getattr(source, "metadata_", None) or {}) if source else {}
    try:
        exclude_ids = {int(x) for x in (meta.get("replay_exclude_traces") or [])}
    except (TypeError, ValueError):
        exclude_ids = set()

    trace_rows = (
        await db.execute(
            select(AskTrace)
            .where(AskTrace.data_source_id == str(data_source_id))
            .order_by(AskTrace.created_at.desc())
            .limit(int(limit))
        )
    ).scalars().all()

    traces: list[dict[str, Any]] = []
    trace_ids: list[int] = []
    for t in trace_rows:
        if not (t.question or "").strip():
            continue
        if int(t.id) in exclude_ids:
            continue
        trace_ids.append(int(t.id))
        traces.append({
            "trace_id": int(t.id),
            "question": (t.question or "").strip(),
            "standalone_question": (t.standalone_question or "").strip(),
            "sql_text": (t.sql_text or "").strip(),
            "success": bool(t.success),
            "row_count": t.row_count,
            "analysis_mode": t.analysis_mode,
            "clarification": bool(t.clarification),
            "memory_hits": int(t.memory_hits or 0),
            "result_signature": t.result_signature,
            "created_at": t.created_at,
        })

    feedback: dict[int, list[dict[str, Any]]] = {}
    if trace_ids:
        fb_rows = (
            await db.execute(
                select(AskFeedback).where(
                    AskFeedback.data_source_id == str(data_source_id),
                    AskFeedback.trace_id.in_(trace_ids),
                ).order_by(AskFeedback.created_at.asc())
            )
        ).scalars().all()
        for f in fb_rows:
            feedback.setdefault(int(f.trace_id), []).append({
                "type": f.feedback_type,
                "corrected_sql": (f.corrected_sql or "").strip(),
                "original_sql": (f.original_sql or "").strip(),
                "comment": (f.comment or "").strip(),
            })
    for t in traces:
        t["feedback"] = feedback.get(t["trace_id"], [])

    golden_rows = (
        await db.execute(
            select(DataAskGoldenQuery)
            .where(DataAskGoldenQuery.data_source_id == str(data_source_id))
            .order_by(DataAskGoldenQuery.use_count.desc())
        )
    ).scalars().all()
    golden = [
        {"id": str(g.id), "question": g.question, "sql_text": g.sql_text, "use_count": int(g.use_count or 0)}
        for g in golden_rows
    ]

    return {
        "data_source_id": str(data_source_id),
        "traces": traces,
        "golden": golden,
        "stats": {
            "traces": len(traces),
            "with_feedback": sum(1 for t in traces if t["feedback"]),
            "corrections": sum(1 for t in traces if any(f["type"] == "correction" for f in t["feedback"])),
            "likes": sum(1 for t in traces if any(f["type"] == "like" for f in t["feedback"])),
            "clarified": sum(1 for t in traces if t["clarification"]),
            "sql_executed": sum(1 for t in traces if t["sql_text"]),
            "golden": len(golden),
        },
    }


def normalize_sql(sql: str) -> str:
    """轻量 SQL 规范化：压缩空白后比较（不做语义等价，重放口径与库内一致即可）。"""
    return " ".join((sql or "").split()).rstrip(";").strip().lower()
