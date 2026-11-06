"""Pick a chart from result columns instead of assuming column 0 is the category."""
from __future__ import annotations

import re
from typing import Any

_MONTH = r"(0?[1-9]|1[0-2])"
_DAY = r"(0?[1-9]|[12]\d|3[01])"
_YEAR = r"(19|20)\d{2}"
# 年份只认 19xx/20xx，月份必须落在 1-12：否则「5869.00」这类金额、或「3335」这类四位整数指标
# 都会被当成时间轴，图表语义完全错位。
_TIME_VALUE = re.compile(
    r"^(" + _YEAR + r"([-/]" + _MONTH + r"([-/]" + _DAY + r")?)?"
    r"|" + _YEAR + r"年" + _MONTH + r"月(\d{1,2}日)?"
    r"|" + _MONTH + r"月(\d{1,2}日)?"
    r"|" + _YEAR + r"Q[1-4])$",
    re.IGNORECASE,
)
_TIME_NAME = ("year", "date", "month", "time", "quarter", "日期", "时间", "季度", "月份", "年份")
_SHARE = ("占比", "比例", "分布", "构成", "share", "distribut", "proportion", "结构")
_RANK = ("排名", "rank", "top", "前几", "最高", "最低", "最多", "最少", "榜")
_LIMIT = 15
_TIME_LIMIT = 60


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

    question_text = question or ""
    axis_is_time = kinds[cat_idx] == "time"
    if axis_is_time:
        # 时间轴按 SQL 的时序取前 60 个点（日/周序列常见 46+ 点，15 个点会丢趋势）
        window = rows[:_TIME_LIMIT]
    elif len(number_idxs) == 1:
        # 单指标分类图：按数值降序取 Top 15，保证「图表顺序 = 指标大小」；
        # 用户问最低/最少时改为升序。
        ascending = _has(question_text, ("最低", "最少", "倒数", "bottom"))
        window = sorted(
            rows,
            key=lambda row: _as_float(_cell(row, number_idxs[0])),
            reverse=not ascending,
        )[:_LIMIT]
    else:
        window = rows[:_LIMIT]

    labels = [str(_cell(row, cat_idx) if _cell(row, cat_idx) is not None else "") for row in window]
    datasets = []
    for idx in number_idxs:
        datasets.append({
            "label": str(columns[idx]),
            "data": [_as_float(_cell(row, idx)) for row in window],
        })

    chart_type = "bar"
    horizontal = False
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
    chart["title"] = _short_title(chart)
    return chart


def _short_title(chart: dict[str, Any]) -> str:
    """图表标题只写一行短标签。facts（逐点数值）留给 L3 提示词，不当作标题展示。"""
    names = [str(d.get("label") or "") for d in (chart.get("datasets") or []) if d.get("label")]
    series = "、".join(names[:2]) + ("等" if len(names) > 2 else "") or "数值"
    kind = chart.get("type")
    if kind == "line":
        return f"{series}趋势"
    if kind == "pie":
        return f"{series}占比"
    return f"{series}对比"


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
