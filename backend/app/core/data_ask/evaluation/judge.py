"""LLM-as-judge：答案质量评分（走 ModelRouter → LiteLLM 统一网关，纳入用量统计）。

只对 SQL 已成功执行的题目评分；judge 失败（网关异常/解析失败）返回 None，
该题不计入 judge 均分，绝不用假分填充。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("agent_eval_judge")

_SYSTEM = (
    "你是问数质量评审专家。给定用户的自然语言问题、系统生成的 SQL、以及 SQL 执行返回的"
    "列名与前 5 行数据，请评判这次回答的质量。\n"
    "评分维度：SQL 是否准确回应了问题意图、结果列与问题关注点是否匹配、数据形态是否合理可读。\n"
    "只依据给出的信息评判，不要编造字段或数据。\n"
    '返回 JSON：{"score": 0到10的数值, "reason": "一句话理由"}\n'
    "评分锚点：9-10 完全切题且结果清晰；6-8 基本切题有瑕疵；3-5 偏离问题或结果难用；0-2 答非所问。"
)


async def judge_answer(
    db: AsyncSession,
    *,
    question: str,
    sql: str | None,
    columns: list[Any],
    rows_sample: list[Any],
) -> dict[str, Any] | None:
    """对一次问数结果打 0-10 分。失败返回 None（不计入均分）。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.models_hub.router import ModelRouter

    preview_rows = rows_sample[:5] if isinstance(rows_sample, list) else []
    user = (
        f"问题: {(question or '')[:500]}\n"
        f"生成 SQL: {(sql or '')[:1200]}\n"
        f"结果列: {json.dumps([str(c) for c in (columns or [])][:30], ensure_ascii=False)}\n"
        f"前 5 行: {json.dumps(preview_rows, ensure_ascii=False, default=str)[:2000]}"
    )
    try:
        llm = await ModelRouter.get_llm(db=db, response_style="precise")
        resp = await llm.ainvoke([SystemMessage(content=_SYSTEM), HumanMessage(content=user)])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
    except Exception as exc:
        logger.warning("judge_llm_failed err=%s", str(exc)[:200])
        return None

    match = re.search(r"\{[\s\S]*\}", text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group())
        score = float(data.get("score"))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    score = max(0.0, min(10.0, score))
    return {"score": score, "reason": str(data.get("reason") or "")[:300]}
