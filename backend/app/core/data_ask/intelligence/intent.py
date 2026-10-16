"""Follow-up rewrite and lightweight intent for data ask."""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.models_hub.router import ModelRouter

_FOLLOWUP = re.compile(
    r"(刚才|同上|这个|同样|改成|换成|继续|上面|上述|前一个|按这个|呢$|^那|再看|再按)"
)
_FORECAST = ("预测", "predict", "forecast", "未来", "下月", "下周", "明年", "预估")


def looks_like_followup(question: str, history: list[dict[str, Any]] | None) -> bool:
    if not history:
        return False
    text = (question or "").strip()
    if not text:
        return False
    if len(text) <= 6:
        return True
    return bool(_FOLLOWUP.search(text))


def is_forecast_question(question: str) -> bool:
    folded = (question or "").lower()
    return any(word in folded for word in _FORECAST)


def _history_block(history: list[dict[str, Any]] | None) -> str:
    lines: list[str] = []
    for turn in (history or [])[-6:]:
        role = str(turn.get("role") or "user")
        content = " ".join(str(turn.get("content") or "").split())[:400]
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


async def rewrite_question(
    db: AsyncSession,
    *,
    question: str,
    history: list[dict[str, Any]] | None,
    llm_provider: str | None,
    llm_model: str | None,
    user_id: str | None = None,
) -> str:
    """Expand a follow-up into a standalone question. Original text is kept on failure."""
    original = (question or "").strip()
    if not looks_like_followup(original, history):
        return original
    system = (
        "You rewrite the latest user question into one standalone data question in the user's language.\n"
        "Use prior turns only to resolve references such as time, metric, or filter.\n"
        "Do not answer the question and do not invent tables or metrics that were not mentioned.\n"
        'Return JSON: {"question": "..."}'
    )
    user = f"History:\n{_history_block(history)}\n\nLatest question: {original}"
    llm = await ModelRouter.get_llm(
        db=db,
        provider=llm_provider,
        model=llm_model,
        user_id=user_id,
        response_style="precise",
    )
    resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    rewritten = ""
    try:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            rewritten = str(json.loads(match.group()).get("question") or "").strip()
    except json.JSONDecodeError:
        rewritten = ""
    if not rewritten or len(rewritten) > 500:
        return original
    return rewritten
