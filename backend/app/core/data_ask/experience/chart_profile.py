"""Pick a chart from result columns instead of assuming column 0 is the category."""
from __future__ import annotations

import re
from typing import Any

_TIME_VALUE = re.compile(
    r"^(\d{4}([-/年.]\d{1,2}([-/月.]\d{1,2}日?)?)?|\d{4}年|\d{1,2}月|\d{4}Q[1-4])$",
    re.IGNORECASE,
)
_TIME_NAME = ("year", "date", "month", "time", "quarter", "日期", "时间", "季度", "月份", "年份")
_SHARE = ("占比", "比例", "分布", "构成", "share", "distribut", "proportion", "结构")
_RANK = ("排名", "rank", "top", "前几", "最高", "最低", "最多", "最少", "榜")
_LIMIT = 15


def suggest_chart(columns: list[str], rows: list[list[Any]], question: str = "") -> dict[str, Any] | None:
    if not columns or not rows or len(columns) < 2:
        return None
    preview = rows[:_LIMIT]
    kinds = [_column_kind(columns[i], [_cell(row, i) for row in preview]) for i in range(len(columns))]
    summary = _summary_chart(columns, preview, kinds)
    if summary is not None:
        return summary
    cat_idx = next((i for i, kind in enumerate(kinds) if kind == "time"), None)
    if cat_idx is None:
        cat_idx = next((i for i, kind in enumerate(kinds) if kind == "category"), None)
    number_idxs = [i for i, kind in enumerate(kinds) if kind == "number" and i != cat_idx]
    if cat_idx is None or not number_idxs:
        return None

    labels = [str(_cell(row, cat_idx) if _cell(row, cat_idx) is not None else "") for row in preview]
    datasets = []
    for idx in number_idxs:
        datasets.append({
            "label": str(columns[idx]),
            "data": [_as_float(_cell(row, idx)) for row in preview],
        })

    question_text = question or ""
    chart_type = "bar"
    horizontal = False
    axis_is_time = kinds[cat_idx] == "time"
    if axis_is_time and len(labels) >= 2:
        chart_type = "line"
    elif (
        len(datasets) == 1
        and 2 <= len(labels) <= 7
        and _has(question_text, _SHARE)
        and all(value >= 0 for value in datasets[0]["data"])
    ):
        chart_type = "pie"
    elif _has(question_text, _RANK) or any(len(label) > 6 for label in labels):
        horizontal = True

    chart: dict[str, Any] = {
        "type": chart_type,
        "labels": labels,
        "values": datasets[0]["data"],
        "series": datasets[0]["label"],
        "datasets": datasets,
    }
    if horizontal and chart_type == "bar":
        chart["horizontal"] = True
    return _with_facts(chart)


def _summary_chart(
    columns: list[str],
    rows: list[list[Any]],
    kinds: list[str],
) -> dict[str, Any] | None:
    """One aggregate row is a set of indicators, not a category axis."""
    if len(rows) != 1:
        return None
    number_idxs = [index for index, kind in enumerate(kinds) if kind == "number"]
    if len(number_idxs) < 2:
        return None
    labels = [str(columns[index]) for index in number_idxs]
    values = [_as_float(_cell(rows[0], index)) for index in number_idxs]
    return _with_facts({
        "type": "bar",
        "labels": labels,
        "values": values,
        "series": "数值",
        "datasets": [{"label": "数值", "data": values}],
        "horizontal": any(len(label) > 8 for label in labels),
    })


def _with_facts(chart: dict[str, Any]) -> dict[str, Any]:
    chart["caption"] = chart_facts(chart)
    chart["title"] = chart["caption"]
    return chart


def chart_facts(chart: dict[str, Any] | None) -> str:
    """Read the plotted points back out. This is the only text the chart is allowed to claim."""
    if not chart:
        return ""
    labels = [str(label) for label in chart.get("labels") or []]
    datasets = chart.get("datasets") or []
    if not labels or not datasets:
        return ""
    if len(datasets) == 1:
        parts = [
            f"{label} {_fmt(datasets[0]['data'][index])}"
            for index, label in enumerate(labels)
            if index < len(datasets[0].get("data") or [])
        ]
        return "、".join(parts)
    parts = []
    for index, label in enumerate(labels):
        bits = []
        for dataset in datasets:
            data = dataset.get("data") or []
            if index < len(data):
                bits.append(f"{dataset.get('label') or '数值'} {_fmt(data[index])}")
        if bits:
            parts.append(f"{label}（{'，'.join(bits)}）")
    return "；".join(parts)


def _fmt(value: Any) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return format(number, "f").rstrip("0").rstrip(".")


def _cell(row: list[Any], index: int) -> Any:
    return row[index] if index < len(row) else None


def _column_kind(name: str, values: list[Any]) -> str:
    present = [value for value in values if value is not None and str(value).strip() != ""]
    if not present:
        return "empty"
    texts = [str(value).strip() for value in present]
    time_hits = sum(
        1 for text in texts if _TIME_VALUE.match(text) or "年" in text or _is_year(text) or _is_datetime(text)
    )
    if time_hits >= max(1, int(len(texts) * 0.6)):
        return "time"
    if _name_is_time(name) and time_hits >= 1:
        return "time"
    if sum(1 for value in present if _is_number(value)) >= max(1, int(len(present) * 0.8)):
        return "number"
    return "category"


def _name_is_time(name: str) -> bool:
    lowered = (name or "").lower()
    return any(token in lowered for token in _TIME_NAME)


def _is_year(value: Any) -> bool:
    return bool(re.fullmatch(r"(19|20)\d{2}", str(value).strip()))


def _is_datetime(value: Any) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}", str(value).strip()))


def _is_number(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    text = str(value).strip().replace(",", "")
    if not text:
        return False
    try:
        float(text)
        return True
    except ValueError:
        return False


def _as_float(value: Any) -> float:
    if not _is_number(value):
        return 0.0
    return float(str(value).strip().replace(",", ""))


def _has(question: str, words: tuple[str, ...]) -> bool:
    lowered = question.lower()
    return any(word in lowered for word in words)
