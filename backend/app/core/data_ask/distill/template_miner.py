"""分析模板蒸馏：高频问题聚类 → 可复用分析框架（Agent Evolution 阶段二 L2）。

- 样本来源：真实成功问数轨迹 ask_trace + 已确认 golden queries + 差评/纠错问题（P3-1：没答好的高频问法也进挖掘）
- 聚类：bigram/jaccard 相似度贪心聚类，>= MIN_SUPPORT 个不同问题才算一个高频簇
- 每个簇调用 LLM 归纳出 模板名 / 适用意图 / 步骤化分析框架 / 触发关键词
- 样本不足如实返回 reason
- P3-1 自动线上化：簇内问题被人工纠错过（= 已复核）或质量分 >= AUTO_ONLINE_SCORE 时，
  模板直接 status=active，不再等待人工逐条点上线；已上线模板不因分数回落而降级
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
from app.db.models import AskFeedback, AskTemplate, AskTrace, DataAskGoldenQuery

logger = logging.getLogger("ds_distill_templates")

MIN_SUPPORT = 3
_CLUSTER_THRESHOLD = 0.55
AUTO_ONLINE_SCORE = 0.7  # P3-1：质量分达标即自动上线（模板自增长，无需人工逐条复核）


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def _as_text(value: Any) -> str:
    """LLM 偶尔把字段返回成数组，统一拼成文本（避免写库类型错误）。"""
    if isinstance(value, (list, tuple)):
        return "\n".join(str(v).strip() for v in value if str(v).strip())
    return str(value or "").strip()


def _as_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()][:20]
    if isinstance(value, str) and value.strip():
        return [value.strip()][:20]
    return []


async def _collect_questions(db: AsyncSession, data_source_id: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []

    def add(q: str) -> None:
        text = (q or "").strip()
        key = _compact(text)
        if len(key) < 4 or key in seen:
            return
        if key.startswith("select") or key.startswith("with"):
            return
        seen.add(key)
        out.append(text)

    res = await db.execute(
        select(DataAskGoldenQuery.question).where(
            DataAskGoldenQuery.data_source_id == str(data_source_id)
        )
    )
    for (q,) in res.all():
        add(q)
    res = await db.execute(
        select(AskTrace.question)
        .where(
            AskTrace.data_source_id == str(data_source_id),
            AskTrace.success.is_(True),
            AskTrace.question.is_not(None),
        )
        .order_by(AskTrace.id.desc())
        .limit(400)
    )
    for (q,) in res.all():
        add(q)
    # P3-1：差评/纠错的问题同样进挖掘源——没答好的高频问法最需要模板兜底
    res = await db.execute(
        select(AskFeedback.question).where(
            AskFeedback.data_source_id == str(data_source_id),
            AskFeedback.feedback_type.in_(("dislike", "correction")),
            AskFeedback.question.is_not(None),
        )
    )
    for (q,) in res.all():
        add(q)
    return out


def _cluster(questions: list[str]) -> list[list[str]]:
    clusters: list[list[str]] = []
    for q in questions:
        placed = False
        for cluster in clusters:
            if score_question_similarity(q, cluster[0]) >= _CLUSTER_THRESHOLD:
                cluster.append(q)
                placed = True
                break
        if not placed:
            clusters.append([q])
    return clusters


async def _summarize_cluster(db: AsyncSession, questions: list[str]) -> dict[str, Any] | None:
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.models_hub.router import ModelRouter

    system = (
        "你是资深数据分析专家。下面是一组数据源用户反复提出的相似问题。\n"
        "请归纳出一个可复用的分析框架，供同类问题直接套用。\n"
        "只基于给出的问题归纳，不要编造业务数据或指标数值。\n"
        '返回 JSON：{"name":"模板名","intent":"适用意图","framework":"步骤化分析框架",'
        '"success_criteria":"可量化的验收标准","keywords":["触发词1","触发词2"]}\n'
    )
    user = "相似问题：\n" + "\n".join(f"- {q}" for q in questions[:12])
    try:
        llm = await ModelRouter.get_llm(db=db, response_style="precise")
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
    except Exception as exc:
        logger.warning("summarize_cluster_llm_failed err=%s", str(exc)[:200])
        return None
    match = re.search(r"\{[\s\S]*\}", text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not str(data.get("name") or "").strip():
        return None
    for key in ("name", "intent", "framework", "success_criteria"):
        data[key] = _as_text(data.get(key))
    data["keywords"] = _as_list(data.get("keywords"))
    return data


async def _feedback_stats(db: AsyncSession, data_source_id: str) -> list[tuple[str, str]]:
    """该数据源全部反馈（问题原文, 反馈类型），用于按相似问题归集评分。"""
    res = await db.execute(
        select(AskFeedback.question, AskFeedback.feedback_type).where(
            AskFeedback.data_source_id == str(data_source_id),
            AskFeedback.question.is_not(None),
        )
    )
    return [(q or "", str(t or "")) for q, t in res.all() if len(_compact(q or "")) >= 4]


async def _correction_questions(db: AsyncSession, data_source_id: str) -> list[str]:
    """人工纠错过的问题原文（P3-1：命中的簇视为已复核，模板直接上线）。"""
    res = await db.execute(
        select(AskFeedback.question).where(
            AskFeedback.data_source_id == str(data_source_id),
            AskFeedback.feedback_type == "correction",
            AskFeedback.question.is_not(None),
        )
    )
    return [q for (q,) in res.all() if len(_compact(q or "")) >= 4]


def _quality_score(members: list[str], feedback: list[tuple[str, str]]) -> float:
    """赞踩率 → 0~1 模板评分（Laplace 平滑，纠错按负反馈计）。

    反馈问题与模板样例题按相似度（≥聚类阈值）归集，近似问法也算命中。
    """
    like = 0
    dislike = 0
    for question, ftype in feedback:
        if max((score_question_similarity(question, m) for m in members), default=0.0) < _CLUSTER_THRESHOLD:
            continue
        if ftype == "like":
            like += 1
        elif ftype in ("dislike", "correction"):
            dislike += 1
    return round((like + 1) / (like + dislike + 2), 4)


async def mine_templates(
    db: AsyncSession,
    *,
    data_source_id: str,
    min_support: int = MIN_SUPPORT,
) -> dict[str, Any]:
    questions = await _collect_questions(db, data_source_id)
    need = max(2, int(min_support))
    if len(questions) < need:
        return {
            "templates": 0,
            "questions": len(questions),
            "reason": f"问数样本不足（{len(questions)} 条 < 所需 {need} 条）",
        }
    clusters = [c for c in _cluster(questions) if len(c) >= need]
    if not clusters:
        return {
            "templates": 0,
            "questions": len(questions),
            "reason": f"未发现重复度≥{need} 的高频问题簇",
        }
    clusters.sort(key=lambda c: -len(c))

    res = await db.execute(
        select(AskTemplate).where(AskTemplate.data_source_id == str(data_source_id))
    )
    existing = {_compact(t.name): t for t in res.scalars().all()}
    fb_stats = await _feedback_stats(db, data_source_id)
    corrected = await _correction_questions(db, data_source_id)

    produced = 0
    auto_online = 0
    for cluster in clusters[:10]:
        summary = await _summarize_cluster(db, cluster)
        if not summary:
            continue
        name = str(summary.get("name")).strip()[:255]
        key = _compact(name)
        members = sorted(set(cluster))
        criteria = str(summary.get("success_criteria") or "").strip() or None
        score = _quality_score(members, fb_stats)
        # P3-1 自动线上化：人工纠错命中（= 已复核）或质量分达标 → 直接 active
        has_correction = any(
            max((score_question_similarity(cq, m) for m in members), default=0.0) >= _CLUSTER_THRESHOLD
            for cq in corrected
        )
        online = has_correction or score >= AUTO_ONLINE_SCORE
        if key in existing:
            row = existing[key]
            row.framework = summary.get("framework") or row.framework
            row.intent = (str(summary.get("intent") or "").strip()[:255]) or row.intent
            row.sample_questions = members[:20]
            row.keywords = summary.get("keywords") or row.keywords
            row.member_count = len(members)
            row.success_criteria = criteria or row.success_criteria
            row.quality_score = score
            if row.status == "draft" and online:
                row.status = "active"
                auto_online += 1
        else:
            row = AskTemplate(
                id=generate_uuid(),
                data_source_id=str(data_source_id),
                name=name,
                intent=(str(summary.get("intent") or "").strip()[:255]) or None,
                framework=str(summary.get("framework") or "") or None,
                sample_questions=members[:20],
                keywords=summary.get("keywords") or [],
                member_count=len(members),
                status="active" if online else "draft",
                source="auto",
                success_criteria=criteria,
                quality_score=score,
            )
            db.add(row)
            existing[key] = row
            if online:
                auto_online += 1
        produced += 1

    await db.flush()
    logger.info(
        "mine_templates ds=%s produced=%s auto_online=%s questions=%s",
        data_source_id, produced, auto_online, len(questions),
    )
    return {
        "templates": produced,
        "questions": len(questions),
        "auto_online": auto_online,
        "auto_online_score": AUTO_ONLINE_SCORE,
    }
