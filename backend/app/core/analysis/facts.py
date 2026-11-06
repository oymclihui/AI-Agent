"""分析事实生成：所有结论性文字都必须能指回结果字段。"""
from __future__ import annotations

from typing import Any


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "是" if value else "否"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num.is_integer():
        return f"{num:,.0f}"
    return f"{num:,.2f}"


def _col_index(columns: list[str], name: str) -> int | None:
    for i, c in enumerate(columns):
        if str(c) == name:
            return i
    return None


def build_facts(spec: dict[str, Any], columns: list[str], rows: list[list[Any]]) -> list[dict[str, str]]:
    if not rows:
        return [{"text": "查询结果为空", "from": "rows.length=0"}]

    facts: list[dict[str, str]] = []
    stype = spec["type"]
    metrics = spec.get("metrics") or []

    if stype == "aggregate":
        for m in metrics:
            idx = _col_index(columns, m["alias"])
            if idx is None:
                continue
            facts.append({
                "text": f"{m['name']} 为 {_fmt(rows[0][idx])}",
                "from": f"rows[0][{idx}]",
            })
        return facts or [{"text": f"共返回 {len(rows)} 行", "from": "rows.length"}]

    if stype == "timeseries":
        time_idx = 0
        for m in metrics:
            idx = _col_index(columns, m["alias"])
            if idx is None:
                continue
            values = [(i, r[time_idx], r[idx]) for i, r in enumerate(rows) if r[idx] is not None]
            if not values:
                continue
            hi = max(values, key=lambda x: float(x[2]))
            lo = min(values, key=lambda x: float(x[2]))
            facts.append({
                "text": f"{m['name']} 最高为 {hi[1]} 的 {_fmt(hi[2])}",
                "from": f"rows[{hi[0]}][{idx}]",
            })
            if len(values) > 1:
                facts.append({
                    "text": f"{m['name']} 最低为 {lo[1]} 的 {_fmt(lo[2])}",
                    "from": f"rows[{lo[0]}][{idx}]",
                })
        return facts or [{"text": f"共 {len(rows)} 个时间点", "from": "rows.length"}]

    if stype in ("distribution", "topn"):
        dim_idx = 0
        metric_idx = _col_index(columns, metrics[0]["alias"]) if metrics else None
        if metric_idx is not None:
            top = rows[0]
            facts.append({
                "text": f"{top[dim_idx]} 的{metrics[0]['name']}最高，为 {_fmt(top[metric_idx])}",
                "from": f"rows[0][{metric_idx}]",
            })
            if len(rows) > 1:
                last = rows[-1]
                facts.append({
                    "text": f"{last[dim_idx]} 的{metrics[0]['name']}最低，为 {_fmt(last[metric_idx])}",
                    "from": f"rows[{len(rows)-1}][{metric_idx}]",
                })
        return facts or [{"text": f"共 {len(rows)} 个分组", "from": "rows.length"}]

    return [{"text": f"共返回 {len(rows)} 行明细", "from": f"rows.length={len(rows)}"}]
