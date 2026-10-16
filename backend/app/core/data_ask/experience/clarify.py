"""Ask a follow-up when the metric or the time range is ambiguous. Otherwise stay silent."""
from __future__ import annotations

import re
from typing import Any

_VAGUE_TIME = re.compile(
    r"(最近|近期|近来|上月|本月|这个月|今年|去年|上周|本周|昨天|今天|近一年|近一个月|近一周|这段时间|前几天)"
)
_CONCRETE_TIME = re.compile(
    r"((19|20)\d{2}|\d{1,2}\s*月|\d{4}[-/.]\d{1,2}|第[一二三四1234]季度|Q[1-4]"
    # 「最近/近/过去 N 天(日/周/月/年)」是可解析的相对区间（锚定数据最新日期），
    # 不属于时间不明，不应触发澄清。
    r"|(?:最近|近|过去)\s*[0-9一二三四五六七八九十两]+\s*(?:天|日|周|月|年))",
    re.IGNORECASE,
)
_DATE_TYPE = ("date", "time", "timestamp", "datetime")
_DATE_NAME = ("日期", "时间", "date", "time", "year", "month", "年份", "月份")


def clarification_for(
    question: str,
    tables: list[dict[str, Any]] | None,
    semantic_model: dict[str, Any] | None,
) -> str | None:
    text = (question or "").strip()
    if not text:
        return None
    metrics = ambiguous_metrics(text, semantic_model)
    if len(metrics) >= 2:
        shown = "、".join(metrics[:4])
        return f"有多个可能的指标：{shown}。请说明要看哪一个。"
    if _VAGUE_TIME.search(text) and not _CONCRETE_TIME.search(text) and _has_date_column(tables):
        return "时间范围还不明确。请补充具体的日期或日期区间（例如「2026-10-01 到 2026-10-11」）。"
    return None


def ambiguous_metrics(question: str, semantic_model: dict[str, Any] | None) -> list[str]:
    """仅当问题里精确出现多个完整指标名时才判定歧义。

    规则：
    - 精确匹配：指标名完整出现在问题中。
    - 若多个匹配项互为子串（如"毛利" ⊂ "毛利率"），只保留最具体（最长）的那个。
    - 不做激进的前缀模糊匹配，避免"销售"这类通用词误命中
      "销售金额/销售成本/销售数量"而误触发澄清。
    """
    names = _metric_names(semantic_model)
    if len(names) < 2:
        return []
    full = [name for name in names if name in question]
    if len(full) > 1:
        full = [n for n in full if not any(n != m and n in m for m in full)]
    return full


def _metric_names(model: dict[str, Any] | None) -> list[str]:
    names: list[str] = []
    for metric in (model or {}).get("metrics") or []:
        if not isinstance(metric, dict):
            continue
        name = str(metric.get("name") or "").strip()
        if len(name) >= 2:
            names.append(name)
    return names


def _has_date_column(tables: list[dict[str, Any]] | None) -> bool:
    for table in tables or []:
        for column in table.get("columns") or []:
            if isinstance(column, str):
                name, typ = column, ""
            elif isinstance(column, dict):
                name = str(column.get("name") or "")
                typ = str(column.get("type") or "")
            else:
                continue
            folded_name = name.lower()
            folded_type = typ.lower()
            if any(token in folded_type for token in _DATE_TYPE):
                return True
            if any(token in folded_name for token in _DATE_NAME):
                return True
    return False
