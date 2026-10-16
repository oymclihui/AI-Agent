"""苏格拉底提问引擎：编排 L0/L1 判定、提问生成与会话状态。

入口 socratic_precheck(db, *, message, conv, agent_id) -> dict | None：
  None            —— 放行直答（清晰/未启用/判定失败/超限）
  {"clarify": payload, "message": final_message}
                    —— 需反问：payload 为前端渲染协议；
                       放行时调用方用替换后的 message 继续原流程。

编排策略：L0 clear 直通；其余统一走 L1 judge（judge 的 askable 质量高，
作为提问生成的兜底素材）；L1 失败一律直答（失败安全）。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.core.socratic.gate import rule_clarity
from app.core.socratic.prompts import ASK_SYSTEM

logger = logging.getLogger(__name__)

_STATE_KEY = "socratic_state"
_DEFAULT_MAX_QUESTIONS = 2
_DEFAULT_MAX_ROUNDS = 3


def load_config(agent_meta: dict[str, Any] | None) -> dict[str, Any]:
    cfg = ((agent_meta or {}).get("socratic_config") or {})
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "mode": str(cfg.get("mode") or "guided").lower(),
        "max_questions": int(cfg.get("max_questions") or _DEFAULT_MAX_QUESTIONS),
        "max_rounds": int(cfg.get("max_rounds") or _DEFAULT_MAX_ROUNDS),
        "tone": str(cfg.get("tone") or "professional"),
        "ask_domains": [str(x) for x in (cfg.get("ask_domains") or [])][:8],
    }


async def socratic_precheck(
    db: Any,
    *,
    message: str,
    conv: Any,
    agent_id: str | None,
) -> dict[str, Any] | None:
    agent = await db.get(_agent_cls(), agent_id) if agent_id else None
    if agent is None:
        return None
    cfg = load_config(getattr(agent, "metadata_", None))
    if not cfg["enabled"] or cfg["mode"] == "off":
        return None

    meta = conv.metadata_ or {}
    state = dict(meta.get(_STATE_KEY) or {})
    rounds = int(state.get("rounds") or 0)
    pending_q = state.get("pending_q") or ""
    original = state.get("original_message") or ""

    # 这是用户对反问的回复：合并上下文后重新判定
    judge_question = message
    context = None
    if pending_q and original:
        judge_question = f"{original}（用户补充说明：{message}）"
        context = f"此前问题：{original}\n此前反问：{pending_q}\n用户回复：{message}"

    # L0 规则快判
    if rule_clarity(judge_question) == "clear":
        _clear_state(conv)
        if pending_q:
            try:
                from sqlalchemy import update as _sa_update
                from app.db.models import AgentSocraticTrace
                await db.execute(
                    _sa_update(AgentSocraticTrace)
                    .where(AgentSocraticTrace.conversation_id == str(getattr(conv, "id", "")))
                    .values(resolved=True))
            except Exception:
                logger.exception("socratic_trace_resolve_failed")
        return None

    # 超轮次上限 → 放行直答（防审讯）
    if rounds >= cfg["max_rounds"]:
        _clear_state(conv)
        return None

    # L1 LLM 统一判定（失败/不自信 → 直答）
    verdict = await _judge(judge_question, context)
    if verdict is not None and verdict["clarity"] == "clear":
        _clear_state(conv)
        if pending_q:
            # 澄清完成：标记轨迹已收敛 + 用「原问题+澄清答案」的增强问题继续原流程
            try:
                from sqlalchemy import update as _sa_update
                from app.db.models import AgentSocraticTrace
                await db.execute(
                    _sa_update(AgentSocraticTrace)
                    .where(AgentSocraticTrace.conversation_id == str(getattr(conv, "id", "")))
                    .values(resolved=True))
            except Exception:
                logger.exception("socratic_trace_resolve_failed")
            return {"clarify": None, "message": judge_question}
        return None
    if verdict is None:
        return None

    # 生成反问 payload（LLM 生成 → judge askable → ask_domains 模板，三层兜底）
    payload = await _build_ask(judge_question, verdict, cfg, original)
    if not payload:
        return None

    new_rounds = rounds + 1 if pending_q else 1
    if not _save_state(conv, {
        "rounds": new_rounds,
        "pending_q": json.dumps(payload["questions"], ensure_ascii=False),
        "original_message": original or message,
    }):
        return None  # 状态写失败 → 放行直答，绝不阻塞

    return {"clarify": {**payload, "round": new_rounds, "max_rounds": cfg["max_rounds"]},
            "message": message}


def _agent_cls():
    from app.db.models import Agent
    return Agent


async def _judge(question: str, context: str | None):
    try:
        from app.core.socratic.judge import judge_clarity
        return await judge_clarity(question, context)
    except Exception:
        logger.exception("socratic_judge_failed")
        return None


async def _build_ask(
    question: str,
    verdict: dict[str, Any],
    cfg: dict[str, Any],
    original: str,
) -> dict[str, Any] | None:
    askable = verdict.get("askable") or []
    missing = verdict.get("missing") or []

    # 1) LLM 生成引导式提问
    try:
        from app.models_hub.router import ModelRouter
        llm = await ModelRouter.get_llm(temperature=0.3)
        user = (
            f"用户问题：{original or question}\n"
            f"缺失维度：{('、'.join(missing)) or '未明确'}\n"
            f"判定器建议的问题点：{json.dumps(askable, ensure_ascii=False)}"
        )
        resp = await llm.ainvoke(
            [{"role": "system", "content": ASK_SYSTEM},
             {"role": "user", "content": user}])
        from app.core.socratic.judge import _parse_json
        data = _parse_json(getattr(resp, "content", ""))
        if isinstance(data, dict) and isinstance(data.get("questions"), list):
            qs = [
                {"text": str(q.get("text") or q.get("q") or "").strip(),
                 "options": [str(o) for o in (q.get("options") or [])][:4],
                 "why": str(q.get("why") or "").strip()}
                for q in data["questions"]
                if isinstance(q, dict) and str(q.get("text") or q.get("q") or "").strip()
            ][: cfg["max_questions"]]
            if qs:
                fb = str(data.get("fallback") or "").strip()
                return {"questions": qs, "fallback": fb}
            logger.info("socratic_ask_empty_questions")
    except Exception:
        logger.exception("socratic_ask_llm_failed")

    # 2) judge askable 模板转换（质量高，优先级仅次于 LLM 生成）
    qs = [
        {"text": a["q"], "options": a["options"], "why": a["why"]}
        for a in askable if a.get("q")
    ][: cfg["max_questions"]]
    if qs:
        return {"questions": qs, "fallback": ""}

    # 3) ask_domains 通用模板兜底
    doms = cfg.get("ask_domains")
    if doms:
        return {"questions": [
            {"text": f"为了更精准地回答，请先明确：{'、'.join(doms[:2])}？",
             "options": [], "why": "这些信息决定分析口径"},
        ], "fallback": "如果不确定，我将按常见口径直接分析。"}
    return None


def _clear_state(conv: Any) -> None:
    try:
        meta = dict(conv.metadata_ or {})
        if _STATE_KEY in meta:
            meta.pop(_STATE_KEY)
            conv.metadata_ = meta
    except Exception:
        pass


def _save_state(conv: Any, state: dict[str, Any]) -> bool:
    try:
        meta = dict(conv.metadata_ or {})
        meta[_STATE_KEY] = state
        conv.metadata_ = meta
        return True
    except Exception:
        logger.exception("socratic_state_save_failed")
        return False
