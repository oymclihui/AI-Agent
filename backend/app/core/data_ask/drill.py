"""图表点击下钻 + 交互式归因（蓝图二期 L3 · p2-1/p2-2）。

数据通路：前端图表 onClick(label) → POST /api/v1/data-ask/drill → 本模块确定性拼 SQL。
- 点日期轴上某天 → 该天按门店拆解（TopN + 占比贡献度排名）
- 点门店（分类轴）→ 该门店的时间趋势
- action="why" → 双窗口对比归因：本期 vs 上期，按门店 Δ 贡献排名（拉动/拖累）

设计约束：
- SQL 全部由模板拼装，clicked_label 只接受日期或 ^[A-Za-z0-9_-]{1,32}$ 维度成员，
  无用户 SQL 输入面，不经过 LLM；
- 指标识别用 metric_layer 同义词表（「总销售额」也能匹配到 sales_amount），
  匹配不到默认销售额；
- 图表复用 suggest_chart（门店轴 label 长 → 自动横向柱状图）；
- 占比贡献复用 depth_analysis.contribution_breakdown。
"""
from __future__ import annotations

import datetime
import re
from typing import Any

from app.core.data_ask.metric_layer import METRICS, MetricDef, detect_retail_tables

_RE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_RE_SLASH = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")
_RE_CN = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日?$")
_RE_MEMBER = re.compile(r"^[A-Za-z0-9_\-]{1,32}$")

# 可加指标 → (来源表, 值列)：对比归因用 CASE WHEN 直接聚合原值列
_ADDITIVE = {
    "sales_amount": ("a", "XSJE"),
    "gross_profit": ("a", "ML"),
    "sales_cost": ("a", "XSCB"),
    "txn_count": ("b", "JYBS"),
    "kl_revenue": ("b", "YYE"),
}

_SYN_SORTED: list[tuple[str, MetricDef]] = sorted(
    ((syn, met) for met in METRICS.values() for syn in met.synonyms),
    key=lambda x: len(x[0]), reverse=True,
)


class DrillError(ValueError):
    """入参不合法（前端可安全展示消息）。"""


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _norm_date(label: Any) -> str | None:
    text = str(label or "").strip()
    for pat in (_RE_ISO, _RE_SLASH, _RE_CN):
        m = pat.match(text)
        if m:
            try:
                return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
            except ValueError:
                return None
    return None


def _match_metric(series_label: Any) -> MetricDef:
    text = str(series_label or "").strip()
    for syn, met in _SYN_SORTED:
        if syn and syn in text:
            return met
    return METRICS["sales_amount"]


def _window_from_labels(labels: list[Any]) -> tuple[str, str] | None:
    dates = sorted(d for d in (_norm_date(l) for l in labels or []) if d)
    if dates:
        return dates[0], dates[-1]
    return None


async def _fetch(source: Any, sql: str, limit: int = 200) -> tuple[list[str], list[list[Any]]]:
    from app.core.data_ask.connectors.factory import build_connector_from_source

    conn = build_connector_from_source(source)
    try:
        qr = await conn.execute_select(sql, limit=limit)
        return list(qr.columns or []), [list(r) for r in (qr.rows or [])]
    finally:
        await conn.close()


async def _latest_rq(source: Any, table: str, rq_col: str) -> str | None:
    try:
        cols, rows = await _fetch(source, f"SELECT MAX({rq_col}) FROM {table}", limit=1)
        if rows and rows[0] and rows[0][0] is not None:
            return str(rows[0][0])[:10]
    except Exception:
        return None
    return None


def _where_for(cols: dict[str, str], day: str | None, store: str | None,
               win: tuple[str, str] | None) -> str:
    """按单表实际列名拼 WHERE：day 单日 / win 区间 / store 维度成员过滤。"""
    conds: list[str] = []
    if day:
        conds.append(f"{cols['RQ']} = '{day}'")
    elif win:
        conds.append(f"{cols['RQ']} BETWEEN '{win[0]}' AND '{win[1]}'")
    if store:
        conds.append(f"{cols['FDBH']} = '{store}'")
    return " AND ".join(conds)


def _drill_sql(
    metric: MetricDef,
    dim: str,
    day: str | None,
    store: str | None,
    win: tuple[str, str] | None,
    cols_a: dict[str, str] | None,
    cols_b: dict[str, str] | None,
    names: dict[str, str],
) -> str:
    """按下钻维度拼 SQL；WHERE 按各表实际列名构造。"""
    name = metric.name
    if metric.src == "x" and cols_a and cols_b:
        where_a = _where_for(cols_a, day, store, win)
        where_b = _where_for(cols_b, day, store, win)
        sub_a = (f"(SELECT {cols_a['RQ']}, {cols_a['FDBH']}, SUM({cols_a['XSJE']}) AS XSJE"
                 + (f", SUM({cols_a['ML']}) AS ML" if "ML" in cols_a else "")
                 + (f", SUM({cols_a['XSCB']}) AS XSCB" if "XSCB" in cols_a else "")
                 + f"\n  FROM {names['a']}\n WHERE {where_a}\n GROUP BY {cols_a['RQ']}, {cols_a['FDBH']}) t0")
        sub_b = (f"(SELECT {cols_b['RQ']}, {cols_b['FDBH']}, SUM({cols_b['JYBS']}) AS JYBS"
                 + (f", SUM({cols_b['YYE']}) AS YYE" if "YYE" in cols_b else "")
                 + f"\n  FROM {names['b']}\n WHERE {where_b}\n GROUP BY {cols_b['RQ']}, {cols_b['FDBH']}) t1")
        join = (f"{sub_a}\nJOIN {sub_b}\n  ON t0.{cols_a['RQ']} = t1.{cols_b['RQ']}"
                f" AND t0.{cols_a['FDBH']} = t1.{cols_b['FDBH']}")
        expr = metric.expr.format(T0="t0", T1="t1")
        if dim == "store":
            return (f"SELECT t0.{cols_a['FDBH']} AS 门店, {expr} AS {name}\nFROM {join}\n"
                    f"GROUP BY t0.{cols_a['FDBH']}\nORDER BY 2 DESC\nLIMIT 15")
        return (f"SELECT t0.{cols_a['RQ']} AS 日期, {expr} AS {name}\nFROM {join}\n"
                f"GROUP BY t0.{cols_a['RQ']}\nORDER BY 1")

    cols = cols_b if metric.src == "b" else cols_a
    table = names["b"] if metric.src == "b" else names["a"]
    where = _where_for(cols, day, store, win)
    expr = metric.expr.replace("{T0}.", "").replace("{T1}.", "")
    if dim == "store":
        return (f"SELECT {cols['FDBH']} AS 门店, {expr} AS {name}\nFROM {table}\n"
                f"WHERE {where}\nGROUP BY {cols['FDBH']}\nORDER BY 2 DESC\nLIMIT 15")
    return (f"SELECT {cols['RQ']} AS 日期, {expr} AS {name}\nFROM {table}\n"
            f"WHERE {where}\nGROUP BY {cols['RQ']}\nORDER BY 1")


async def run_drill(source: Any, payload: dict[str, Any], all_tables: list[dict[str, Any]] | None) -> dict[str, Any]:
    """点击下钻：payload = {clicked_label, labels, series_label}。"""
    cols_a, cols_b, names = detect_retail_tables(all_tables)
    if not cols_a and not cols_b:
        raise DrillError("该数据源不支持下钻（未识别到零售表结构）")

    clicked = str(payload.get("clicked_label") or "").strip()
    if not clicked:
        raise DrillError("缺少点击的图形标签")
    metric = _match_metric(payload.get("series_label"))
    labels = list(payload.get("labels") or [])

    day = _norm_date(clicked)
    store: str | None = None
    win: tuple[str, str] | None = None
    if day:
        dim, time_desc = "store", day
    elif _RE_MEMBER.match(clicked):
        win = _window_from_labels(labels)
        if not win:
            latest = None
            if cols_a:
                latest = await _latest_rq(source, names["a"], cols_a["RQ"])
            if not latest and cols_b:
                latest = await _latest_rq(source, names["b"], cols_b["RQ"])
            if not latest:
                raise DrillError("无法确定时间范围（数据源无营业日期）")
            win = (latest, latest)
        dim, store, time_desc = "day", clicked, f"{win[0]} ~ {win[1]}"
    else:
        raise DrillError(f"不支持下钻的图形标签：{clicked[:30]}")

    sql = _drill_sql(metric, dim, day, store, win, cols_a, cols_b, names)
    columns, rows = await _fetch(source, sql)

    from app.core.data_ask.depth_analysis import contribution_breakdown

    contrib = contribution_breakdown(columns, rows, metric_index=1) if rows else {"available": False}

    # chart 自建：门店轴横向柱 / 日轴折线；单门店数据源自动附带近 7 天趋势
    chart: dict[str, Any] | None = None
    note = ""
    if dim == "day" and rows:
        chart = {
            "type": "line",
            "title": f"{metric.name} · {store} · {time_desc}",
            "labels": [str(r[0])[:10] for r in rows],
            "datasets": [{"label": metric.name, "data": [_f(r[1]) for r in rows]}],
        }
    elif dim == "store" and rows:
        chart = {
            "type": "bar",
            "title": f"{metric.name} · {time_desc} · 按门店",
            "labels": [str(r[0]) for r in rows],
            "datasets": [{"label": metric.name, "data": [_f(r[1]) for r in rows]}],
            "horizontal": len(rows) > 6,
        }
        if len(rows) <= 1 and day:
            # 单门店：门店拆解无信息量 → 附近 7 天趋势作主图
            try:
                s7 = datetime.date.fromisoformat(day) - datetime.timedelta(days=6)
                tsql = _drill_sql(metric, "day", None, None, (s7.isoformat(), day), cols_a, cols_b, names)
                _, trows = await _fetch(source, tsql)
                if len(trows) > 1:
                    chart = {
                        "type": "line",
                        "title": f"{metric.name} · 近 7 天（{s7} ~ {day}）",
                        "labels": [str(r[0])[:10] for r in trows],
                        "datasets": [{"label": metric.name, "data": [_f(r[1]) for r in trows]}],
                    }
                    note = "（当前数据源仅 1 家门店，已附近 7 天趋势）"
            except Exception:
                pass

    top_desc = ""
    if contrib.get("available") and contrib.get("top"):
        lead = contrib["top"][0]
        top_desc = f"，最高：{lead['group']}（{lead['value']:,.2f}，占 {lead['pct']:.1f}%）"
    answer = (f"{metric.name} · {time_desc} · 按{'门店' if dim == 'store' else '日'}拆解："
              f"共 {contrib.get('total', 0):,.2f} {metric.unit}{top_desc}{note}")

    return {
        "ok": True,
        "action": "drill",
        "answer": answer,
        "metric": metric.name,
        "dimension": "门店" if dim == "store" else "日期",
        "time_desc": time_desc,
        "time": {"start": day or (win[0] if win else None), "end": day or (win[1] if win else None)},
        "columns": columns,
        "rows": rows,
        "chart": chart,
        "contribution": contrib,
        "sql": sql,
    }


async def run_attribution(source: Any, payload: dict[str, Any], all_tables: list[dict[str, Any]] | None) -> dict[str, Any]:
    """对比归因：payload = {labels, series_label, time?{start,end}}。本期 vs 等长上期，按门店 Δ 贡献。"""
    cols_a, cols_b, names = detect_retail_tables(all_tables)
    if not cols_a and not cols_b:
        raise DrillError("该数据源不支持归因（未识别到零售表结构）")

    metric = _match_metric(payload.get("series_label"))
    if metric.key not in _ADDITIVE:
        raise DrillError(f"{metric.name} 是比率型指标，对比归因请换成销售额 / 毛利 / 交易笔数等可加指标")
    src, val_col = _ADDITIVE[metric.key]
    cols = cols_b if src == "b" else cols_a
    table = names["b"] if src == "b" else names["a"]
    if val_col not in cols:
        raise DrillError(f"数据表缺少归因所需列 {val_col}")

    t = payload.get("time") or {}
    win = (str(t.get("start") or ""), str(t.get("end") or ""))
    if not win[0] or not win[1]:
        win = _window_from_labels(list(payload.get("labels") or [])) or ("", "")
    if not win[0]:
        latest = await _latest_rq(source, table, cols["RQ"])
        if not latest:
            raise DrillError("无法确定时间范围（数据源无营业日期）")
        win = (latest, latest)
    start_s, end_s = win

    s = datetime.date.fromisoformat(start_s)
    e = datetime.date.fromisoformat(end_s)
    length = (e - s).days + 1
    prv_e = s - datetime.timedelta(days=1)
    prv_s = prv_e - datetime.timedelta(days=length - 1)
    rq, fd = cols["RQ"], cols["FDBH"]
    prv_s_s, prv_e_s = prv_s.isoformat(), prv_e.isoformat()
    sql = (
        f"SELECT {fd} AS 门店,\n"
        f"  SUM(CASE WHEN {rq} BETWEEN '{start_s}' AND '{end_s}' THEN {val_col} ELSE 0 END) AS 本期,\n"
        f"  SUM(CASE WHEN {rq} BETWEEN '{prv_s_s}' AND '{prv_e_s}' THEN {val_col} ELSE 0 END) AS 上期\n"
        f"FROM {table}\nWHERE {rq} BETWEEN '{prv_s_s}' AND '{end_s}'\n"
        f"GROUP BY {fd}"
    )
    columns, rows = await _fetch(source, sql, limit=200)

    items: list[dict[str, Any]] = []
    total_cur = total_prv = 0.0
    for row in rows:
        try:
            cur, prev = float(row[1] or 0), float(row[2] or 0)
        except (TypeError, ValueError):
            continue
        delta = cur - prev
        items.append({
            "group": str(row[0]), "cur": round(cur, 2), "prev": round(prev, 2),
            "delta": round(delta, 2),
            "delta_pct": round(delta / prev * 100, 2) if prev else None,
        })
        total_cur += cur
        total_prv += prev
    delta_total = total_cur - total_prv
    for it in items:
        it["contrib_pct"] = round(it["delta"] / delta_total * 100, 2) if delta_total else None
    items.sort(key=lambda x: abs(x["delta"]), reverse=True)
    top = items[:10]

    def _fmt(v: float) -> str:
        return f"{v:,.2f}"

    pct = round(delta_total / total_prv * 100, 2) if total_prv else None
    up = [i for i in top if i["delta"] > 0]
    down = [i for i in top if i["delta"] < 0]
    parts = [
        f"{metric.name}：本期 {_fmt(total_cur)} vs 上期（{prv_s_s} ~ {prv_e_s}）{_fmt(total_prv)}，"
        f"变化 {('+' if delta_total >= 0 else '')}{_fmt(delta_total)}"
        + (f"（{pct:+.2f}%）" if pct is not None else "") + "。"
    ]
    if up:
        parts.append(f"主要拉动：{up[0]['group']}（+{_fmt(up[0]['delta'])}"
                     + (f"，贡献 {up[0]['contrib_pct']:.1f}%" if up[0]["contrib_pct"] is not None else "") + "）。")
    if down:
        parts.append(f"主要拖累：{down[0]['group']}（{_fmt(down[0]['delta'])}"
                     + (f"，贡献 {down[0]['contrib_pct']:.1f}%" if down[0]["contrib_pct"] is not None else "") + "）。")
    if not up and not down:
        parts.append("各门店无明显变化。")

    return {
        "ok": True,
        "action": "why",
        "answer": "".join(parts),
        "metric": metric.name,
        "time": {"start": start_s, "end": end_s, "prev_start": prv_s_s, "prev_end": prv_e_s},
        "columns": ["门店", "本期", "上期", "变化", "变化%", "贡献%"],
        "rows": [
            [i["group"], i["cur"], i["prev"], i["delta"],
             f"{i['delta_pct']:+.2f}" if i["delta_pct"] is not None else "-",
             f"{i['contrib_pct']:+.2f}" if i["contrib_pct"] is not None else "-"]
            for i in top
        ],
        "attribution": top,
        "sql": sql,
    }
