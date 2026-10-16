"""业务规则蒸馏：纠错记录 → 默认过滤 / 口径 / 术语偏好（Agent Evolution 阶段二 L2）。

- 样本来源：ask_feedback 中 feedback_type=correction 的（原 SQL, 修正 SQL）配对，均为真实用户纠错
- 同一类问题的纠错聚成组，交由 LLM 归纳通用业务规则
- 规则类型：caliber(指标口径/公式) / terminology(术语别名/字段含义) / filter(默认过滤条件)
- 生效(activate)后回写语义层：caliber→指标口径，terminology→术语词典，filter→问数 prompt notes
- 无纠错记录如实返回 reason，不合成
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.intelligence.query_memory import score_question_similarity
from app.db.base import generate_uuid
from app.db.models import (
    AskFeedback,
    DsBusinessRule,
    DsSemanticMetric,
    DsSemanticTerm,
)

logger = logging.getLogger("ds_distill_rules")

_RULE_TYPES = ("caliber", "terminology", "filter")
_GROUP_THRESHOLD = 0.6


def _is_select(sql: str | None) -> bool:
    s = (sql or "").strip().lstrip("(").strip().lower()
    return s.startswith("select") or s.startswith("with")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def _group_corrections(corrections: list[AskFeedback]) -> list[list[AskFeedback]]:
    groups: list[list[AskFeedback]] = []
    for fb in corrections:
        q = fb.question or ""
        placed = False
        for group in groups:
            if score_question_similarity(q, group[0].question or "") >= _GROUP_THRESHOLD:
                group.append(fb)
                placed = True
                break
        if not placed:
            groups.append([fb])
    return groups


async def _summarize_rules(db: AsyncSession, group: list[AskFeedback]) -> list[dict[str, Any]]:
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.models_hub.router import ModelRouter

    system = (
        "你是数据治理专家。下面给出同一类问题的【错误 SQL】与【用户修正后的正确 SQL】。\n"
        "请归纳出这批纠错背后的通用业务规则，用于让后续生成的 SQL 一次命中。\n"
        "只依据给出的 SQL 差异归纳，不要编造字段、数值或不存在的表。\n"
        "规则类型只能是：caliber(指标口径/公式)、terminology(术语别名/字段含义)、filter(默认过滤条件)。\n"
        '返回 JSON：{"rules":[{"rule_type":"filter","name":"规则名","rule_text":"规则说明",'
        '"applies_to":"适用指标/字段/场景","confidence":0.8,"expr":"可选SQL表达式",'
        '"column_ref":"可选列名","note":"可选补充"}]}\n'
    )
    lines: list[str] = []
    for fb in group[:8]:
        lines.append(f"问题: {fb.question or ''}")
        lines.append(f"错误 SQL: {(fb.original_sql or '')[:800]}")
        lines.append(f"正确 SQL: {(fb.corrected_sql or '')[:800]}")
        lines.append("")
    user = "\n".join(lines)
    try:
        llm = await ModelRouter.get_llm(db=db, response_style="precise")
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
    except Exception as exc:
        logger.warning("summarize_rules_llm_failed err=%s", str(exc)[:200])
        return []
    match = re.search(r"\{[\s\S]*\}", text or "")
    if not match:
        return []
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return []
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        return []
    return [r for r in rules if isinstance(r, dict) and str(r.get("rule_type") or "") in _RULE_TYPES]


async def _upsert_rule(
    db: AsyncSession,
    *,
    data_source_id: str,
    existing: dict[tuple[str, str], DsBusinessRule],
    item: dict[str, Any],
    evidence: dict[str, Any],
) -> bool:
    rule_type = str(item.get("rule_type") or "").strip()
    name = str(item.get("name") or "").strip()[:255]
    rule_text = str(item.get("rule_text") or "").strip()
    if not rule_type or not name or not rule_text:
        return False
    payload = {
        "expr": str(item.get("expr") or "").strip(),
        "column_ref": str(item.get("column_ref") or "").strip(),
        "note": str(item.get("note") or "").strip(),
        "synonyms": item.get("synonyms") or [],
        "dimensions": item.get("dimensions") or [],
        "default_filters": item.get("default_filters") or [],
    }
    try:
        confidence = float(item.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    key = (rule_type, _compact(name))
    row = existing.get(key)
    if row is not None:
        row.rule_text = rule_text
        row.applies_to = (str(item.get("applies_to") or "").strip()[:255]) or row.applies_to
        row.payload = payload
        row.evidence = evidence
        row.confidence = confidence
        return False
    row = DsBusinessRule(
        id=generate_uuid(),
        data_source_id=str(data_source_id),
        rule_type=rule_type,
        name=name,
        rule_text=rule_text,
        applies_to=(str(item.get("applies_to") or "").strip()[:255]) or None,
        payload=payload,
        evidence=evidence,
        confidence=confidence,
        status="candidate",
        source="auto",
    )
    db.add(row)
    existing[key] = row
    return True


async def mine_rules(
    db: AsyncSession,
    *,
    data_source_id: str,
    min_support: int = 1,
) -> dict[str, Any]:
    res = await db.execute(
        select(AskFeedback)
        .where(
            AskFeedback.data_source_id == str(data_source_id),
            AskFeedback.feedback_type == "correction",
        )
        .order_by(AskFeedback.id.desc())
        .limit(200)
    )
    corrections = [
        fb
        for fb in res.scalars().all()
        if _is_select(fb.original_sql) and _is_select(fb.corrected_sql)
    ]
    if not corrections:
        return {"rules": 0, "reason": "无纠错记录（feedback_type=correction）"}

    groups = _group_corrections(corrections)
    existing_res = await db.execute(
        select(DsBusinessRule).where(DsBusinessRule.data_source_id == str(data_source_id))
    )
    existing = {(r.rule_type, _compact(r.name)): r for r in existing_res.scalars().all()}

    produced = 0
    for group in groups:
        items = await _summarize_rules(db, group)
        if not items:
            continue
        evidence = {
            "corrections": [fb.id for fb in group][:20],
            "samples": [
                {
                    "question": fb.question or "",
                    "wrong_sql": (fb.original_sql or "")[:400],
                    "right_sql": (fb.corrected_sql or "")[:400],
                }
                for fb in group[:5]
            ],
        }
        for item in items:
            if await _upsert_rule(
                db, data_source_id=data_source_id, existing=existing, item=item, evidence=evidence
            ):
                produced += 1

    await db.flush()
    logger.info("mine_rules ds=%s produced=%s corrections=%s", data_source_id, produced, len(corrections))
    return {"rules": produced, "corrections": len(corrections)}


async def activate_rule(db: AsyncSession, rule: DsBusinessRule) -> dict[str, Any]:
    """把候选规则写回语义层（caliber→指标，terminology→术语；filter 由 prompt 注入）。"""
    payload = rule.payload or {}
    materialized_id: str | None = None

    if rule.rule_type == "caliber" and str(payload.get("expr") or "").strip():
        res = await db.execute(
            select(DsSemanticMetric).where(
                DsSemanticMetric.data_source_id == rule.data_source_id,
                DsSemanticMetric.name == rule.name,
            )
        )
        row = res.scalar_one_or_none()
        if row:
            row.expr = str(payload["expr"]).strip()
            row.description = rule.rule_text
            row.source = "auto"
        else:
            row = DsSemanticMetric(
                id=generate_uuid(),
                data_source_id=rule.data_source_id,
                name=rule.name,
                expr=str(payload["expr"]).strip(),
                description=rule.rule_text,
                dimensions=payload.get("dimensions") or [],
                default_filters=payload.get("default_filters") or [],
                source="auto",
            )
            db.add(row)
        await db.flush()
        materialized_id = str(row.id)
    elif rule.rule_type == "terminology":
        res = await db.execute(
            select(DsSemanticTerm).where(
                DsSemanticTerm.data_source_id == rule.data_source_id,
                DsSemanticTerm.term == rule.name,
            )
        )
        row = res.scalar_one_or_none()
        if row:
            row.definition = rule.rule_text
            row.column_ref = str(payload.get("column_ref") or "").strip() or row.column_ref
            row.source = "auto"
        else:
            row = DsSemanticTerm(
                id=generate_uuid(),
                data_source_id=rule.data_source_id,
                term=rule.name,
                definition=rule.rule_text,
                column_ref=str(payload.get("column_ref") or "").strip() or None,
                synonyms=payload.get("synonyms") or [],
                source="auto",
            )
            db.add(row)
        await db.flush()
        materialized_id = str(row.id)

    rule.status = "active"
    rule.materialized_id = materialized_id
    await db.flush()
    return {"status": "active", "materialized_id": materialized_id, "rule_type": rule.rule_type}
