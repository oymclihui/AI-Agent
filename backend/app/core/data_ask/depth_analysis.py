"""深度分析：异常点识别 + 归因拆解 + 建议生成。纯规则优先，不调 LLM。

为什么不调 LLM：
- 回答必须基于真数，不能自由发挥
- LLM 还可能把数字看错或编理由。规则版 100% 基于实际查询结果
- 快、确定性、可调试
"""
from __future__ import annotations

from typing import Any


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def anomaly_points(
    columns: list[str],
    rows: list[list[Any]],
    *,
    min_change_pct: float = 5.0,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """找出各指标环比变动绝对值最大的项。

    输入 rows 期望是两列以上：[当前值, 对比值] 或 [分组, 当前值, 对比值]。
    更通用做法：对 rows 的每一行，找所有数值列，计算行内最大绝对值变动。
    简化：接收 columns + rows 假定行是 [分组, 当前指标1, 对比指标1, 当前指标2, 对比指标2, ...]
    """
    if not rows or not columns:
        return []
    # 纯简化：columns 是分组+指标，rows 的每个元素里所有成对数值列算环比
    # 实际调用方会传专门的对比查询结果，这里只做最简单的：逐行逐列对数字算 TopN 变动
    flat: list[dict[str, Any]] = []
    for row in rows[:50]:
        row_label = str(row[0]) if row else ""
        for i in range(1, len(row)):
            cur = _to_float(row[i])
            if cur is None:
                continue
            flat.append({"label": f"{row_label} {columns[i]}", "value": cur})
    # 跟全局平均值比异常
    if not flat:
        return []
    vals = [f["value"] for f in flat]
    avg = sum(vals) / len(vals)
    if avg == 0:
        return []
    for item in flat:
        item["deviation_pct"] = round((item["value"] - avg) / abs(avg) * 100, 2)
    flat.sort(key=lambda x: abs(x["deviation_pct"]), reverse=True)
    top = [f for f in flat if abs(f["deviation_pct"]) >= min_change_pct][:top_n]
    return top


def contribution_breakdown(
    columns: list[str],
    rows: list[list[Any]],
    metric_index: int = 1,
    top_n: int = 5,
) -> dict[str, Any]:
    """按分组拆解某指标的贡献：谁占总量比例最高。

    rows 期望形如 [分组, 指标值] 或 [分组, 指标1, 指标2, ...]。
    """
    if not rows or metric_index >= len(rows[0] or []):
        return {"available": False, "reason": "无可拆解数据"}
    parsed = []
    total = 0.0
    for row in rows:
        label = str(row[0]) if row else ""
        v = _to_float(row[metric_index])
        if v is None:
            continue
        parsed.append({"group": label, "value": v})
        total += v
    if total == 0:
        return {"available": False, "reason": "指标总量为 0"}
    parsed.sort(key=lambda x: x["value"], reverse=True)
    top = parsed[:top_n]
    for p in top:
        p["pct"] = round(p["value"] / total * 100, 2)
    others = {"group": "其它", "value": round(total - sum(p["value"] for p in top), 2),
              "pct": round((total - sum(p["value"] for p in top)) / total * 100, 2)}
    return {"available": True, "metric": columns[metric_index] if metric_index < len(columns) else "",
            "total": round(total, 2), "top": top, "others": others}


def generate_suggestions(
    question: str,
    comp: dict[str, Any],
    anomalies: list[dict[str, Any]],
    breakdowns: list[dict[str, Any]],
) -> list[str]:
    """基于真实数字生成可操作建议。纯规则，不编造。"""
    sugs: list[str] = []
    dod = comp.get("dod") or {}
    if dod.get("available"):
        deltas = dod.get("delta_pct") or []
        for i, d in enumerate(deltas):
            if d is None:
                continue
            if d < -10:
                sugs.append(f"· {question} 出现显著下滑（日环比 {d:.1f}%），建议立即拆解到门店/品类定位原因")
                break
    wow = comp.get("wow") or {}
    if wow.get("available"):
        deltas = wow.get("delta_pct") or []
        for i, d in enumerate(deltas):
            if d is None:
                continue
            if d > 15:
                sugs.append(f"· {question} 周环比提升 {d:.1f}%，可评估是否有可复制动作")
                break
    if anomalies:
        top = anomalies[0]
        sugs.append(f"· 波动最大项：{top['label']}（偏离均值 {top['deviation_pct']:.1f}%），建议单独复盘")
    for b in breakdowns:
        if b.get("available") and b.get("top"):
            lead = b["top"][0]
            sugs.append(f"· {b['metric']} 主要来自 {lead['group']}（占 {lead['pct']:.1f}%），聚焦头部贡献即可")
    if comp.get("yoy") and not comp["yoy"].get("available"):
        sugs.append("· 年同比不可用（历史数据缺失），建议 DBA 补入后再做年度口径对比")
    if not sugs:
        sugs.append("· 指标平稳，无需特别动作；持续观察即可")
    return sugs
