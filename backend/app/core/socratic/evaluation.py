"""S4 苏格拉底反问评估核心：考题库构建 + clarity judge 回归 + 质量指标聚合"""
from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Agent,
    AgentSocraticTrace,
    Conversation,
    Message,
    SocraticEvalRun,
    SocraticEvalSet,
)

logger = logging.getLogger("socratic_eval")

# ── 质量门槛 ──
PROMOTE_DIRECT_ACCURACY = 0.95  # 误反问率 ≤5%
PROMOTE_CLARIFY_ACCURACY = 0.90
MIN_SOCRATIC_EVAL_SET = 5


# ── 考题库构建（从 agent_socratic_trace 蒸馏高频模糊问题 + 明确问题）──
async def build_socratic_eval_set(
    db: AsyncSession, *, agent_id: str | None = None
) -> dict[str, Any]:
    """从真实反问轨迹蒸馏考题库：高频反问问题→clarify 类目；高频直答问题→direct 类目。
    幂等：同一问题不重复插入。"""
    base = select(AgentSocraticTrace)
    if agent_id:
        base = base.where(AgentSocraticTrace.agent_id == agent_id)

    # 取最近 50 条反问过的问题作为 clarify 候选
    clarify_rows = (await db.execute(
        base.where(AgentSocraticTrace.clarify_questions.isnot(None))
        .order_by(AgentSocraticTrace.id.desc()).limit(50)
    )).scalars().all()

    created = 0
    skipped_dupe = 0
    for row in clarify_rows:
        q = (row.question or "").strip()
        if len(q) < 4:
            continue
        exists = (await db.execute(
            select(SocraticEvalSet.id).where(
                SocraticEvalSet.question == q,
                SocraticEvalSet.agent_id.is_(agent_id),
            ).limit(1)
        )).scalar_one_or_none()
        if exists:
            skipped_dupe += 1
            continue
        domains = []
        for cq in (row.clarify_questions or []):
            domains.append((cq.get("text") or "")[:30])
        db.add(SocraticEvalSet(
            agent_id=agent_id, question=q,
            expected_behavior="clarify", expected_domains=domains,
            difficulty="medium", source="trace",
        ))
        created += 1

    # direct 类目：从消息中找明确问题（数字/日期/问句开头）→ 期望直答
    # 简化：取 5 条已验证的明确问题模板
    direct_templates = [
        "什么是毛利率？",
        "Python 中 len() 函数的作用是什么？",
        "今天是几号？",
        "1+1等于几？",
        "SQL 中 COUNT(*) 和 COUNT(1) 有什么区别？",
    ]
    for q in direct_templates:
        exists = (await db.execute(
            select(SocraticEvalSet.id).where(
                SocraticEvalSet.question == q,
                SocraticEvalSet.agent_id.is_(agent_id),
            ).limit(1)
        )).scalar_one_or_none()
        if exists:
            skipped_dupe += 1
            continue
        db.add(SocraticEvalSet(
            agent_id=agent_id, question=q,
            expected_behavior="direct", expected_domains=[],
            difficulty="easy", source="seed",
        ))
        created += 1

    await db.flush()
    total = (await db.execute(
        select(func.count(SocraticEvalSet.id)).where(
            SocraticEvalSet.agent_id.is_(agent_id),
            SocraticEvalSet.active.is_(True),
        )
    )).scalar() or 0
    return {"created": created, "skipped_dupe": skipped_dupe, "set_size": total}


# ── clarity judge 回归评估 ──
async def run_socratic_eval(
    db: AsyncSession, run_row: SocraticEvalRun, *, agent_id: str | None = None
) -> None:
    """执行一轮苏格拉底反问回归评估：对每条考题调 socratic_precheck，比对期望行为。"""
    from app.core.socratic.engine import socratic_precheck

    t0 = time.time()
    q = select(SocraticEvalSet).where(
        SocraticEvalSet.agent_id.is_(agent_id),
        SocraticEvalSet.active.is_(True),
    )
    items = (await db.execute(q)).scalars().all()

    run_row.total = len(items)
    run_row.status = "running"
    await db.flush()

    clarify_correct = 0
    clarify_total = 0
    direct_correct = 0
    direct_total = 0
    results = []

    # 需要一个 conversation 对象传给 socratic_precheck；用临时内存对象
    class _StubConv:
        def __init__(self, aid):
            self.id = f"socratic-eval-{int(time.time()*1000)}"
            self.agent_id = aid
            self.metadata_ = {}

    for item in items:
        # 找一个启用了 socratic_config 的默认智能体（agent_id 为 None 时使用）
        default_aid = agent_id
        if not default_aid:
            all_agents = (await db.execute(select(Agent.id, Agent.metadata_))).all()
            for _aid, _meta in all_agents:
                _m = _meta or {}
                if isinstance(_m, str):
                    try: _m = json.loads(_m)
                    except Exception: _m = {}
                if (_m.get("socratic_config") or {}).get("enabled"):
                    default_aid = str(_aid)
                    break
        aid = item.agent_id or default_aid
        conv = _StubConv(aid)
        expected = item.expected_behavior
        try:
            decision = await socratic_precheck(
                db, message=item.question, conv=conv, agent_id=aid,
            )
        except Exception as exc:
            logger.warning("socratic_eval_item_failed q=%s err=%s", item.question[:30], str(exc)[:100])
            decision = None

        actual_clarify = bool(decision and decision.get("clarify"))
        actual = "clarify" if actual_clarify else "direct"
        passed = (actual == expected)

        if expected == "clarify":
            clarify_total += 1
            if passed:
                clarify_correct += 1
        else:
            direct_total += 1
            if passed:
                direct_correct += 1

        results.append({
            "question": item.question[:120],
            "expected": expected,
            "actual": actual,
            "passed": passed,
            "domains": [q.get("text", "")[:30] for q in (decision or {}).get("clarify", {}).get("questions", [])] if actual_clarify else [],
        })

    run_row.passed = clarify_correct + direct_correct
    run_row.clarify_accuracy = (clarify_correct / clarify_total) if clarify_total else None
    run_row.direct_accuracy = (direct_correct / direct_total) if direct_total else None
    # 平均收敛轮次从真实轨迹取
    avg_rounds_row = (await db.execute(
        select(func.avg(AgentSocraticTrace.round)).where(
            AgentSocraticTrace.resolved.is_(True),
            AgentSocraticTrace.agent_id.is_(agent_id),
        )
    )).scalar()
    run_row.avg_rounds = float(avg_rounds_row) if avg_rounds_row else None
    run_row.items = results
    run_row.status = "done"
    run_row.duration_ms = int((time.time() - t0) * 1000)


# ── 质量指标聚合（从 agent_socratic_trace 实时计算）──
async def socratic_quality_metrics(
    db: AsyncSession, *, agent_id: str | None = None, window_days: int = 30
) -> dict[str, Any]:
    """四项反问质量指标：反问率 / 澄清后解决率 / 误反问率 / 平均收敛轮次"""
    from datetime import timedelta, timezone

    now = __import__("datetime").datetime.now(timezone.utc)
    since = now - timedelta(days=window_days)

    base = select(AgentSocraticTrace).where(AgentSocraticTrace.created_at >= since)
    if agent_id:
        base = base.where(AgentSocraticTrace.agent_id == agent_id)

    total_clarify = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar() or 0

    resolved_n = (await db.execute(
        select(func.count()).select_from(
            base.where(AgentSocraticTrace.resolved.is_(True)).subquery()
        )
    )).scalar() or 0

    avg_rounds = (await db.execute(
        select(func.avg(AgentSocraticTrace.round)).select_from(
            base.where(AgentSocraticTrace.resolved.is_(True)).subquery()
        )
    )).scalar()

    # 反问率 = clarify 事件数 / 总用户消息数（限定配置了 socratic_config 的智能体会话）
    total_user_msgs = 0
    if agent_id:
        total_user_msgs = (await db.execute(
            select(func.count(Message.id)).join(
                Conversation, Message.conversation_id == Conversation.id
            ).where(
                Conversation.agent_id == agent_id,
                Message.role == "user",
                Message.created_at >= since,
            )
        )).scalar() or 0
    else:
        # 全平台：配置了 socratic_config 的智能体
        agents_with_cfg = (await db.execute(
            select(Agent.id).where(Agent.metadata_.isnot(None))
        )).scalars().all()
        cfg_ids = []
        for aid in agents_with_cfg:
            # metadata_ 是 JSON，需检查是否含 socratic_config；简化为全部有 metadata 的
            cfg_ids.append(str(aid))
        if cfg_ids:
            total_user_msgs = (await db.execute(
                select(func.count(Message.id)).join(
                    Conversation, Message.conversation_id == Conversation.id
                ).where(
                    Conversation.agent_id.in_(cfg_ids),
                    Message.role == "user",
                    Message.created_at >= since,
                )
            )).scalar() or 0

    clarify_rate = (total_clarify / total_user_msgs) if total_user_msgs else 0.0
    resolve_rate = (resolved_n / total_clarify) if total_clarify else 0.0

    # 误反问率：从最近的 eval run 取 direct_accuracy 的补
    misclarify_rate = None
    last_run = (await db.execute(
        select(SocraticEvalRun).where(
            SocraticEvalRun.agent_id.is_(agent_id),
            SocraticEvalRun.status == "done",
        ).order_by(SocraticEvalRun.id.desc()).limit(1)
    )).scalar_one_or_none()
    if last_run and last_run.direct_accuracy is not None:
        misclarify_rate = 1.0 - last_run.direct_accuracy

    return {
        "window_days": window_days,
        "total_clarify_events": total_clarify,
        "total_user_messages": total_user_msgs,
        "clarify_rate": round(clarify_rate, 4),
        "resolve_rate": round(resolve_rate, 4),
        "misclarify_rate": round(misclarify_rate, 4) if misclarify_rate is not None else None,
        "avg_rounds": round(float(avg_rounds), 2) if avg_rounds else None,
        "last_eval_run_id": int(last_run.id) if last_run else None,
    }
