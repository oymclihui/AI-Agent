"""示例库蒸馏（Agent Evolution 阶段二 L2）。

信号 → 示例：
- like / example  → 正例（原 SQL）
- correction       → 原 SQL 为负例 + 修正后的 SQL 为正例
- dislike          → 负例
正例向量化入 Milvus，问数时检索 Top-K 注入 prompt（few-shot RAG）。

数据真实性红线：示例全部来自真实反馈；样本不足如实返回 reason，不合成、不填充。
"""
from __future__ import annotations

import asyncio
import functools
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.distill import vector_index
from app.db.base import generate_uuid
from app.db.models import AskExample, AskFeedback

logger = logging.getLogger("ds_distill_examples")

SCORE_FLOOR = 0.30


def _is_select(sql: str | None) -> bool:
    s = (sql or "").strip().lstrip("(").strip().lower()
    return s.startswith("select") or s.startswith("with")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def merge_examples(primary: list[dict], secondary: list[dict], limit: int = 4) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for item in list(primary or []) + list(secondary or []):
        question = str(item.get("question") or "").strip()
        key = _compact(question)
        if not key or key in seen:
            continue
        seen.add(key)
        ref_id = str(item.get("ref_id") or item.get("example_id") or "")
        ref_type = item.get("ref_type")
        if not ref_type and ref_id:
            ref_type = "example" if item.get("example_id") else "golden"
        out.append(
            {
                "question": question,
                "sql": str(item.get("sql") or ""),
                "score": float(item.get("score") or 0),
                "ref_id": ref_id or None,
                "ref_type": ref_type or None,
            }
        )
        if len(out) >= limit:
            break
    return out


async def gather_memory_examples(
    db: AsyncSession,
    *,
    data_source_id: str,
    question: str,
    top_k: int = 3,
    min_score: float | None = None,
    strong_score: float | None = None,
    skill_id: str | None = None,
) -> list[dict[str, Any]]:
    """golden queries（词面相似）+ 蒸馏示例库（向量相似）合并，供 nl2sql few-shot 注入。

    skill_id 非空时，该技能的专属示例排在金标之前（不足 top_k 再回落全源金标）。

    min_score：P0-C 记忆先验分档阈值（None=query_memory 默认 0.35）。
    strong_score：P1-C 相似度分档阈值（归一化刻度，None=不标注）。非空时为每条
    示例标注 tier——归一化相似度 ≥ 阈值标 "strong"（强沿用指令），否则标 "weak"
    （仅参考指令），由 format_memory_prompt 分档渲染。
    """
    from app.core.data_ask.intelligence.query_memory import retrieve_similar_queries

    kwargs: dict[str, Any] = {}
    if min_score is not None:
        kwargs["min_score"] = float(min_score)
    base = await retrieve_similar_queries(
        db, data_source_id=data_source_id, question=question, top_k=top_k, **kwargs
    )
    if skill_id:
        try:
            from app.core.data_ask.skill_memory import retrieve_skill_examples

            skill_hits = await retrieve_skill_examples(
                db, skill_id=skill_id, question=question,
                data_source_id=data_source_id, top_k=top_k,
                min_score=float(min_score) if min_score is not None else 0.35,
            )
            base = list(skill_hits) + list(base)
        except Exception as exc:
            logger.warning("gather_skill_memory_failed skill=%s err=%s", skill_id, str(exc)[:150])
    distilled: list[dict[str, Any]] = []
    try:
        distilled = await asyncio.to_thread(
            functools.partial(
                vector_index.search_examples,
                data_source_id=data_source_id,
                question=question,
                top_k=top_k,
            )
        )
    except Exception as exc:
        logger.warning("gather_distilled_failed ds=%s err=%s", data_source_id, str(exc)[:150])
    strong = [d for d in distilled if float(d.get("score") or 0) >= SCORE_FLOOR]
    # 金标在前：同一问题去重时保留金标（反馈时同步写入，纠正后立即生效），
    # 蒸馏示例由 Celery 异步产出，可能短暂滞后于最新纠正。
    merged = merge_examples(base, strong, limit=max(top_k, 4))
    if strong_score is not None:
        from app.core.data_ask.intelligence.query_memory import normalized_score

        threshold = float(strong_score)
        for ex in merged:
            ex["tier"] = (
                "strong"
                if normalized_score(float(ex.get("score") or 0), ex.get("ref_type")) >= threshold
                else "weak"
            )
    return merged


async def distill_examples(db: AsyncSession, *, data_source_id: str) -> dict[str, Any]:
    """把 ask_feedback 蒸馏成 ask_example；正例向量化入 Milvus。"""
    fb_res = await db.execute(
        select(AskFeedback)
        .where(AskFeedback.data_source_id == str(data_source_id))
        .order_by(AskFeedback.id.asc())
        .limit(500)
    )
    feedbacks = list(fb_res.scalars().all())
    if not feedbacks:
        return {"created": 0, "updated": 0, "indexed": 0, "reason": "无用户反馈样本（点赞 / 保存示例 / 纠错 / 踩）"}

    ex_res = await db.execute(
        select(AskExample).where(AskExample.data_source_id == str(data_source_id)).limit(1000)
    )
    existing = list(ex_res.scalars().all())

    # 同一问题+类型只保留最新一行：旧反馈按时间顺序回放时，"最新纠正"必须最终生效，
    # 历史同 key 行一律停用并从向量库删除，避免旧 SQL 以高分示例抢占 prompt。
    def _ts(row: AskExample):
        return row.updated_at or row.created_at or datetime.min.replace(tzinfo=timezone.utc)

    keep: dict[tuple[str, str], AskExample] = {}
    for row in sorted(existing, key=_ts):
        keep[(_compact(row.question), str(row.kind))] = row
    for row in existing:
        key = (_compact(row.question), str(row.kind))
        if row is keep.get(key):
            continue
        if row.active:
            row.active = False
            await asyncio.to_thread(
                functools.partial(
                    vector_index.delete_example,
                    data_source_id=str(data_source_id),
                    example_id=str(row.id),
                )
            )
    key_map: dict[tuple[str, str], AskExample] = dict(keep)

    candidates: list[dict[str, Any]] = []

    def add_candidate(question: str, sql: str, kind: str, source: str, trace_id, quality: float) -> None:
        if not question or not _is_select(sql):
            return
        candidates.append(
            {
                "question": question.strip(),
                "sql": (sql or "").strip(),
                "kind": kind,
                "source": source,
                "trace_id": trace_id,
                "quality": quality,
            }
        )

    for fb in feedbacks:
        q = (fb.question or "").strip()
        if not q:
            continue
        ftype = (fb.feedback_type or "").strip().lower()
        orig = fb.original_sql
        corr = fb.corrected_sql
        if ftype == "correction":
            add_candidate(q, orig or "", "negative", "correction", fb.trace_id, 0.6)
            add_candidate(q, corr or "", "positive", "correction", fb.trace_id, 0.95)
        elif ftype == "dislike":
            add_candidate(q, corr or orig or "", "negative", "dislike", fb.trace_id, 0.6)
        elif ftype in ("like", "example"):
            add_candidate(q, corr or orig or "", "positive", ftype, fb.trace_id, 0.9 if ftype == "example" else 0.8)

    created = 0
    updated = 0
    indexed = 0
    for cand in candidates:
        key = (_compact(cand["question"]), cand["kind"])
        row = key_map.get(key)
        if row is not None:
            # 低质量信号（like/example=0.8~0.9）不得覆盖高质量信号（correction=0.95）
            if float(cand["quality"]) < float(row.quality or 0):
                continue
            row.sql_text = cand["sql"]
            row.quality = max(float(row.quality or 0), cand["quality"])
            row.trace_id = cand["trace_id"] or row.trace_id
            row.active = True
            updated += 1
        else:
            row = AskExample(
                id=generate_uuid(),
                data_source_id=str(data_source_id),
                question=cand["question"],
                sql_text=cand["sql"],
                kind=cand["kind"],
                source=cand["source"],
                quality=cand["quality"],
                trace_id=cand["trace_id"],
                use_count=0,
                active=True,
                indexed=False,
            )
            db.add(row)
            key_map[key] = row
            created += 1
        await db.flush()
        if row.kind == "positive":
            ok = await asyncio.to_thread(
                functools.partial(
                    vector_index.upsert_example,
                    data_source_id=str(data_source_id),
                    example_id=str(row.id),
                    question=row.question,
                    sql_text=row.sql_text,
                    kind=row.kind,
                    source=row.source,
                    trace_id=int(row.trace_id or 0),
                )
            )
            row.indexed = bool(ok)
            if ok:
                indexed += 1

    await db.flush()
    logger.info(
        "distill_examples ds=%s created=%s updated=%s indexed=%s",
        data_source_id, created, updated, indexed,
    )
    return {
        "created": created,
        "updated": updated,
        "indexed": indexed,
        "total_feedback": len(feedbacks),
    }
