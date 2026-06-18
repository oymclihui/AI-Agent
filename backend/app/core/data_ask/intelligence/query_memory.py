"""Golden question-SQL memory per data source."""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import generate_uuid
from app.db.models import DataAskGoldenQuery


def _tokens(text: str) -> set[str]:
    parts = re.findall(r"[\w\u4e00-\u9fff]+", (text or "").lower())
    return {p for p in parts if len(p) >= 2}


async def retrieve_similar_queries(
    db: AsyncSession,
    *,
    data_source_id: str,
    question: str,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(DataAskGoldenQuery)
        .where(DataAskGoldenQuery.data_source_id == data_source_id)
        .order_by(DataAskGoldenQuery.use_count.desc(), DataAskGoldenQuery.updated_at.desc())
        .limit(50)
    )
    rows = list(result.scalars().all())
    if not rows:
        return []

    qtok = _tokens(question)
    scored: list[tuple[float, DataAskGoldenQuery]] = []
    for row in rows:
        rtok = _tokens(row.question)
        overlap = len(qtok & rtok)
        score = overlap + min(row.use_count, 10) * 0.1
        if row.question.strip().lower() == question.strip().lower():
            score += 10
        scored.append((score, row))
    scored.sort(key=lambda x: -x[0])
    out: list[dict[str, Any]] = []
    for score, row in scored[:top_k]:
        if score <= 0 and out:
            break
        out.append({"question": row.question, "sql": row.sql_text, "score": score})
    return out


async def save_golden_query(
    db: AsyncSession,
    *,
    data_source_id: str,
    question: str,
    sql_text: str,
    user_id: str | None,
) -> DataAskGoldenQuery:
    result = await db.execute(
        select(DataAskGoldenQuery).where(
            DataAskGoldenQuery.data_source_id == data_source_id,
            DataAskGoldenQuery.question == question.strip(),
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.sql_text = sql_text.strip()
        existing.confirmed_by = user_id
        existing.use_count = (existing.use_count or 0) + 1
        await db.flush()
        return existing
    row = DataAskGoldenQuery(
        id=generate_uuid(),
        data_source_id=data_source_id,
        question=question.strip(),
        sql_text=sql_text.strip(),
        confirmed_by=user_id,
        use_count=1,
    )
    db.add(row)
    await db.flush()
    return row


def format_memory_prompt(examples: list[dict[str, Any]]) -> str:
    if not examples:
        return ""
    lines = ["## 相似历史问答（可参考）"]
    for ex in examples:
        lines.append(f"Q: {ex['question']}")
        lines.append(f"SQL: {ex['sql']}")
    return "\n".join(lines) + "\n"
