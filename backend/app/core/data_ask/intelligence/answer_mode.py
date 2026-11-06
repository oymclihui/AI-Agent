"""问数回答模式判定：L1 直答 / L2 表格 / L3 深度分析。

纯规则判定，不调用模型。输入问题文本 + 结果结构（列/行），输出回答形态。
分析词表支持三级扩展：内置默认 → 环境变量（租户级）→ 数据源 semantic_model.analysis_keywords。
"""
from __future__ import annotations

import os
import re
from typing import Any

MODE_DIRECT = "L1"
MODE_TABLE = "L2"
MODE_ANALYSIS = "L3"

# 命中即进入分析候选，再由「多行 / 多指标」二次确认
DEFAULT_ANALYSIS_KEYWORDS = (
    "分析", "原因", "为什么", "趋势", "对比", "同比", "环比",
    "异常", "下降", "上升", "建议", "如何", "怎么", "评估",
    "诊断", "问题", "优化",
)

# 租户级扩展：逗号 / 顿号 / 空格分隔的多词，部署时按需覆盖
_ENV_KEYWORDS = "DATA_ASK_ANALYSIS_KEYWORDS"

_NUMERIC_NAME_HINTS = ("金额", "笔数", "余额", "数量", "率", "额", "数", "量")


def _split_keywords(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        items = [str(v) for v in value]
    else:
        items = re.split(r"[,，、;；\s]+", str(value or ""))
    return [item.strip() for item in items if item and item.strip()]


def analysis_keywords(extra: Any = None) -> tuple[str, ...]:
    """合并默认词表、环境变量与数据源级扩展，保持顺序去重。"""
    merged = list(DEFAULT_ANALYSIS_KEYWORDS)
    merged += _split_keywords(os.getenv(_ENV_KEYWORDS, ""))
    merged += _split_keywords(extra)
    return tuple(dict.fromkeys(merged))


def keywords_from_semantic(semantic_model: Any) -> list[str]:
    """读取数据源语义模型里的 analysis_keywords（可选）。"""
    if not isinstance(semantic_model, dict):
        return []
    return _split_keywords(semantic_model.get("analysis_keywords"))


def _looks_numeric(name: str, rows: list[list[Any]], idx: int) -> bool:
    """优先看采样值的可解析性，其次看列名关键词。"""
    for row in (rows or [])[:5]:
        value = row[idx] if idx < len(row) else None
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        try:
            float(str(value).replace(",", ""))
            return True
        except (TypeError, ValueError):
            continue
    return any(hint in (name or "") for hint in _NUMERIC_NAME_HINTS)


def classify_answer_mode(
    question: str,
    columns: list[str] | None,
    rows: list[list[Any]] | None,
    extra_keywords: Any = None,
) -> str:
    """返回 L1 / L2 / L3。空结果一律 L1（短答说明无数据）。"""
    text = (question or "").strip()
    cols = [str(c) for c in (columns or [])]
    data = rows or []
    if not data:
        return MODE_DIRECT

    hit = any(keyword in text for keyword in analysis_keywords(extra_keywords))
    numeric = sum(1 for i, col in enumerate(cols) if _looks_numeric(col, data, i))
    text_cols = len(cols) - numeric

    if hit and (numeric >= 2 or len(data) >= 2):
        return MODE_ANALYSIS
    if hit:
        # 走到这里必是「单行且非多指标」：分析意图撑不起表格，
        # 降级为一句话直答，便于交代数据局限（如仅一家门店、无法对比）。
        return MODE_DIRECT
    if numeric >= 2:
        return MODE_TABLE
    if len(data) >= 2 and text_cols >= 1:
        return MODE_TABLE
    return MODE_DIRECT
