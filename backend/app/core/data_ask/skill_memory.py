"""技能专属示例库（蓝图《分析能力前台化》P1-③，对标 Vanna Tool Memory）。

示例落在 ask_example.skill_id。技能命中后检索优先取该技能示例，条数不足再由
gather_memory_examples 回落全源金标。沉淀只走三条路径：点赞、采纳（example /
correction）、编排步骤经治理链成功。归一化相似度 > 0.95 视为重复，只累加
use_count，不新插一行。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import generate_uuid
from app.db.models import AskExample

_DEDUP_NORM = 0.95
_MATCH_NORM = 0.72
_SCAN_LIMIT = 200


def _norm(question: str, other: str, use_count: int = 0) -> tuple[float, float]:
    from app.core.data_ask.intelligence.query_memory import (
        normalized_score,
        score_question_similarity,
    )

    raw = score_question_similarity(question, other, use_count)
    return raw, normalized_score(raw, "skill")


async def _skill_rows(
    db: AsyncSession,
    *,
    skill_id: str,
    data_source_id: str | None = None,
    skill_ids: list[str] | None = None,
) -> list[AskExample]:
    ids = [skill_id] if skill_id else list(skill_ids or [])
    ids = [s for s in ids if s]
    if not ids:
        return []
    stmt = select(AskExample).where(
        AskExample.skill_id.in_(ids),
        AskExample.active.is_(True),
        AskExample.kind == "positive",
    )
    if data_source_id:
        stmt = stmt.where(AskExample.data_source_id == str(data_source_id))
    stmt = stmt.order_by(AskExample.use_count.desc(), AskExample.updated_at.desc()).limit(_SCAN_LIMIT)
    return list((await db.execute(stmt)).scalars().all())


async def save_skill_example(
    db: AsyncSession,
    *,
    data_source_id: str,
    skill_id: str,
    question: str,
    sql_text: str,
    source: str = "like",
    trace_id: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """写入技能示例。近重复（归一化相似度 > 0.95）不新增，只给原行累加 use_count。"""
    question = (question or "").strip()
    sql_text = (sql_text or "").strip()
    skill_id = (skill_id or "").strip()
    if not question or not sql_text or not skill_id:
        return {"saved": False, "reason": "missing"}

    best: AskExample | None = None
    best_norm = 0.0
    for row in await _skill_rows(db, skill_id=skill_id, data_source_id=data_source_id):
        _raw, norm = _norm(question, row.question or "", row.use_count or 0)
        if norm > best_norm:
            best, best_norm = row, norm
    if best is not None and best_norm > _DEDUP_NORM:
        best.use_count = (best.use_count or 0) + 1
        await db.flush()
        return {
            "saved": False,
            "deduped": True,
            "example_id": best.id,
            "score": round(best_norm, 4),
        }

    row = AskExample(
        id=generate_uuid(),
        data_source_id=str(data_source_id),
        skill_id=skill_id,
        question=question[:4000],
        sql_text=sql_text[:8000],
        kind="positive",
        source=(source or "like")[:20],
        quality=1.0 if source == "correction" else 0.8,
        trace_id=trace_id,
        use_count=1,
        active=True,
        indexed=False,
        note=(note or "")[:500] or None,
    )
    db.add(row)
    await db.flush()
    return {"saved": True, "deduped": False, "example_id": row.id}


async def retrieve_skill_examples(
    db: AsyncSession,
    *,
    skill_id: str,
    question: str,
    data_source_id: str | None = None,
    top_k: int = 3,
    min_score: float = 0.35,
) -> list[dict[str, Any]]:
    """按词面相似度取该技能的正例。分数刻度与金标检索一致（ref_type=skill）。"""
    scored: list[tuple[float, AskExample]] = []
    for row in await _skill_rows(db, skill_id=skill_id, data_source_id=data_source_id):
        raw, _norm_score = _norm(question, row.question or "", row.use_count or 0)
        if raw >= min_score:
            scored.append((raw, row))
    scored.sort(key=lambda item: -item[0])
    out: list[dict[str, Any]] = []
    for raw, row in scored[:top_k]:
        out.append({
            "question": row.question,
            "sql": row.sql_text,
            "score": round(raw, 4),
            "ref_id": str(row.id),
            "ref_type": "skill",
            "skill_id": row.skill_id,
        })
    return out


async def best_skill_by_examples(
    db: AsyncSession,
    *,
    question: str,
    skill_ids: list[str],
    data_source_id: str | None = None,
    priorities: dict[str, int] | None = None,
    min_norm: float = _MATCH_NORM,
) -> str | None:
    """规则未命中时，用技能示例相似度裁决绑定技能。返回 skill_id 或 None。"""
    priorities = priorities or {}
    best_id: str | None = None
    best_key: tuple[float, int] | None = None
    rows = await _skill_rows(db, skill_id="", skill_ids=skill_ids, data_source_id=data_source_id)
    by_skill: dict[str, list[AskExample]] = {}
    for row in rows:
        by_skill.setdefault(str(row.skill_id), []).append(row)
    for sid, items in by_skill.items():
        top = 0.0
        for row in items:
            _raw, norm = _norm(question, row.question or "", row.use_count or 0)
            if norm > top:
                top = norm
        if top < min_norm:
            continue
        key = (top, int(priorities.get(sid) or 0))
        if best_key is None or key > best_key:
            best_key, best_id = key, sid
    return best_id


async def list_skill_examples(
    db: AsyncSession,
    *,
    skill_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    stmt = (
        select(AskExample)
        .where(AskExample.skill_id == skill_id, AskExample.active.is_(True))
        .order_by(AskExample.use_count.desc(), AskExample.updated_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return [
        {
            "id": row.id,
            "data_source_id": row.data_source_id,
            "question": row.question,
            "sql_text": row.sql_text,
            "source": row.source,
            "use_count": row.use_count or 0,
            "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


async def delete_skill_example(
    db: AsyncSession,
    *,
    skill_id: str,
    example_id: str,
) -> bool:
    row = await db.get(AskExample, example_id)
    if not row or row.skill_id != skill_id:
        return False
    await db.delete(row)
    await db.flush()
    return True
