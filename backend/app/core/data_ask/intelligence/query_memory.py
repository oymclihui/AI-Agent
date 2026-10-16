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


def _bigrams(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", (text or "").lower())
    if len(compact) < 2:
        return set()
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def score_question_similarity(left: str, right: str, use_count: int = 0) -> float:
    """Chinese-friendly similarity. Bigrams catch rephrasing that whole-word overlap misses."""
    if left.strip().lower() == right.strip().lower():
        return 10.0 + min(use_count, 10) * 0.05
    score = _jaccard(_bigrams(left), _bigrams(right)) * 2.0
    score += _jaccard(_tokens(left), _tokens(right))
    folded_left = left.strip().lower()
    folded_right = right.strip().lower()
    if folded_left and (folded_left in folded_right or folded_right in folded_left):
        score += 0.6
    score += min(use_count, 10) * 0.05
    return score


def normalized_score(score: float, ref_type: str | None = None) -> float:
    """把两类记忆源的原始相似度归一到 [0,1]，供 P1-C 强沿用/仅参考分档比较。

    - golden（词面打分）：精确匹配=10+ → 1.0；其余由 bigram/token/包含关系构成，
      按 score/2 折半映射、0.99 封顶。归一后 ≥0.85 ≈ 原始分 ≥1.7（措辞高度重合，
      大概率为同一提问）。
    - example（Milvus 向量余弦）：本就在 [0,1]，截断即可。
    ref_type 缺失时按数值范围启发：>1.0 必为 golden 刻度（向量分不会超 1）。
    """
    s = float(score or 0.0)
    golden_scale = ref_type == "golden" or (ref_type is None and s > 1.0)
    if golden_scale:
        if s >= 10.0:
            return 1.0
        return max(0.0, min(0.99, s / 2.0))
    return max(0.0, min(1.0, s))


async def retrieve_similar_queries(
    db: AsyncSession,
    *,
    data_source_id: str,
    question: str,
    top_k: int = 3,
    min_score: float = 0.35,
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(DataAskGoldenQuery)
        .where(DataAskGoldenQuery.data_source_id == data_source_id)
        .order_by(DataAskGoldenQuery.use_count.desc(), DataAskGoldenQuery.updated_at.desc())
        .limit(200)
    )
    rows = list(result.scalars().all())
    if not rows:
        return []

    scored: list[tuple[float, DataAskGoldenQuery]] = []
    for row in rows:
        score = score_question_similarity(question, row.question, row.use_count or 0)
        scored.append((score, row))
    scored.sort(key=lambda x: -x[0])
    out: list[dict[str, Any]] = []
    for score, row in scored[:top_k]:
        if score < min_score:
            continue
        out.append({
            "question": row.question, "sql": row.sql_text,
            "score": round(score, 4), "ref_id": str(row.id), "ref_type": "golden",
        })
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


def pick_recommended(
    golden: list[tuple[str, int]],
    audits: list[str],
    limit: int = 6,
) -> list[str]:
    """Golden questions first, then recent successful asks. Duplicates collapse."""
    seen: set[str] = set()
    picked: list[str] = []

    def add(question: str) -> None:
        text = (question or "").strip()
        key = re.sub(r"\s+", "", text).lower()
        if len(key) < 4 or key in seen:
            return
        if key.startswith("select") or key.startswith("with") or text.startswith("执行"):
            return
        seen.add(key)
        picked.append(text)

    for question, _use_count in sorted(golden, key=lambda item: (-item[1], item[0])):
        add(question)
        if len(picked) >= limit:
            return picked
    for question in audits:
        add(question)
        if len(picked) >= limit:
            break
    return picked


async def recommend_questions(
    db: AsyncSession,
    *,
    data_source_id: str,
    limit: int = 6,
) -> list[str]:
    from app.db.models import DataAskAuditLog

    golden_rows = await db.execute(
        select(DataAskGoldenQuery.question, DataAskGoldenQuery.use_count)
        .where(DataAskGoldenQuery.data_source_id == data_source_id)
        .order_by(DataAskGoldenQuery.use_count.desc())
        .limit(30)
    )
    audit_rows = await db.execute(
        select(DataAskAuditLog.question)
        .where(
            DataAskAuditLog.data_source_id == data_source_id,
            DataAskAuditLog.success.is_(True),
            DataAskAuditLog.question.is_not(None),
        )
        .order_by(DataAskAuditLog.created_at.desc())
        .limit(40)
    )
    golden = [(str(question or ""), int(use_count or 0)) for question, use_count in golden_rows.all()]
    audits = [str(question or "") for (question,) in audit_rows.all()]
    return pick_recommended(golden, audits, limit)


def format_memory_prompt(examples: list[dict[str, Any]]) -> str:
    """把历史问答（金标 / 蒸馏示例）注入 nl2sql few-shot。

    P1-C 相似度分档：按 tier（gather 时按归一化相似度阈值标注）分两档——
    - strong（高置信同一提问）：强指令沿用其 SQL 口径（验收实证：弱提示下改变率为 0）。
    - weak（主题相近但不足以判定同一提问）：降级「仅参考」，告知模型可按本问题
      实际语义自行探索口径（Dream-RSI 机制三：强先验对非同一提问压制泛化）。
    无 tier 标注的条目按 strong 处理（向后兼容旧调用方）。
    """
    if not examples:
        return ""

    def _item_lines(items: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for ex in items:
            question = str(ex.get("question") or "").strip()
            sql = str(ex.get("sql") or "").strip()
            if not question or not sql:
                continue
            score = ex.get("score")
            ref = str(ex.get("ref_type") or ex.get("source") or "").strip()
            tag = ""
            if isinstance(score, (int, float)):
                tag = f"  -- 相似度 {float(score):.2f}"
            if ref:
                tag += f"｜来源 {ref}"
            lines.append(f"Q: {question}")
            lines.append(f"SQL: {sql}{tag}")
        return lines

    strong_lines = _item_lines([e for e in examples if str(e.get("tier") or "") != "weak"])
    weak_lines = _item_lines([e for e in examples if str(e.get("tier") or "") == "weak"])
    if not strong_lines and not weak_lines:
        return ""

    out: list[str] = []
    if strong_lines:
        out.append("## 历史问答记忆（来自用户已确认 / 已纠正的真实问答）")
        out.append(
            "判定规则：若下列某条与本问题属于同一提问（问题意图一致，仅措辞不同），"
            "必须直接沿用该条的 SQL 口径与写法（聚合方式、分组维度、过滤条件、字段与别名），"
            "不要按你的默认口径自行改写；若只是主题相近但时间范围 / 口径不同，则忽略该条或仅作参考。"
            "相似度越高越可能是同一提问。"
        )
        out.extend(strong_lines)
    if weak_lines:
        out.append("## 相似历史问答（仅参考，不足以判定为同一提问）")
        out.append(
            "下列问答与本问题主题相近，但相似度不足以判定为同一提问：SQL 口径仅供参照，"
            "请按本问题的实际语义（时间范围 / 指标口径 / 分组维度）自行生成，不要强行沿用。"
        )
        out.extend(weak_lines)
    return "\n".join(out) + "\n"
