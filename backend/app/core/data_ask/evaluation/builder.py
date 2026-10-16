"""回归测试集（考题库）构建：golden 查询 + 正例示例 + 人工补充。

数据真实性红线：
- 考题全部来自真实交互（data_ask_golden_queries / ask_example 正例）或人工录入，禁止合成。
- 期望结果签名取自真实问数轨迹（ask_trace.result_signature），取不到则留空，
  首次评估时以真实执行结果回填基线（runner 侧负责）。
- 素材不足时如实返回缺口提示，不硬凑题数。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.evaluation.categories import classify_question
from app.db.models import (
    AgentEvalSet,
    AskExample,
    AskTrace,
    DataAskGoldenQuery,
    DataSource,
)

logger = logging.getLogger("agent_eval_builder")

_MAX_SET_SIZE = 50


def _norm_question(text: str | None) -> str:
    return " ".join((text or "").split()).strip().lower()


async def _latest_trace_baseline(
    db: AsyncSession, data_source_id: str, question: str,
) -> tuple[str | None, int | None]:
    """从真实轨迹取该问题最近一次成功执行的签名基线。"""
    res = await db.execute(
        select(AskTrace.result_signature, AskTrace.row_count)
        .where(
            AskTrace.data_source_id == str(data_source_id),
            AskTrace.success.is_(True),
            AskTrace.result_signature.isnot(None),
            AskTrace.question == question,
        )
        .order_by(AskTrace.id.desc())
        .limit(1)
    )
    row = res.first()
    if not row:
        return None, None
    return row[0], row[1]


async def _existing_questions(db: AsyncSession, data_source_id: str) -> set[str]:
    res = await db.execute(
        select(AgentEvalSet.question).where(AgentEvalSet.data_source_id == str(data_source_id))
    )
    return {_norm_question(q) for (q,) in res.all()}


async def build_eval_set(
    db: AsyncSession,
    source: DataSource,
    *,
    max_golden: int = 25,
    max_examples: int = 25,
) -> dict[str, Any]:
    """从 golden 查询与正例示例自动构建/扩充回归测试集（幂等：按问题文本去重）。"""
    ds = str(source.id)
    agent_id = str(source.agent_id) if source.agent_id else None
    existing = await _existing_questions(db, ds)

    created = 0
    skipped_dupe = 0
    golden_used = 0
    examples_used = 0
    baseline_hits = 0

    # ── 素材一：golden 查询（用户确认过的优质问答，优先级最高）──
    golden_rows = (
        await db.execute(
            select(DataAskGoldenQuery)
            .where(DataAskGoldenQuery.data_source_id == ds)
            .order_by(DataAskGoldenQuery.use_count.desc(), DataAskGoldenQuery.created_at.desc())
            .limit(max_golden)
        )
    ).scalars().all()

    for g in golden_rows:
        if created >= _MAX_SET_SIZE:
            break
        key = _norm_question(g.question)
        if not key or key in existing:
            skipped_dupe += 1
            continue
        sig, row_count = await _latest_trace_baseline(db, ds, g.question)
        if sig:
            baseline_hits += 1
        db.add(AgentEvalSet(
            data_source_id=ds,
            agent_id=agent_id,
            question=g.question,
            expected_sql=g.sql_text,
            expected_signature=sig,
            expected_row_count=row_count,
            category=classify_question(g.question),
            source="golden",
        ))
        existing.add(key)
        created += 1
        golden_used += 1

    # ── 素材二：示例库正例（点赞/保存沉淀的优质问答）──
    example_rows = (
        await db.execute(
            select(AskExample)
            .where(
                AskExample.data_source_id == ds,
                AskExample.kind == "positive",
                AskExample.active.is_(True),
            )
            .order_by(AskExample.quality.desc(), AskExample.use_count.desc(), AskExample.created_at.desc())
            .limit(max_examples)
        )
    ).scalars().all()

    trace_ids = [e.trace_id for e in example_rows if e.trace_id]
    trace_sigs: dict[int, tuple[str | None, int | None]] = {}
    if trace_ids:
        rows = (
            await db.execute(
                select(AskTrace.id, AskTrace.result_signature, AskTrace.row_count)
                .where(AskTrace.id.in_(trace_ids))
            )
        ).all()
        trace_sigs = {int(tid): (sig, rc) for tid, sig, rc in rows}

    for e in example_rows:
        if created >= _MAX_SET_SIZE:
            break
        key = _norm_question(e.question)
        if not key or key in existing:
            skipped_dupe += 1
            continue
        sig, row_count = trace_sigs.get(int(e.trace_id), (None, None)) if e.trace_id else (None, None)
        if sig:
            baseline_hits += 1
        db.add(AgentEvalSet(
            data_source_id=ds,
            agent_id=agent_id,
            question=e.question,
            expected_sql=e.sql_text,
            expected_signature=sig,
            expected_row_count=row_count,
            category=classify_question(e.question),
            source="example",
        ))
        existing.add(key)
        created += 1
        examples_used += 1

    await db.flush()

    set_size = int((
        await db.execute(
            select(func.count(AgentEvalSet.id)).where(
                AgentEvalSet.data_source_id == ds, AgentEvalSet.active.is_(True),
            )
        )
    ).scalar() or 0)

    gaps: list[str] = []
    if set_size < 5:
        gaps.append(
            f"考题库仅 {set_size} 题（建议 ≥5）：golden 查询与正例示例不足，"
            "请通过问数反馈（点赞/保存示例）或手工补题继续积累"
        )
    if created > 0 and baseline_hits == 0:
        gaps.append("本次新增考题均未命中历史结果签名，首次评估将回填真实基线")

    logger.info(
        "build_eval_set ds=%s created=%s golden=%s examples=%s dupe=%s baseline=%s set_size=%s",
        ds, created, golden_used, examples_used, skipped_dupe, baseline_hits, set_size,
    )
    return {
        "data_source_id": ds,
        "created": created,
        "golden_used": golden_used,
        "examples_used": examples_used,
        "skipped_dupe": skipped_dupe,
        "baseline_hits": baseline_hits,
        "set_size": set_size,
        "gaps": gaps,
    }
