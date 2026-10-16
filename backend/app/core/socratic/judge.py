"""L1 LLM 清晰度判定：结构化 JSON 输出 + 容错解析。

失败安全：任何异常返回 None（调用方回退直答）。
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.core.socratic.prompts import JUDGE_SYSTEM

_MIN_CONFIDENCE = 0.7


async def judge_clarity(question: str, context: str | None = None) -> dict[str, Any] | None:
    """返回 {"clarity","missing","askable","confidence"} 或 None（失败/不可判）。"""
    from app.models_hub.router import ModelRouter

    llm = await ModelRouter.get_llm(temperature=0.1)
    user = question if not context else f"[会话上下文]\n{context}\n\n[当前问题]\n{question}"
    try:
        resp = await llm.ainvoke(
            [{"role": "system", "content": JUDGE_SYSTEM},
             {"role": "user", "content": user}])
        data = _parse_json(getattr(resp, "content", ""))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    clarity = str(data.get("clarity") or "").strip().lower()
    if clarity not in ("clear", "ambiguous", "underspecified"):
        return None
    try:
        confidence = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0
    if clarity != "clear" and confidence < _MIN_CONFIDENCE:
        return None  # 判定不自信 → 放行直答
    return {
        "clarity": clarity,
        "missing": _str_list(data.get("missing")),
        "askable": _askable_list(data.get("askable")),
        "confidence": confidence,
    }


def _parse_json(text: str) -> Any:
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _str_list(v: Any) -> list[str]:
    if not isinstance(v, list):
        return []
    return [str(x) for x in v if x][:6]


def _askable_list(v: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(v, list):
        return out
    for item in v:
        if not isinstance(item, dict):
            continue
        q = str(item.get("q") or item.get("text") or "").strip()
        if not q:
            continue
        out.append({
            "q": q,
            "options": _str_list(item.get("options"))[:4],
            "why": str(item.get("why") or "").strip(),
        })
    return out[:2]
