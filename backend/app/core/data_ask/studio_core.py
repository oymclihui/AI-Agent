"""一句话分析工作台：模板匹配 + 多节执行 + 三栏输出（文字摘要 + 数据表格 + 深度分析）。

每节结构：
  {
    "title": str,
    "role": "kpi" | "detail",
    "summary_lines": [...],      # 管理层摘要 3-5 句（含环比/同比数字）
    "comparisons": {dod, wow, yoy},  # 环比同比计算结果
    "table": {columns, rows},    # 原始主查询结果
    "deep_analysis": {anomalies, breakdowns, suggestions},
    "charts": [...],
    "sql": str,
  }
"""
from __future__ import annotations

import re
import time
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.comparison import compute_comparisons, summary_lines
from app.core.data_ask.depth_analysis import (
    anomaly_points,
    contribution_breakdown,
    generate_suggestions,
)
from app.core.data_ask.service import run_data_ask
from app.core.data_ask.studio_models import AnalysisTemplate
from app.db.models import DataSource

logger = structlog.get_logger(__name__)

MAX_SECTIONS = 6


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def match_template(templates: list[AnalysisTemplate], question: str) -> AnalysisTemplate | None:
    q = _norm(question)
    best: AnalysisTemplate | None = None
    best_score = 0
    for tpl in templates:
        if not tpl.enabled:
            continue
        score = sum(1 for k in (tpl.keywords or []) if _norm(k) and _norm(k) in q)
        if score > best_score:
            best, best_score = tpl, score
    return best


async def list_templates(db: AsyncSession, data_source_id: str) -> list[AnalysisTemplate]:
    rows = (
        await db.execute(
            select(AnalysisTemplate)
            .where(AnalysisTemplate.data_source_id == data_source_id)
            .order_by(AnalysisTemplate.sort_order, AnalysisTemplate.created_at)
        )
    ).scalars().all()
    return list(rows)


async def _build_section(
    *,
    db: AsyncSession,
    source: DataSource,
    question_about: str,
    title: str,
    role: str,
    chart_hint: str,
    user: Any,
) -> dict[str, Any]:
    start = time.monotonic()
    result = await run_data_ask(
        db,
        data_source_id=source.id,
        question=question_about,
        user=user,
        execute=True,
        history=[],
        stage_queue=None,
    )
    columns = list(result.get("columns") or [])
    rows = list(result.get("rows") or [])
    sql = result.get("display_sql") or result.get("sql") or ""

    # 三栏输出：kpi 节做对比和深度分析；detail 节只做表格
    comparisons: dict[str, Any] | None = None
    anomalies: list[dict[str, Any]] = []
    breakdowns: list[dict[str, Any]] = []
    suggestions: list[str] = []
    summary: list[str] = []

    if role == "kpi" and rows:
        try:
            comparisons = await compute_comparisons(
                source=source, current_sql=sql,
                current_rows=rows, columns=columns,
            )
            summary = summary_lines(columns, rows, comparisons, question_about)
            anomalies = anomaly_points(columns, rows)
            # 拆解前两列（分组 + 指标）
            for m_idx in range(1, min(len(rows[0] or []), 4)):
                if m_idx < len(columns):
                    bd = contribution_breakdown(columns, rows, metric_index=m_idx)
                    if bd.get("available"):
                        breakdowns.append(bd)
            suggestions = generate_suggestions(question_about, comparisons, anomalies, breakdowns)
        except Exception as exc:  # 对比/深度分析不影响主结果
            logger.warning("studio_deep_failed", title=title, error=str(exc)[:200])
            summary = [f"· {question_about}（深度分析失败：{exc}）"]
    elif not summary:
        summary = [f"· {question_about}"]

    charts = result.get("charts") or []
    if chart_hint in ("bar", "line", "pie"):
        charts = [c for c in charts if str(c.get("type") or "") == chart_hint] or charts

    return {
        "title": title,
        "role": role,
        "summary_lines": summary,
        "comparisons": comparisons,
        "table": {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        },
        "deep_analysis": {
            "anomalies": anomalies,
            "breakdowns": breakdowns,
            "suggestions": suggestions,
        },
        "charts": charts,
        "chart": result.get("chart"),
        "sql": sql,
        "cached": bool(result.get("cached")),
        "elapsed_ms": int((time.monotonic() - start) * 1000),
        "route": result.get("route"),
        "confidence": result.get("confidence"),
    }


async def run_analysis_studio(
    db: AsyncSession,
    *,
    data_source_id: str,
    question: str,
    user: Any,
    template_id: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()

    source = await db.get(DataSource, data_source_id)
    if source is None:
        raise ValueError("数据源不存在")

    tpl: AnalysisTemplate | None = None
    if template_id:
        tpl = (
            await db.execute(
                select(AnalysisTemplate).where(
                    AnalysisTemplate.id == template_id,
                    AnalysisTemplate.data_source_id == data_source_id,
                )
            )
        ).scalars().first()
    if tpl is None:
        tpl = match_template(await list_templates(db, data_source_id), question)

    if tpl is None:
        section = await _build_section(
            db=db, source=source, question_about=question,
            title=question[:40], role="kpi", chart_hint="auto", user=user,
        )
        return {
            "mode": "free",
            "matched_template": None,
            "question": question,
            "sections": [section],
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }

    sections: list[dict[str, Any]] = []
    for sec in (tpl.sections or [])[:MAX_SECTIONS]:
        sub_q = str(sec.get("question") or "").replace("{q}", question).replace("{question}", question)
        if not sub_q.strip():
            continue
        role = str(sec.get("role") or ("kpi" if len(sections) == 0 else "detail"))
        try:
            sections.append(
                await _build_section(
                    db=db, source=source, question_about=sub_q,
                    title=str(sec.get("title") or sub_q[:30]),
                    role=role,
                    chart_hint=str(sec.get("chart") or "auto"),
                    user=user,
                )
            )
        except Exception as exc:
            logger.warning("studio_section_failed", title=sec.get("title"), error=str(exc)[:200])
            sections.append({
                "title": str(sec.get("title") or ""),
                "role": role,
                "error": str(exc)[:200],
            })

    return {
        "mode": "template",
        "matched_template": {"id": tpl.id, "name": tpl.name, "keywords": tpl.keywords or []},
        "question": question,
        "sections": sections,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }
