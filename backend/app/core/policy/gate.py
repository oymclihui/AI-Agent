"""确定性准入(Gate) — 把一个触发判成强度与去向，并在接受时授予 Mandate。

本阶段只做**确定性**判定（基于允许名单、是否 @ 机器人、是否 bot）；
「推断候选」的模型研判(Assessment)与真正的执行留待 Phase 3。调用方（入库）要求本函数
绝不抛异常，失败只记日志并返回 None。
"""
from __future__ import annotations

import structlog

from app.db.models import SuperagentDecision, SuperagentMandate, SuperagentTrigger

logger = structlog.get_logger(__name__)


async def evaluate_gate(
    db,
    trigger: SuperagentTrigger,
    *,
    addressed: bool = True,
    is_bot: bool = False,
) -> dict | None:
    """在给定会话内评估一个已入库的触发，写入 Decision（必要时写 Mandate）。

    返回判定摘要 dict，或在跳过/失败时返回 None。不提交（由调用方提交）。
    """
    try:
        from app.core.policy.service import (
            PERSON_SOURCE_KINDS,
            ensure_default_policy,
            get_current_policy,
            get_policy_source,
        )

        if trigger.source_kind not in PERSON_SOURCE_KINDS:
            return None  # schedule 等系统触发不过 Gate

        await ensure_default_policy()
        policy = await get_current_policy(db)
        src = await get_policy_source(db, policy, trigger.source_kind)
        allowlist = (src.allowlist if src else []) or []
        bot_list = (src.bot_list if src else []) or []
        actor = trigger.actor or ""

        if is_bot or actor.endswith("[bot]"):
            strength = "inferred" if actor in bot_list else "not_admitted"
        else:
            allowed = actor in allowlist
            if allowed and addressed:
                strength = "explicit"
            elif allowed and not addressed:
                strength = "inferred"
            else:
                strength = "not_admitted"

        mode = policy.accept_mode
        matched_rules: list = []  # Phase 3：研判填入命中规则

        if strength == "explicit":
            decision, reason = "accept", "allowlisted sender addressed the agent"
        elif strength == "inferred":
            if mode == "off":
                decision, reason = "ignore", "inferred candidate; accept mode off"
            elif mode == "auto":
                decision, reason = "accept", "inferred candidate accepted under auto mode"
            else:  # observe (default)
                decision, reason = "would_accept", "inferred candidate; observe mode records only"
        else:
            decision, reason = "ignore", "not admitted by policy"

        mandate_id = None
        if decision == "accept":
            mandate = SuperagentMandate(
                trigger_id=trigger.id,
                thread_id=trigger.thread_id,
                policy_version=policy.version,
                source_kind=trigger.source_kind,
                originator=actor or None,
                strength=strength,
                matched_rules=matched_rules,
            )
            db.add(mandate)
            await db.flush()
            mandate_id = mandate.id

        db.add(
            SuperagentDecision(
                trigger_id=trigger.id,
                thread_id=trigger.thread_id,
                policy_version=policy.version,
                source_kind=trigger.source_kind,
                strength=strength,
                decision=decision,
                mandate_id=mandate_id,
                reason=reason[:255],
            )
        )
        return {
            "strength": strength,
            "decision": decision,
            "mandate_id": mandate_id,
            "policy_version": policy.version,
        }
    except Exception as exc:  # 入库要求绝不因 Gate 失败而中断
        logger.warning(
            "superagent_gate_failed",
            trigger_id=getattr(trigger, "id", None),
            error=str(exc),
        )
        return None
