"""派生算子：在基础结果集上用确定性算法计算诊断/预测指标。

原则：不引入随机性、不做外部调用；所有结论文字都指回派生结果的行或计算元数据。
"""
from __future__ import annotations

import math
from typing import Any

COLUMNS: dict[str, list[str]] = {
    "period_compare": ["时间", "指标", "本期", "对比期", "变化量", "变化率%"],
    "contribution": ["维度", "指标值", "贡献占比%", "累计占比%", "排名"],
    "breakdown": ["父维度", "子维度", "指标值", "父内占比%", "累计占比%", "父总额"],
    "outlier": ["维度", "指标值", "Z值", "均值", "标准差", "判定"],
    "pareto": ["维度", "指标值", "占比%", "累计占比%", "分类"],
    "forecast": ["时间", "值", "类型", "下限", "上限"],
    "correlation": ["维度", "", ""],
    "cluster": ["维度", "cluster"],
    "cohort": ["同期群", "规模"],
    "funnel": ["阶段", "实体数", "转化率%", "环比转化%"],
    "whatif": ["维度", "基期销售额", "基期销量", "模拟销售额", "销售额变化%", "模拟毛利", "毛利变化%"],
}


class DerivedError(ValueError):
    """派生计算失败（样本不足 / 参数不合法）。"""

    def __init__(self, message: str, code: str = "derived_failed"):
        super().__init__(message)
        self.code = code


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    return num


def _fmt(value: Any, digits: int = 2) -> str:
    num = _num(value)
    if num is None:
        return "-"
    if num.is_integer():
        return f"{num:,.0f}"
    return f"{num:,.{digits}f}"


def _pct(value: Any, digits: int = 2) -> str:
    num = _num(value)
    return "-" if num is None else f"{num:.{digits}f}%"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def _next_period(label: str, granularity: str) -> str:
    """按粒度生成下一个周期标签（用于预测期）。"""
    text = str(label)
    try:
        if granularity == "day":
            import datetime
            d = datetime.date.fromisoformat(text[:10])
            return (d + datetime.timedelta(days=1)).isoformat()
        if granularity == "month" and len(text) >= 7:
            y, m = int(text[:4]), int(text[5:7])
            m += 1
            if m > 12:
                y, m = y + 1, 1
            return f"{y:04d}-{m:02d}"
        if granularity == "quarter" and "-Q" in text:
            y, q = text.split("-Q", 1)
            qn = int(q) + 1
            return f"{int(y) + 1}-Q1" if qn > 4 else f"{int(y)}-Q{qn}"
        if granularity == "year":
            return str(int(text[:4]) + 1)
        if granularity == "week":
            y, w = text.split("-", 1)
            n = int(w) + 1
            return f"{int(y) + 1}-01" if n > 53 else f"{int(y)}-{n:02d}"
    except (ValueError, TypeError):
        pass
    return text


def _prior_period(label: str, mode: str) -> str:
    text = str(label)
    if mode == "yoy":
        if len(text) >= 4 and text[:4].isdigit():
            return f"{int(text[:4]) - 1}{text[4:]}"
        return ""
    return ""


# ────────────────────────── P1：诊断算子 ──────────────────────────

def _period_compare(spec: dict, columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    metrics = spec["metrics"]
    mode = spec["options"].get("mode", "mom")
    # 远端引擎不保证 ORDER BY 语义，时间序列在本地按周期排序后再比较
    rows = sorted(rows, key=lambda r: str(r[0]))
    out: list[list[Any]] = []
    if mode == "yoy":
        index = {str(r[0]): i for i, r in enumerate(rows)}
        for i, r in enumerate(rows):
            prior = _prior_period(r[0], "yoy")
            j = index.get(prior)
            if j is None:
                continue
            for k, m in enumerate(metrics, start=1):
                cur, prev = r[k], rows[j][k]
                cn, pn = _num(cur), _num(prev)
                if cn is None or pn is None:
                    continue
                delta = cn - pn
                rate = (delta / pn * 100) if pn else None
                out.append([str(r[0]), m["name"], cn, pn, delta, rate])
    else:
        for i in range(1, len(rows)):
            for k, m in enumerate(metrics, start=1):
                cur, prev = rows[i][k], rows[i - 1][k]
                cn, pn = _num(cur), _num(prev)
                if cn is None or pn is None:
                    continue
                delta = cn - pn
                rate = (delta / pn * 100) if pn else None
                out.append([str(rows[i][0]), m["name"], cn, pn, delta, rate])

    if not out:
        raise DerivedError("对比期没有可匹配的数据，请扩大 time_range")

    facts: list[dict[str, str]] = []
    ranked = sorted(enumerate(out), key=lambda x: _num(x[1][5]) or 0)
    drop_i, drop = ranked[0]
    rise_i, rise = ranked[-1]
    word = "环比" if mode == "mom" else "同比"
    facts.append({
        "text": f"{drop[1]} {drop[0]} {word}下降 {_pct(abs(_num(drop[5]) or 0))}，本期 {_fmt(drop[2])}，对比期 {_fmt(drop[3])}",
        "from": f"rows[{drop_i}][4],rows[{drop_i}][3]",
    })
    if len(out) > 1:
        facts.append({
            "text": f"{rise[1]} {rise[0]} {word}上升 {_pct(abs(_num(rise[5]) or 0))}，本期 {_fmt(rise[2])}，对比期 {_fmt(rise[3])}",
            "from": f"rows[{rise_i}][4],rows[{rise_i}][3]",
        })
    last = out[-1]
    facts.append({
        "text": f"最近一期 {last[0]} 的{last[1]}为 {_fmt(last[2])}",
        "from": f"rows[{len(out) - 1}][2]",
    })
    return {
        "columns": list(COLUMNS["period_compare"]),
        "rows": out,
        "facts": facts,
        "chart": {"type": "bar", "x": "时间", "series": ["变化率%"], "group": "指标"},
    }


def _contribution(spec: dict, columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    name = spec["metrics"][0]["name"]
    pairs = [(str(r[0]), _num(r[1])) for r in rows if _num(r[1]) is not None]
    if not pairs:
        raise DerivedError("没有可用于贡献度计算的数值")
    pairs.sort(key=lambda x: float(x[1]), reverse=True)
    total = sum(float(v) for _, v in pairs)
    if abs(total) < 1e-12:
        raise DerivedError("指标合计为 0，无法计算贡献占比")
    out: list[list[Any]] = []
    cum = 0.0
    for i, (dim, value) in enumerate(pairs, start=1):
        share = float(value) / total * 100
        cum += share
        out.append([dim, float(value), share, cum, i])

    facts = [
        {"text": f"{out[0][0]} 的{name}最高，为 {_fmt(out[0][1])}，贡献 {_pct(out[0][2])}",
         "from": "rows[0][1],rows[0][2]"},
    ]
    for n in (3, 5, 10):
        if len(out) >= n:
            facts.append({
                "text": f"前 {n} 个维度合计贡献 {_pct(out[n - 1][3])}",
                "from": f"rows[{n - 1}][3]",
            })
            break
    facts.append({"text": f"共 {len(out)} 个维度参与，合计 {_fmt(total)}", "from": "derived.total"})
    return {
        "columns": list(COLUMNS["contribution"]),
        "rows": out,
        "facts": facts,
        "chart": {"type": "pareto_bar", "x": "维度", "series": ["指标值"], "cumulative": "累计占比%"},
    }


def _breakdown(spec: dict, columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    name = spec["metrics"][0]["name"]
    grouped: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        value = _num(r[2])
        if value is None:
            continue
        grouped.setdefault(str(r[0]), []).append((str(r[1]), value))
    if not grouped:
        raise DerivedError("没有可用于拆解的数据")
    out: list[list[Any]] = []
    for parent, items in grouped.items():
        parent_total = sum(v for _, v in items)
        items.sort(key=lambda x: x[1], reverse=True)
        cum = 0.0
        for child, value in items:
            share = (value / parent_total * 100) if parent_total else None
            cum += share or 0
            out.append([parent, child, value, share, cum, parent_total])
    out.sort(key=lambda x: (-(x[5] or 0), -(x[2] or 0)))
    top_parent = out[0][0]
    top_child = out[0][1]
    facts = [
        {"text": f"{top_parent} 的{name}最高子项为 {top_child}，{_fmt(out[0][2])}，占该类 {_pct(out[0][3])}",
         "from": "rows[0][2],rows[0][3]"},
        {"text": f"{top_parent} 的{name}合计 {_fmt(out[0][5])}", "from": "rows[0][5]"},
        {"text": f"共 {len(grouped)} 个父维度、{len(out)} 个组合", "from": "rows.length"},
    ]
    return {
        "columns": list(COLUMNS["breakdown"]),
        "rows": out,
        "facts": facts,
        "chart": {"type": "bar", "x": "父维度", "series": ["指标值"], "group": "子维度"},
    }


def _outlier(spec: dict, columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    name = spec["metrics"][0]["name"]
    threshold = float(spec["options"].get("threshold", 2.0))
    pairs = [(str(r[0]), _num(r[1])) for r in rows if _num(r[1]) is not None]
    if len(pairs) < 3:
        raise DerivedError("异常检测至少需要 3 个维度的数据")
    values = [float(v) for _, v in pairs]
    mean = _mean(values)
    std = _std(values)
    if std <= 0:
        raise DerivedError("指标标准差为 0，无法判定异常")
    scored = []
    for dim, value in pairs:
        z = (float(value) - mean) / std
        scored.append((dim, float(value), z))
    scored.sort(key=lambda x: abs(x[2]), reverse=True)
    out = []
    for dim, value, z in scored:
        if abs(z) < threshold:
            continue
        out.append([dim, value, z, mean, std, "高于均值" if z > 0 else "低于均值"])
    if not out:
        raise DerivedError(f"没有 |Z| ≥ {threshold} 的异常维度")
    facts = [
        {"text": f"{len(out)} 个维度触发异常（|Z| ≥ {threshold:g}），样本均值 {_fmt(mean)}、标准差 {_fmt(std)}",
         "from": "rows.length,derived.mean,derived.std"},
        {"text": f"{out[0][0]} 偏离最大，Z={out[0][2]:.2f}，值 {_fmt(out[0][1])}",
         "from": "rows[0][2],rows[0][1]"},
    ]
    return {
        "columns": list(COLUMNS["outlier"]),
        "rows": out,
        "facts": facts,
        "chart": {"type": "anomaly_scatter", "x": "维度", "y": "指标值", "z": "Z值",
                  "mean": mean, "std": std, "metric": name},
    }


def _pareto(spec: dict, columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    name = spec["metrics"][0]["name"]
    cutoff = float(spec["options"].get("cutoff", 80.0))
    pairs = [(str(r[0]), _num(r[1])) for r in rows if _num(r[1]) is not None]
    if not pairs:
        raise DerivedError("没有可用于帕累托分析的数据")
    pairs.sort(key=lambda x: float(x[1]), reverse=True)
    total = sum(float(v) for _, v in pairs)
    if total <= 0:
        raise DerivedError("指标合计不为正，无法计算累计占比")
    out: list[list[Any]] = []
    cum = 0.0
    a_count = 0
    for dim, value in pairs:
        share = float(value) / total * 100
        cum += share
        klass = "A" if cum <= cutoff + 1e-9 else ("B" if cum <= 95 else "C")
        if klass == "A":
            a_count += 1
        out.append([dim, float(value), share, cum, klass])
    facts = [
        {"text": f"A 类 {a_count} 个维度累计贡献 {_pct(out[max(a_count - 1, 0)][3])}（阈值 {cutoff:g}%）",
         "from": f"rows[{max(a_count - 1, 0)}][3]"},
        {"text": f"{out[0][0]} 排名第一，{_fmt(out[0][1])}，占 {_pct(out[0][2])}",
         "from": "rows[0][1],rows[0][2]"},
        {"text": f"共 {len(out)} 个维度，合计 {_fmt(total)}", "from": "derived.total"},
    ]
    return {
        "columns": list(COLUMNS["pareto"]),
        "rows": out,
        "facts": facts,
        "chart": {"type": "pareto_bar", "x": "维度", "series": ["指标值"], "cumulative": "累计占比%"},
    }


# ────────────────────────── P2：预测与统计 ──────────────────────────

def _forecast(spec: dict, columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    metrics = spec["metrics"]
    name = metrics[0]["name"]
    horizon = int(spec["options"].get("horizon", 3))
    gran = (spec.get("time_range") or {}).get("granularity", "month")
    rows = sorted(rows, key=lambda r: str(r[0]))
    points: list[tuple[int, float]] = []
    labels: list[str] = []
    for i, r in enumerate(rows):
        value = _num(r[1])
        labels.append(str(r[0]))
        if value is not None:
            points.append((i, value))
    if len(points) < 3:
        raise DerivedError("预测至少需要 3 个有效历史点")
    xs = [float(x) for x, _ in points]
    ys = [y for _, y in points]
    mx, my = _mean(xs), _mean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var <= 0:
        raise DerivedError("时间轴无变化，无法拟合趋势")
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
    intercept = my - slope * mx
    fitted = [slope * x + intercept for x in xs]
    ss_res = sum((y - f) ** 2 for y, f in zip(ys, fitted))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 1.0
    resid_std = math.sqrt(ss_res / (len(ys) - 2)) if len(ys) > 2 else 0.0

    out: list[list[Any]] = []
    value_by_row = {i: v for i, v in points}
    for i, label in enumerate(labels):
        value = value_by_row.get(i)
        if value is None:
            continue
        out.append([label, value, "实际", None, None])
    last_label = labels[-1]
    last_x = float(xs[-1])
    future: list[list[Any]] = []
    cursor = last_label
    for h in range(1, horizon + 1):
        cursor = _next_period(cursor, gran)
        pred = slope * (last_x + h) + intercept
        band = 1.96 * resid_std
        future.append([cursor, pred, "预测", pred - band, pred + band])
    out.extend(future)

    last_actual = ys[-1]
    final = future[-1][1]
    change = ((final - last_actual) / last_actual * 100) if last_actual else None
    facts = [
        {"text": f"基于 {len(ys)} 个历史点线性外推，斜率 {slope:,.4f}/期，R²={r2:.4f}",
         "from": "derived.fit.slope,derived.fit.r2"},
        {"text": f"最近实际 {labels[-1]} 的{name}为 {_fmt(last_actual)}", "from": f"rows[{len(ys) - 1}][1]"},
        {"text": f"预测 {future[-1][0]} 为 {_fmt(final)}，较最近实际 {_pct(change)}",
         "from": f"rows[{len(out) - 1}][1],derived.fit.change"},
    ]
    return {
        "columns": list(COLUMNS["forecast"]),
        "rows": out,
        "facts": facts,
        "chart": {"type": "forecast_line", "x": "时间", "series": ["值"], "type_col": "类型",
                  "lower": "下限", "upper": "上限", "fit": {"slope": slope, "r2": r2}},
    }


def _correlation(spec: dict, columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    m0, m1 = spec["metrics"][0], spec["metrics"][1]
    pairs = []
    for r in rows:
        a, b = _num(r[1]), _num(r[2])
        if a is None or b is None:
            continue
        pairs.append((str(r[0]), a, b))
    if len(pairs) < 3:
        raise DerivedError("相关系数至少需要 3 个有效样本")
    xs = [p[1] for p in pairs]
    ys = [p[2] for p in pairs]
    mx, my = _mean(xs), _mean(ys)
    sx, sy = _std(xs), _std(ys)
    if sx <= 0 or sy <= 0:
        raise DerivedError("指标无波动，无法计算相关系数")
    r = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) * sx * sy)
    r = max(-1.0, min(1.0, r))
    strength = "强" if abs(r) >= 0.7 else ("中等" if abs(r) >= 0.4 else "弱")
    direction = "正" if r >= 0 else "负"
    out = [[dim, a, b] for dim, a, b in pairs]
    out.sort(key=lambda x: -(x[1] or 0))
    facts = [
        {"text": f"{m0['name']} 与 {m1['name']} 的皮尔逊相关系数为 {r:.4f}，{strength}{direction}相关",
         "from": "derived.pearson"},
        {"text": f"样本 {len(out)} 个，{m0['name']} 均值 {_fmt(mx)}，{m1['name']} 均值 {_fmt(my)}",
         "from": "rows.length,derived.means"},
    ]
    return {
        "columns": [spec["dimensions"][0], m0["name"], m1["name"]],
        "rows": out,
        "facts": facts,
        "chart": {"type": "scatter", "x": m0["name"], "y": m1["name"], "correlation": round(r, 6)},
    }


def _cluster(spec: dict, columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    k = int(spec["options"].get("k", 3))
    metrics = spec["metrics"]
    points = []
    for r in rows:
        values = [_num(r[1 + i]) for i in range(len(metrics))]
        if any(v is None for v in values):
            continue
        points.append((str(r[0]), [float(v) for v in values]))
    if len(points) < k:
        raise DerivedError(f"聚类至少需要 {k} 个有效样本")
    dim = len(metrics)
    means = [_mean([p[1][j] for p in points]) for j in range(dim)]
    stds = [_std([p[1][j] for p in points]) for j in range(dim)]
    stds = [s if s > 0 else 1.0 for s in stds]
    z = [[(p[1][j] - means[j]) / stds[j] for j in range(dim)] for p in points]

    order = sorted(range(len(z)), key=lambda i: z[i][0])
    centroids = [list(z[order[min(len(z) - 1, int((c + 0.5) * len(z) / k))]]) for c in range(k)]
    labels = [0] * len(z)
    for _ in range(30):
        changed = False
        for i, vec in enumerate(z):
            best = min(range(k), key=lambda c: sum((vec[j] - centroids[c][j]) ** 2 for j in range(dim)))
            if labels[i] != best:
                labels[i] = best
                changed = True
        for c in range(k):
            members = [z[i] for i in range(len(z)) if labels[i] == c]
            if members:
                centroids[c] = [_mean([m[j] for m in members]) for j in range(dim)]
        if not changed:
            break

    out = []
    for i, (name, raw) in enumerate(points):
        out.append([name, *raw, labels[i]])
    out.sort(key=lambda x: (x[-1], -(x[1] or 0)))
    sizes = [sum(1 for i in range(len(z)) if labels[i] == c) for c in range(k)]
    facts = [{"text": f"按 {dim} 个指标分为 {k} 类，样本 {len(out)} 个", "from": "rows.length"}]
    for c in range(k):
        members = [p[1] for i, p in enumerate(points) if labels[i] == c]
        if not members:
            continue
        center = [_mean([m[j] for m in members]) for j in range(dim)]
        detail = "，".join(f"{metrics[j]['name']}均值 {_fmt(center[j])}" for j in range(dim))
        facts.append({"text": f"第 {c + 1} 类 {sizes[c]} 个：{detail}", "from": f"derived.centroids[{c}]"})
    return {
        "columns": [spec["dimensions"][0], *[m["name"] for m in metrics], "cluster"],
        "rows": out,
        "facts": facts,
        "chart": {"type": "scatter", "x": metrics[0]["name"], "y": metrics[1]["name"], "color": "cluster"},
    }


def _cohort(spec: dict, columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    entity_periods: dict[str, set[str]] = {}
    for r in rows:
        entity_periods.setdefault(str(r[0]), set()).add(str(r[1]))
    if not entity_periods:
        raise DerivedError("没有可用于同期群分析的数据")
    all_periods = sorted({p for periods in entity_periods.values() for p in periods})
    period_index = {p: i for i, p in enumerate(all_periods)}
    cohorts: dict[str, list[str]] = {}
    for entity, periods in entity_periods.items():
        first = min(periods)
        cohorts.setdefault(first, []).append(entity)
    width = len(all_periods)
    header = ["同期群", "规模"] + [f"第{i}期" for i in range(width)]
    out: list[list[Any]] = []
    for cohort in sorted(cohorts):
        entities = cohorts[cohort]
        start = period_index[cohort]
        row: list[Any] = [cohort, len(entities)]
        for offset in range(width):
            if offset >= width - start:
                row.append(None)
                continue
            period = all_periods[start + offset]
            active = sum(1 for e in entities if period in entity_periods[e])
            row.append(round(active / len(entities) * 100, 2))
        out.append(row)
    facts = [
        {"text": f"共 {len(all_periods)} 个周期、{len(out)} 个同期群、{len(entity_periods)} 个实体",
         "from": "rows.length,derived.periods"},
        {"text": f"{out[0][0]} 同期群规模 {out[0][1]}，第 1 期留存 {_pct(out[0][2] if len(out[0]) > 2 else None)}",
         "from": "rows[0][1],rows[0][2]"},
    ]
    if len(out) > 1:
        facts.append({"text": f"最新同期群 {out[-1][0]} 规模 {out[-1][1]}", "from": f"rows[{len(out) - 1}][1]"})
    return {
        "columns": header,
        "rows": out,
        "facts": facts,
        "chart": {"type": "heatmap", "x": "期数", "y": "同期群", "header": header},
    }


def _funnel(spec: dict, columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    stages = spec["options"]["stages"]
    pairs = [(str(r[0]), _num(r[1])) for r in rows if _num(r[1]) is not None]
    if not pairs:
        raise DerivedError("没有可用于漏斗计算的数据")
    out: list[list[Any]] = []
    first = None
    prev = None
    for stage in stages:
        count = sum(1 for _, value in pairs if float(value) >= stage["min"])
        if first is None:
            first = count
        rate = (count / first * 100) if first else None
        step = (count / prev * 100) if prev else None
        out.append([stage["name"], count, rate, step])
        prev = count
    if not first:
        raise DerivedError("首阶段实体数为 0，无法计算转化")
    facts = [
        {"text": f"{out[0][0]} 实体数 {out[0][1]}，{out[-1][0]} 实体数 {out[-1][1]}，整体转化 {_pct(out[-1][2])}",
         "from": f"rows[0][1],rows[{len(out) - 1}][1],rows[{len(out) - 1}][2]"},
    ]
    for i in range(1, len(out)):
        facts.append({"text": f"{out[i][0]} 环比转化 {_pct(out[i][3])}", "from": f"rows[{i}][3]"})
    return {
        "columns": list(COLUMNS["funnel"]),
        "rows": out,
        "facts": facts,
        "chart": {"type": "funnel", "x": "阶段", "series": ["实体数"]},
    }


def _whatif(spec: dict[str, Any], columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    """A4 What-if 策略模拟（确定性模型，无 LLM）：

    单价 = 销售额 / 销量；单位成本 = (销售额 - 毛利) / 销量（基期不变假设）。
    给定价格变动 dp 与弹性 e，销量变动 dq = e·dp（或直接给定 volume_change_pct），
    模拟销售额 = 单价×(1+dp)×销量×(1+dq)，模拟毛利 = (单价×(1+dp) − 单位成本)×新销量。
    """
    opts = spec.get("options") or {}
    dp = float(opts.get("price_change_pct", 5.0)) / 100.0
    if opts.get("volume_change_pct") is not None:
        dq = float(opts["volume_change_pct"]) / 100.0
        e_used: float | None = None
    else:
        e_used = float(opts.get("elasticity", -1.5))
        dq = e_used * dp

    mi = len(spec["dimensions"])  # 指标起始列：m0 销售额, m1 销量, m2 毛利
    if mi + 2 >= len(columns):
        raise DerivedError("基础结果集缺少销售额/销量/毛利指标列")

    def _num(v: Any) -> float | None:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if math.isfinite(f) else None

    out: list[list[Any]] = []
    total = [0.0, 0.0, 0.0, 0.0]  # 基期销售额, 基期销量, 模拟销售额, 模拟毛利
    skipped = 0
    for r in rows:
        rev, qty, profit = _num(r[mi]), _num(r[mi + 1]), _num(r[mi + 2])
        if rev is None or qty is None or profit is None or qty <= 0:
            skipped += 1
            continue
        price = rev / qty
        cost_unit = (rev - profit) / qty
        new_qty = qty * (1.0 + dq)
        new_rev = price * (1.0 + dp) * new_qty
        new_profit = (price * (1.0 + dp) - cost_unit) * new_qty
        rev_chg = (new_rev / rev - 1.0) * 100.0 if rev != 0 else 0.0
        profit_chg = (new_profit / profit - 1.0) * 100.0 if profit != 0 else None
        key = "整体" if not spec["dimensions"] else " / ".join(str(r[i]) for i in range(mi))
        out.append([
            key, round(rev, 2), round(qty, 2), round(new_rev, 2), round(rev_chg, 2),
            round(new_profit, 2), round(profit_chg, 2) if profit_chg is not None else "—",
        ])
        total[0] += rev
        total[1] += qty
        total[2] += new_rev
        total[3] += new_profit

    if not out:
        raise DerivedError("没有可模拟的数据行（销量必须为正）")

    total_rev_chg = (total[2] / total[0] - 1.0) * 100.0 if total[0] else 0.0
    # 合计毛利变化率按基期毛利合计计算
    base_profit_total = 0.0
    for r in rows:
        rev, qty, profit = _num(r[mi]), _num(r[mi + 1]), _num(r[mi + 2])
        if rev is None or qty is None or profit is None or qty <= 0:
            continue
        base_profit_total += profit
    total_profit_chg = (total[3] / base_profit_total - 1.0) * 100.0 if base_profit_total else 0.0

    if spec["dimensions"]:
        out.append(["合计", round(total[0], 2), round(total[1], 2), round(total[2], 2),
                    round(total_rev_chg, 2), round(total[3], 2), round(total_profit_chg, 2)])
    out.sort(key=lambda r: -(r[3] if isinstance(r[3], (int, float)) else 0.0))
    # 合计固定沉底
    out.sort(key=lambda r: r[0] == "合计")

    facts: list[dict[str, Any]] = [
        {"text": f"模拟参数：价格 {dp * 100:+.1f}%，"
                 + (f"销量 {dq * 100:+.1f}%（直接给定）" if e_used is None else f"弹性 {e_used}（销量 {dq * 100:+.1f}%）"),
         "from": "spec.options"},
    ]
    for i, r in enumerate(out[:5]):
        if r[0] != "合计":
            facts.append({"text": f"{r[0]} 模拟销售额 {r[3]:,.2f}（{r[4]:+.1f}%）", "from": f"rows[{i}]"})
    if skipped:
        facts.append({"text": f"{skipped} 行因销量为 0 或数据缺失被跳过", "from": "rows"})

    return {
        "columns": list(COLUMNS["whatif"]),
        "rows": out,
        "facts": facts,
        "chart": {"type": "whatif_table", "x": spec["dimensions"][0] if spec["dimensions"] else ""},
    }


def impact_result(spec: dict[str, Any], treat_rows: list[list[Any]], ctrl_rows: list[list[Any]]) -> dict[str, Any]:
    """A4 因果推断：事件影响 · 双重差分（DID），确定性计算。

    净效应 = (处理组后均值 − 处理组前均值) − (对照组后均值 − 对照组前均值)。
    输入为两条按日 timeseries（处理组 / 对照组），列 [期间, 指标]。
    """
    def _f(v: Any) -> float | None:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if math.isfinite(f) else None

    opts = spec.get("options") or {}
    ev = str(opts.get("event_date"))
    treat = opts.get("treatment") or {}
    tlabel = str(treat.get("label") or treat.get("value"))

    def split(rows: list[list[Any]]) -> tuple[list[float], list[float]]:
        pre = [f for r in rows if str(r[0]) < ev for f in [_f(r[1])] if f is not None]
        post = [f for r in rows if str(r[0]) >= ev for f in [_f(r[1])] if f is not None]
        if not pre or not post:
            raise DerivedError(f"事件日 {ev} 前后缺少数据（前 {len(pre)} 天 / 后 {len(post)} 天）")
        return pre, post

    pre_t, post_t = split(treat_rows)
    pre_c, post_c = split(ctrl_rows)
    mt_pre, mt_post = sum(pre_t) / len(pre_t), sum(post_t) / len(post_t)
    mc_pre, mc_post = sum(pre_c) / len(pre_c), sum(post_c) / len(post_c)
    dt, dc = mt_post - mt_pre, mc_post - mc_pre
    did = dt - dc
    did_pct = did / mt_pre * 100.0 if mt_pre != 0 else None

    def pct(v: float | None) -> Any:
        return round(v, 2) if v is not None else "—"

    rows = [
        [tlabel, round(mt_pre, 2), round(mt_post, 2), round(dt, 2), pct(dt / mt_pre * 100.0 if mt_pre else None)],
        ["对照组", round(mc_pre, 2), round(mc_post, 2), round(dc, 2), pct(dc / mc_pre * 100.0 if mc_pre else None)],
        ["净效应（双重差分）", "—", "—", round(did, 2), pct(did_pct)],
    ]
    facts: list[dict[str, Any]] = [
        {"text": f"事件日 {ev}；处理组 {tlabel}（{treat.get('field')}={treat.get('value')}），"
                 f"前期 {len(pre_t)} 天 / 后期 {len(post_t)} 天按日均值", "from": "spec.options"},
        {"text": f"对照组口径 {treat.get('field')} ≠ {treat.get('value')}（空值不计入），"
                 f"前期 {len(pre_c)} 天 / 后期 {len(post_c)} 天", "from": "spec.options"},
        {"text": f"处理组变化 {dt:+,.2f}，对照组 {dc:+,.2f}，净效应 {did:+,.2f}", "from": "rows"},
    ]
    return {
        "columns": ["组别", "前期均值", "后期均值", "变化", "变化%"],
        "rows": rows,
        "facts": facts,
        "chart": {"type": "impact_table"},
    }


_HANDLERS = {
    "period_compare": _period_compare,
    "contribution": _contribution,
    "breakdown": _breakdown,
    "outlier": _outlier,
    "pareto": _pareto,
    "forecast": _forecast,
    "correlation": _correlation,
    "cluster": _cluster,
    "cohort": _cohort,
    "funnel": _funnel,
    "whatif": _whatif,
}


def derive(spec: dict[str, Any], columns: list[str], rows: list[list[Any]]) -> dict[str, Any] | None:
    """派生算子入口；非派生类型返回 None。"""
    handler = _HANDLERS.get(spec["type"])
    if handler is None:
        return None
    if not rows:
        raise DerivedError("基础结果集为空，无法计算", "no_data")
    return handler(spec, columns, rows)
