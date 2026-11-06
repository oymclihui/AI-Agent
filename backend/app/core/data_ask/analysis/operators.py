"""分析算子层（蓝图《分析能力前台化》P1-①）。

8 个内置分析算子：metric_query / yoy_compare / mom_compare / topn_rank /
share_of_total / trend_detect / forecast_simple / anomaly_detect。

设计约束（蓝图红线）：
- 算子只产出 facts（{name, value, compare, unit, window}），不写自然语言——措辞交给技能结论规范；
- 所有 SQL 复用 metric_layer.build_metric_sql 确定性拼装（预聚合范式，无 LLM 参与）；
- 执行前一律过治理链：sql_guard + 列策略 + 行级权限注入（与问数主链路同一条链，fail-closed）；
- 本模块不得 import service.py（P1-② 编排器在 service 层调用本模块，避免循环导入）。

入口：run_operator(db, operator=..., data_source_id=..., params=..., user=...)。
时间窗参数支持相对词（$最新日/$昨天/$近N天/$本周/$上周/$本月/$上月/$今年/$去年）
与显式（YYYY-MM-DD / YYYY-MM-DD~YYYY-MM-DD / YYYY-MM）。
"""
from __future__ import annotations

import decimal
import re
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean, pstdev
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.connectors.factory import build_connector_from_source
from app.core.data_ask.govern.access import bypass_row_permission
from app.core.data_ask.govern.calendar import business_today
from app.core.data_ask.govern.audit import log_query
from app.core.data_ask.govern.column_policy import validate_sql_columns
from app.core.data_ask.govern.fanout import detect_fanout
from app.core.data_ask.govern.permission import (
    build_permission_scope_sql,
    inject_permission_filter,
    permission_config_from_rules,
    resolve_permission_columns,
)
from app.core.data_ask.govern.sql_guard import disambiguate_subquery_columns, validate_select_sql
from app.core.data_ask.intelligence.value_link import enrich_tables
from app.core.data_ask.metric_layer import (
    METRICS,
    MetricDef,
    MetricIntent,
    TimeRange,
    build_metric_sql,
    detect_retail_tables,
)
from app.core.data_ask.schema.introspect import introspect_tables
from app.db.models import DataSource, DataSourceTable, DataSourceTableRole, User

# 行数上限：算子单步取数兜底（防大结果集拖垮编排）
_MAX_ROWS_IN_RESULT = 50
_MAX_FACTS = 20


# ───────────────────────────── 上下文 ─────────────────────────────


@dataclass
class OperatorContext:
    """一次算子执行的完整环境：数据源 + 表元数据 + 治理链上下文。"""

    db: AsyncSession
    source: DataSource
    table_meta: list[dict[str, Any]]
    semantic: dict[str, Any] | None
    user: User | None
    scope: Any = None
    allowed: set[str] = field(default_factory=set)
    apply_perm: bool = False
    perm_table: str | None = None
    perm_rules: dict[str, str] = field(default_factory=dict)
    # 执行缓存
    _latest: str | None = None
    _retail: tuple | None = None


def _business_columns(all_tables: list[dict[str, Any]] | None) -> set[str]:
    """业务列大写集合（对齐 service.load_source_context 同名逻辑）。"""
    cols: set[str] = set()
    for t in all_tables or []:
        for c in t.get("columns") or []:
            name = str((c.get("name") if isinstance(c, dict) else c) or "").strip()
            if name:
                cols.add(name.upper())
    return cols


def _user_key(user: User | None) -> str:
    if not user:
        return "anonymous"
    key = str(user.employee_no or user.id)
    if not re.match(r"^[\w\-.@]+$", key):
        raise ValueError("Invalid user identity for permission filter")
    return key


async def build_operator_context(
    db: AsyncSession,
    data_source_id: str,
    user: User | None = None,
) -> OperatorContext:
    """加载算子执行环境（表元数据 + 权限链，对齐问数主链路 load_source_context 口径）。"""
    source = await db.get(DataSource, data_source_id)
    if not source:
        raise ValueError("Data source not found")

    result = await db.execute(
        select(DataSourceTable).where(DataSourceTable.data_source_id == data_source_id)
    )
    reg_tables = list(result.scalars().all())
    data_tables = [t for t in reg_tables if t.role == DataSourceTableRole.data]
    perm_row = next((t for t in reg_tables if t.role == DataSourceTableRole.permission), None)

    table_meta: list[dict[str, Any]] = []
    for t in data_tables:
        cols = (t.column_meta or {}).get("columns") or []
        if isinstance(t.column_meta, list):
            cols = t.column_meta
        table_meta.append(
            {
                "table_name": t.table_name,
                "columns": cols,
                "partition_columns": (t.column_meta or {}).get("partition_columns") or [],
                "sample_rows": t.sample_rows or [],
                "join_keys": t.join_keys or {},
            }
        )
    if not table_meta and data_tables:
        table_meta = await introspect_tables(source, [t.table_name for t in data_tables])
    table_meta = enrich_tables(table_meta)

    perm_table = perm_row.table_name if perm_row else None
    allowed = {t["table_name"] for t in table_meta}
    if perm_table:
        allowed.add(perm_table)

    scope = None
    if user is not None:
        from app.core.auth.permissions import resolve_data_scope

        scope = await resolve_data_scope(db, user)

    perm_rules = permission_config_from_rules(source.permission_rules)
    apply_perm = bool(perm_table) and not bypass_row_permission(user, scope)
    if apply_perm and user is None:
        # fail-closed：数据源启用了行级权限但缺少用户上下文，宁可拒绝也不放全量
        raise ValueError("该数据源启用了行级权限，分析算子需要登录用户上下文")
    if apply_perm and perm_table:
        effective, perm_error = await resolve_permission_columns(
            source, perm_table, perm_rules, _business_columns(table_meta)
        )
        if perm_error:
            raise ValueError(f"行级权限配置与数据源不一致：{perm_error}")
        perm_rules = effective

    return OperatorContext(
        db=db,
        source=source,
        table_meta=table_meta,
        semantic=source.semantic_model if isinstance(source.semantic_model, dict) else None,
        user=user,
        scope=scope,
        allowed=allowed,
        apply_perm=apply_perm,
        perm_table=perm_table,
        perm_rules=perm_rules if apply_perm else {},
    )


# ───────────────────────────── 治理链执行 ─────────────────────────────


async def _governed_execute(
    ctx: OperatorContext,
    sql: str,
    *,
    question: str = "",
) -> dict[str, Any]:
    """算子统一执行入口：sql_guard → 列策略 → 扇出保护 → 行级权限 → 执行 → 审计。"""
    dialect = str(ctx.source.driver)
    sql = disambiguate_subquery_columns(sql, dialect=dialect)

    ok, msg = validate_select_sql(sql, allowed_tables=ctx.allowed, dialect=dialect)
    if not ok:
        raise ValueError(f"算子 SQL 未过安全校验：{msg}")
    col_ok, col_msg = validate_sql_columns(
        sql,
        semantic_model=ctx.semantic,
        user_is_admin=bool(ctx.user and ctx.user.is_admin),
        scope=ctx.scope,
    )
    if not col_ok:
        raise ValueError(f"算子 SQL 未过列策略：{col_msg}")
    if detect_fanout(sql):
        raise ValueError("算子 SQL 触发行数放大保护，已拒绝执行")

    exec_sql = sql
    if ctx.apply_perm and ctx.perm_table:
        missing = [k for k in ("user_column", "scope_column", "data_column") if not ctx.perm_rules.get(k)]
        if missing:
            raise ValueError(f"行级权限配置不完整（缺少 {', '.join(missing)}），已拒绝执行以避免越权取数")
        scope_sql = build_permission_scope_sql(
            user_key=_user_key(ctx.user),
            permission_table=ctx.perm_table,
            scope_column=ctx.perm_rules["scope_column"],
            user_column=ctx.perm_rules["user_column"],
            dialect=dialect,
        )
        exec_sql = inject_permission_filter(
            sql,
            data_column=ctx.perm_rules["data_column"],
            scope_subquery=scope_sql,
            dialect=dialect,
        )
        exec_sql = disambiguate_subquery_columns(exec_sql, dialect=dialect)

    conn = build_connector_from_source(ctx.source)
    try:
        qr = await conn.execute_select(exec_sql)
    except Exception as exc:
        await log_query(
            ctx.db,
            user_id=ctx.user.id if ctx.user else None,
            data_source_id=str(ctx.source.id),
            question=question,
            sql_text=exec_sql,
            row_count=0,
            success=False,
            error_message=str(exc),
        )
        raise ValueError(f"算子 SQL 执行失败：{exc}") from exc
    finally:
        await conn.close()

    await log_query(
        ctx.db,
        user_id=ctx.user.id if ctx.user else None,
        data_source_id=str(ctx.source.id),
        question=question,
        sql_text=exec_sql,
        row_count=qr.row_count,
        success=True,
        error_message=None,
    )
    return {
        "columns": list(qr.columns or []),
        "rows": [list(r) for r in (qr.rows or [])],
        "row_count": int(qr.row_count or 0),
        "exec_sql": exec_sql,
    }


# ───────────────────────────── 指标 / 维度 / 时间窗 ─────────────────────────────


def _metric_def(name: Any) -> MetricDef:
    text = str(name or "").strip()
    if not text:
        raise ValueError("缺少指标（metric）参数")
    if text in METRICS:
        return METRICS[text]
    low = text.lower()
    for m in METRICS.values():
        if text in m.synonyms or low == m.key.lower() or low in {s.lower() for s in m.synonyms}:
            return m
    raise ValueError(
        f"未知指标「{text}」，当前支持：{'、'.join(m.name for m in METRICS.values())}"
    )


_DIM_MAP = {
    "store": "store", "门店": "store", "按门店": "store", "门店维度": "store",
    "day": "day", "日": "day", "按日": "day", "日期": "day", "按天": "day",
    "month": "month", "月": "month", "按月": "month", "月份": "month",
}


def _dimension(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return _DIM_MAP.get(text)


def _dim_param(p: dict[str, Any]) -> str | None:
    """从 params 提取维度：dimensions[]（取首个）/dimension/dim 三种键名兼容。"""
    v = p.get("dimensions")
    if isinstance(v, list):
        v = v[0] if v else None
    v = v or p.get("dimension") or p.get("dim")
    return _dimension(v) if v else None


def _d(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _month_end(d: date) -> date:
    return d.replace(day=monthrange(d.year, d.month)[1])


def _shift_year(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 2/29 → 2/28
        return d.replace(year=d.year - 1, day=28)


def _retail(ctx: OperatorContext) -> tuple[dict | None, dict | None, dict[str, str]]:
    if ctx._retail is None:
        ctx._retail = detect_retail_tables(ctx.table_meta)
    return ctx._retail


async def _latest_biz_date(ctx: OperatorContext) -> str:
    if ctx._latest:
        return ctx._latest
    cols_a, _cols_b, names = _retail(ctx)
    if not cols_a or not names.get("a"):
        raise ValueError("数据源未识别到销售日报表（需 RQ/FDBH/XSJE/ML 列签名），无法执行分析算子")
    rq = cols_a.get("RQ", "RQ")
    conn = build_connector_from_source(ctx.source)
    try:
        qr = await conn.execute_select(f"SELECT MAX({rq}) FROM {names['a']}", limit=1)
    finally:
        await conn.close()
    val = qr.rows[0][0] if qr.rows else None
    if val is None:
        raise ValueError("销售日报表无数据（MAX(RQ) 为空）")
    ctx._latest = str(val)[:10]
    return ctx._latest


async def _resolve_window(ctx: OperatorContext, spec: Any) -> TimeRange:
    """时间窗解析。$今天/$本月/$今年 用日历今天；$最新日 才是 MAX(RQ)。"""
    text = str(spec or "").strip() or "$最新日"
    today = business_today()

    if text == "$最新日":
        latest = await _latest_biz_date(ctx)
        return TimeRange(latest, latest, "annotation")
    if text in ("$今天", "$今日"):
        day = today.isoformat()
        return TimeRange(day, day, "annotation")
    if text in ("$昨天", "$昨日"):
        day = (today - timedelta(days=1)).isoformat()
        return TimeRange(day, day, "annotation")

    m = re.fullmatch(r"\$(?:近|最近)\s*(\d+)\s*天", text)
    if m:
        n = max(1, min(365, int(m.group(1))))
        start = (today - timedelta(days=n - 1)).isoformat()
        return TimeRange(start, today.isoformat(), "annotation")

    if text == "$本周":
        start = (today - timedelta(days=today.weekday())).isoformat()
        return TimeRange(start, today.isoformat(), "annotation")
    if text == "$上周":
        ws = today - timedelta(days=today.weekday() + 7)
        return TimeRange(ws.isoformat(), (ws + timedelta(days=6)).isoformat(), "annotation")
    if text == "$本月":
        return TimeRange(date(today.year, today.month, 1).isoformat(), today.isoformat(), "annotation")
    if text == "$上月":
        pm_last = date(today.year, today.month, 1) - timedelta(days=1)
        return TimeRange(_month_start(pm_last).isoformat(), _month_end(pm_last).isoformat(), "annotation")
    if text == "$今年":
        return TimeRange(date(today.year, 1, 1).isoformat(), today.isoformat(), "annotation")
    if text == "$去年":
        return TimeRange(date(today.year - 1, 1, 1).isoformat(), date(today.year - 1, 12, 31).isoformat(), "annotation")

    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\s*[-~至到—]\s*(\d{4}-\d{2}-\d{2})", text)
    if m:
        lo, hi = sorted([m.group(1), m.group(2)])
        _d(lo), _d(hi)
        return TimeRange(lo, hi, "annotation")

    m = re.fullmatch(r"(\d{4})[-年](\d{1,2})月?", text)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if not 1 <= mo <= 12:
            raise ValueError(f"月份越界：{text}")
        s = date(y, mo, 1)
        return TimeRange(s.isoformat(), _month_end(s).isoformat(), "annotation")

    m = re.fullmatch(r"\d{4}-\d{2}-\d{2}", text)
    if m:
        _d(text)
        return TimeRange(text, text, "annotation")

    raise ValueError(
        f"无法解析时间窗「{text}」。支持：$最新日/$昨天/$近N天/$本周/$上周/$本月/$上月/$今年/$去年、"
        "YYYY-MM-DD、YYYY-MM-DD~YYYY-MM-DD、YYYY-MM"
    )


def _wtext(tr: TimeRange) -> str:
    return tr.start if tr.start == tr.end else f"{tr.start}~{tr.end}"


def _prev_window(tr: TimeRange) -> TimeRange:
    """环比窗口：单日→前一日；整月→上月整月；区间→等长前移。"""
    s, e = _d(tr.start), _d(tr.end)
    if s == e:
        d = (s - timedelta(days=1)).isoformat()
        return TimeRange(d, d, "annotation")
    if s.day == 1 and e == _month_end(e):
        pm_last = _month_start(s) - timedelta(days=1)
        return TimeRange(_month_start(pm_last).isoformat(), _month_end(pm_last).isoformat(), "annotation")
    n = (e - s).days + 1
    pe = s - timedelta(days=1)
    ps = pe - timedelta(days=n - 1)
    return TimeRange(ps.isoformat(), pe.isoformat(), "annotation")


def _year_ago_window(tr: TimeRange) -> TimeRange:
    return TimeRange(
        _shift_year(_d(tr.start)).isoformat(), _shift_year(_d(tr.end)).isoformat(), "annotation"
    )


# ───────────────────────────── 取数与 facts 工具 ─────────────────────────────


def _cell(v: Any) -> Any:
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (date,)):
        return v.isoformat()
    return v


def _num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


def _fact(name: str, value: Any, unit: str, window: str | None = None, compare: Any = None) -> dict[str, Any]:
    f: dict[str, Any] = {"name": str(name), "value": _num(value), "unit": str(unit or "")}
    if window:
        f["window"] = str(window)
    if compare is not None:
        f["compare"] = _num(compare)
    return f


def _sub(a: Any, b: Any) -> float | None:
    x, y = _num(a), _num(b)
    if x is None or y is None:
        return None
    return round(x - y, 4)


def _pct(a: Any, b: Any) -> float | None:
    """变化率：基数无效返回 None。"""
    x, y = _num(a), _num(b)
    if x is None or y is None or y == 0:
        return None
    return round((x - y) / abs(y) * 100, 2)


async def _fetch(
    ctx: OperatorContext,
    *,
    metric: Any,
    dimension: str | None,
    tr: TimeRange,
    order: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """指标层确定性取数：MetricIntent → build_metric_sql → 治理链执行。"""
    md = _metric_def(metric)
    intent = MetricIntent(metrics=[md], dimension=dimension, time=tr, order=order, limit=limit)
    cols_a, cols_b, names = _retail(ctx)
    sql, _expl = build_metric_sql(intent, cols_a, cols_b, names)
    if not sql:
        raise ValueError("指标层无法生成该取数 SQL（表签名/时间窗不满足前置条件）")
    res = await _governed_execute(ctx, sql, question=f"operator:{md.key}|{_wtext(tr)}")
    records = [dict(zip(res["columns"], [_cell(v) for v in row])) for row in res["rows"]]
    return {
        "sql": res["exec_sql"],
        "columns": res["columns"],
        "records": records,
        "row_count": res["row_count"],
        "metric": md,
        "time_range": tr,
    }


def _dim_key(record: dict[str, Any]) -> str | None:
    for c in ("门店", "日期", "月份"):
        v = record.get(c)
        if v is not None:
            return str(v)
    return None


def _val(out: dict[str, Any]) -> Any:
    """汇总值（无维度取数 = 单行单指标）。"""
    md = out["metric"]
    recs = out["records"]
    if not recs:
        return None
    return recs[0].get(md.name)


def _result(
    name: str,
    *,
    facts: list[dict[str, Any]],
    outs: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    res: dict[str, Any] = {"operator": name, "facts": facts[:_MAX_FACTS], "meta": meta or {}}
    outs = outs or []
    if outs:
        res["sql"] = ";\n".join(o["sql"] for o in outs)
        res["row_count"] = sum(o["row_count"] for o in outs)
        rows: list[dict[str, Any]] = []
        for o in outs:
            rows.extend(o["records"][:_MAX_ROWS_IN_RESULT])
        res["rows"] = rows[:_MAX_ROWS_IN_RESULT]
    return res


def _series(out: dict[str, Any]) -> list[tuple[str, float]]:
    """按日序列 [(date, value)]，升序。"""
    md = out["metric"]
    pts: list[tuple[str, float]] = []
    for rec in out["records"]:
        d, v = rec.get("日期"), _num(rec.get(md.name))
        if d is not None and v is not None:
            pts.append((str(d)[:10], v))
    pts.sort()
    return pts


def _linreg(vals: list[float]) -> tuple[float, float]:
    """最小二乘：返回 (斜率, 截距)。"""
    n = len(vals)
    xs = list(range(n))
    mx, my = mean(xs), mean(vals)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0, my
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, vals)) / denom
    return slope, my - slope * mx


# ───────────────────────────── 8 个算子 ─────────────────────────────


async def op_metric_query(ctx: OperatorContext, p: dict[str, Any]) -> dict[str, Any]:
    """按指标 + 维度 + 时间窗取数。"""
    dimension = _dim_param(p)
    tr = await _resolve_window(ctx, p.get("time_range"))
    order = "desc" if dimension == "store" else None
    out = await _fetch(ctx, metric=p.get("metric"), dimension=dimension, tr=tr, order=order)

    md = out["metric"]
    w = _wtext(tr)
    facts: list[dict[str, Any]] = []
    if dimension is None:
        facts.append(_fact(md.name, _val(out), md.unit, window=w))
    else:
        for rec in out["records"]:
            k = _dim_key(rec)
            facts.append(_fact(f"{k} {md.name}", rec.get(md.name), md.unit, window=w))
    return _result(
        "metric_query",
        facts=facts,
        outs=[out],
        meta={"metric": md.name, "dimension": dimension, "time_range": w, "row_count": out["row_count"]},
    )


async def _compare_impl(
    ctx: OperatorContext,
    p: dict[str, Any],
    *,
    op_name: str,
    label: str,
    shift,
    default_window: str,
) -> dict[str, Any]:
    """同比/环比共用的两窗口对比。"""
    dimension = _dim_param(p)
    tr = await _resolve_window(ctx, p.get("time_range") or default_window)
    tr_prev = shift(tr)
    cur = await _fetch(ctx, metric=p.get("metric"), dimension=dimension, tr=tr)
    prev = await _fetch(ctx, metric=p.get("metric"), dimension=dimension, tr=tr_prev)
    md = cur["metric"]
    w, wp = _wtext(tr), _wtext(tr_prev)

    facts: list[dict[str, Any]] = []
    if dimension is None:
        c, b = _val(cur), _val(prev)
        if md.ratio:
            delta_unit, delta = "百分点", _sub(c, b)
        else:
            delta_unit, delta = md.unit, _sub(c, b)
        facts = [
            _fact(f"{md.name}（本期）", c, md.unit, window=w),
            _fact(f"{md.name}（{label}期）", b, md.unit, window=wp),
            _fact(f"{label}增减", delta, delta_unit, window=w),
            _fact(f"{label}增幅", _pct(c, b), "百分点" if md.ratio else "%", window=w),
        ]
        meta_rows: list[dict[str, Any]] = []
    else:
        cur_map = {_dim_key(r): _num(r.get(md.name)) for r in cur["records"]}
        prev_map = {_dim_key(r): _num(r.get(md.name)) for r in prev["records"]}
        meta_rows = []
        for k, c in cur_map.items():
            b = prev_map.get(k)
            row = {"维度": k, "本期": c, f"{label}期": b, f"{label}增幅": _pct(c, b)}
            meta_rows.append(row)
            facts.append(_fact(f"{k} {md.name}", c, md.unit, window=w, compare=b))
        # 按 |增幅| 排序，变化最大的排前
        meta_rows.sort(key=lambda r: abs(r[f"{label}增幅"]) if r[f"{label}增幅"] is not None else -1, reverse=True)
        facts = facts[:_MAX_FACTS]

    return {
        "operator": op_name,
        "facts": facts,
        "sql": ";\n".join([cur["sql"], prev["sql"]]),
        "row_count": cur["row_count"] + prev["row_count"],
        "rows": meta_rows[:_MAX_ROWS_IN_RESULT],
        "meta": {
            "metric": md.name,
            "dimension": dimension,
            "window": w,
            "compare_window": wp,
            "row_count": cur["row_count"] + prev["row_count"],
        },
    }


async def op_yoy_compare(ctx: OperatorContext, p: dict[str, Any]) -> dict[str, Any]:
    """同比对比：本期 vs 去年同期（单日/整月/区间整体平移一年）。"""
    return await _compare_impl(
        ctx, p, op_name="yoy_compare", label="同比", shift=_year_ago_window, default_window="$本月"
    )


async def op_mom_compare(ctx: OperatorContext, p: dict[str, Any]) -> dict[str, Any]:
    """环比对比：本期 vs 上一期（单日→前一日，整月→上月，区间→等长前移）。"""
    return await _compare_impl(
        ctx, p, op_name="mom_compare", label="环比", shift=_prev_window, default_window="$最新日"
    )


async def op_topn_rank(ctx: OperatorContext, p: dict[str, Any]) -> dict[str, Any]:
    """TOP N 排名（默认门店维度降序）。"""
    try:
        n = int(p.get("n") or p.get("top") or 10)
    except (TypeError, ValueError):
        n = 10
    n = max(1, min(100, n))
    dim = _dimension(p.get("dim") or p.get("dimension")) or "store"
    order = "asc" if str(p.get("order") or "desc").lower() == "asc" else "desc"
    tr = await _resolve_window(ctx, p.get("time_range"))
    out = await _fetch(ctx, metric=p.get("metric"), dimension=dim, tr=tr, order=order, limit=n)

    md = out["metric"]
    w = _wtext(tr)
    facts = []
    for i, rec in enumerate(out["records"], 1):
        k = _dim_key(rec)
        facts.append(_fact(f"TOP{i} {k}", rec.get(md.name), md.unit, window=w))
    return _result(
        "topn_rank",
        facts=facts,
        outs=[out],
        meta={"metric": md.name, "dim": dim, "n": n, "order": order, "time_range": w},
    )


async def op_share_of_total(ctx: OperatorContext, p: dict[str, Any]) -> dict[str, Any]:
    """占比/构成：各维度项占总计比例。"""
    dim = _dimension(p.get("by_dim") or p.get("dim") or p.get("dimension")) or "store"
    tr = await _resolve_window(ctx, p.get("time_range"))
    out = await _fetch(ctx, metric=p.get("metric"), dimension=dim, tr=tr, order="desc", limit=200)

    md = out["metric"]
    w = _wtext(tr)
    items = []
    for rec in out["records"]:
        k, v = _dim_key(rec), _num(rec.get(md.name))
        if k is not None and v is not None:
            items.append((k, v))
    total = sum(v for _, v in items)
    if not items or total == 0:
        raise ValueError(f"时间窗 {w} 内「{md.name}」无有效数据，无法计算占比")

    rows = []
    facts = []
    top5 = 0.0
    for i, (k, v) in enumerate(items):
        share = round(v / total * 100, 2)
        rows.append({"维度": k, md.name: v, "占比%": share})
        if i < 5:
            facts.append(_fact(f"{k} 占比", share, "%", window=w))
            top5 += share
    facts.append(_fact("TOP5 集中度", round(top5, 2), "%", window=w))
    facts.append(_fact("总计", total, md.unit, window=w))
    return {
        "operator": "share_of_total",
        "facts": facts,
        "sql": out["sql"],
        "row_count": out["row_count"],
        "rows": rows[:_MAX_ROWS_IN_RESULT],
        "meta": {"metric": md.name, "by_dim": dim, "time_range": w, "total": total},
    }


async def op_trend_detect(ctx: OperatorContext, p: dict[str, Any]) -> dict[str, Any]:
    """趋势与突变点：最小二乘斜率 + 相邻差值超 sensitivity×std 判定变点。"""
    try:
        sens = float(p.get("sensitivity") or 1.5)
    except (TypeError, ValueError):
        sens = 1.5
    tr = await _resolve_window(ctx, p.get("time_range") or "$近30天")
    out = await _fetch(ctx, metric=p.get("metric"), dimension="day", tr=tr)

    md = out["metric"]
    w = _wtext(tr)
    pts = _series(out)
    if len(pts) < 3:
        raise ValueError(f"时间窗 {w} 内序列点不足（{len(pts)} < 3），无法做趋势检测")
    vals = [v for _, v in pts]
    slope, _intercept = _linreg(vals)
    avg = mean(vals)
    diffs = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
    dstd = pstdev(diffs) if len(diffs) >= 2 else 0.0

    changepoints = []
    for i in range(len(pts) - 1):
        delta = vals[i + 1] - vals[i]
        if dstd > 0 and abs(delta) > sens * dstd:
            changepoints.append({
                "date": pts[i + 1][0], "from": vals[i], "to": vals[i + 1],
                "delta": round(delta, 4), "direction": "up" if delta > 0 else "down",
            })

    facts = [
        _fact(f"日均{md.name}", round(avg, 2), md.unit, window=w),
        _fact("日均变化（斜率）", round(slope, 4), f"{md.unit}/天", window=w),
        _fact("期间累计", round(sum(vals), 2), md.unit, window=w),
        _fact("最大单日上涨", round(max(diffs), 2) if diffs else None, md.unit, window=w),
        _fact("最大单日下跌", round(min(diffs), 2) if diffs else None, md.unit, window=w),
        _fact("突变点数", len(changepoints), "个", window=w),
    ]
    return _result(
        "trend_detect",
        facts=facts,
        outs=[out],
        meta={
            "metric": md.name, "time_range": w, "sensitivity": sens,
            "points": len(pts), "changepoints": changepoints[:10],
        },
    )


async def op_forecast_simple(ctx: OperatorContext, p: dict[str, Any]) -> dict[str, Any]:
    """简单预测：线性外推 / 移动平均。"""
    method = str(p.get("method") or "linear").lower()
    if method not in ("linear", "moving_avg", "moving_average", "ma"):
        method = "linear"
    try:
        periods = int(p.get("periods") or 7)
    except (TypeError, ValueError):
        periods = 7
    periods = max(1, min(60, periods))
    try:
        ma_window = int(p.get("window") or 7)
    except (TypeError, ValueError):
        ma_window = 7
    ma_window = max(2, min(30, ma_window))

    tr = await _resolve_window(ctx, p.get("time_range") or p.get("history_window") or "$近90天")
    out = await _fetch(ctx, metric=p.get("metric"), dimension="day", tr=tr)

    md = out["metric"]
    w = _wtext(tr)
    pts = _series(out)
    if len(pts) < 5:
        raise ValueError(f"时间窗 {w} 内序列点不足（{len(pts)} < 5），无法做预测")
    vals = [v for _, v in pts]
    last_date = _d(pts[-1][0])

    forecast: list[dict[str, Any]] = []
    if method in ("moving_avg", "moving_average", "ma"):
        base = mean(vals[-ma_window:])
        for i in range(1, periods + 1):
            d = (last_date + timedelta(days=i)).isoformat()
            forecast.append({"date": d, "value": round(base, 2)})
    else:
        slope, intercept = _linreg(vals)
        n = len(vals)
        for i in range(1, periods + 1):
            d = (last_date + timedelta(days=i)).isoformat()
            forecast.append({"date": d, "value": round(intercept + slope * (n - 1 + i), 2)})

    facts = [_fact(f"预测{f['date']}", f["value"], md.unit, window=f["date"]) for f in forecast[:7]]
    facts.append(_fact(f"未来{periods}天合计", round(sum(f["value"] for f in forecast), 2), md.unit, window=w))
    return _result(
        "forecast_simple",
        facts=facts,
        outs=[out],
        meta={
            "metric": md.name, "method": "moving_avg" if method != "linear" else "linear",
            "periods": periods, "history_window": w, "history_points": len(pts),
            "forecast": forecast,
        },
    )


async def op_anomaly_detect(ctx: OperatorContext, p: dict[str, Any]) -> dict[str, Any]:
    """异常值检测：z-score / IQR。"""
    method = str(p.get("method") or "zscore").lower()
    if method not in ("zscore", "z", "iqr"):
        method = "zscore"
    try:
        threshold = float(p.get("threshold") or (3.0 if method != "iqr" else 1.5))
    except (TypeError, ValueError):
        threshold = 3.0 if method != "iqr" else 1.5

    tr = await _resolve_window(ctx, p.get("time_range") or "$近30天")
    out = await _fetch(ctx, metric=p.get("metric"), dimension="day", tr=tr)

    md = out["metric"]
    w = _wtext(tr)
    pts = _series(out)
    if len(pts) < 5:
        raise ValueError(f"时间窗 {w} 内序列点不足（{len(pts)} < 5），无法做异常检测")
    vals = [v for _, v in pts]

    anomalies: list[dict[str, Any]] = []
    if method == "iqr":
        sv = sorted(vals)
        n = len(sv)
        q1 = sv[max(0, int(n * 0.25) - 1)] if n >= 4 else sv[0]
        q3 = sv[min(n - 1, int(n * 0.75))] if n >= 4 else sv[-1]
        iqr = q3 - q1
        lo, hi = q1 - threshold * iqr, q3 + threshold * iqr
        for d, v in pts:
            if v < lo or v > hi:
                anomalies.append({
                    "date": d, "value": round(v, 2),
                    "score": round((v - (q1 + q3) / 2) / iqr, 2) if iqr > 0 else 0.0,
                    "direction": "high" if v > hi else "low",
                })
        spread = round(iqr, 2)
        spread_name = "四分位距"
    else:
        avg = mean(vals)
        sd = pstdev(vals)
        for d, v in pts:
            if sd > 0 and abs((v - avg) / sd) > threshold:
                anomalies.append({
                    "date": d, "value": round(v, 2),
                    "score": round((v - avg) / sd, 2),
                    "direction": "high" if v > avg else "low",
                })
        spread = round(sd, 2)
        spread_name = "标准差"

    facts = [
        _fact(f"平均{md.name}", round(mean(vals), 2), md.unit, window=w),
        _fact(spread_name, spread, md.unit, window=w),
        _fact("异常天数", len(anomalies), "天", window=w),
        _fact("最大值", round(max(vals), 2), md.unit, window=w),
        _fact("最小值", round(min(vals), 2), md.unit, window=w),
    ]
    return _result(
        "anomaly_detect",
        facts=facts,
        outs=[out],
        meta={
            "metric": md.name, "method": method, "threshold": threshold,
            "time_range": w, "points": len(pts), "anomalies": anomalies[:10],
        },
    )


# ───────────────────────────── 注册表与入口 ─────────────────────────────


@dataclass(frozen=True)
class OperatorSpec:
    name: str
    display_name: str
    description: str
    handler: Any
    parameters_schema: dict[str, Any]


_TIME_RANGE_PROP = {
    "type": "string",
    "description": "时间窗：$最新日/$昨天/$近N天/$本周/$上周/$本月/$上月/$今年/$去年，"
    "或 YYYY-MM-DD / YYYY-MM-DD~YYYY-MM-DD / YYYY-MM",
}
_METRIC_PROP = {
    "type": "string",
    "description": "指标名：销售额/毛利/毛利率/销售成本/交易笔数/客流营业额/客单价/门店数/日均销售额/店均销售额（支持同义词）",
}


OPERATORS: dict[str, OperatorSpec] = {
    "metric_query": OperatorSpec(
        "metric_query", "指标取数",
        "按指标 + 维度（门店/日/月）+ 时间窗取数，返回确定性事实",
        op_metric_query,
        {
            "type": "object",
            "properties": {
                "metric": _METRIC_PROP,
                "dimensions": {"type": "array", "items": {"type": "string"}, "description": "维度：store/day/month（可省略=汇总）"},
                "time_range": _TIME_RANGE_PROP,
            },
            "required": ["metric"],
        },
    ),
    "yoy_compare": OperatorSpec(
        "yoy_compare", "同比对比",
        "本期 vs 去年同期（窗口整体平移一年），返回两期值/增减/增幅",
        op_yoy_compare,
        {
            "type": "object",
            "properties": {
                "metric": _METRIC_PROP,
                "time_range": _TIME_RANGE_PROP,
                "dimensions": {"type": "array", "items": {"type": "string"}, "description": "按维度对比（可省略=汇总级）"},
            },
            "required": ["metric"],
        },
    ),
    "mom_compare": OperatorSpec(
        "mom_compare", "环比对比",
        "本期 vs 上一期（单日→前一日，整月→上月，区间→等长前移）",
        op_mom_compare,
        {
            "type": "object",
            "properties": {
                "metric": _METRIC_PROP,
                "time_range": _TIME_RANGE_PROP,
                "dimensions": {"type": "array", "items": {"type": "string"}, "description": "按维度对比（可省略=汇总级）"},
            },
            "required": ["metric"],
        },
    ),
    "topn_rank": OperatorSpec(
        "topn_rank", "TOP N 排名",
        "按维度取指标前 N 名（默认门店维度降序）",
        op_topn_rank,
        {
            "type": "object",
            "properties": {
                "metric": _METRIC_PROP,
                "dim": {"type": "string", "description": "排名维度：store（默认）/day/month"},
                "n": {"type": "integer", "description": "取前 N 名（默认 10）"},
                "order": {"type": "string", "description": "desc（默认）/asc"},
                "time_range": _TIME_RANGE_PROP,
            },
            "required": ["metric"],
        },
    ),
    "share_of_total": OperatorSpec(
        "share_of_total", "占比构成",
        "各维度项占总计的比例与 TOP5 集中度",
        op_share_of_total,
        {
            "type": "object",
            "properties": {
                "metric": _METRIC_PROP,
                "by_dim": {"type": "string", "description": "构成维度：store（默认）/day/month"},
                "time_range": _TIME_RANGE_PROP,
            },
            "required": ["metric"],
        },
    ),
    "trend_detect": OperatorSpec(
        "trend_detect", "趋势检测",
        "日序列趋势（最小二乘斜率）与突变点（相邻差超 sensitivity×std）",
        op_trend_detect,
        {
            "type": "object",
            "properties": {
                "metric": _METRIC_PROP,
                "time_range": _TIME_RANGE_PROP,
                "sensitivity": {"type": "number", "description": "突变灵敏度（默认 1.5，越大越不敏感）"},
            },
            "required": ["metric"],
        },
    ),
    "forecast_simple": OperatorSpec(
        "forecast_simple", "简单预测",
        "线性外推 / 移动平均预测未来 N 天",
        op_forecast_simple,
        {
            "type": "object",
            "properties": {
                "metric": _METRIC_PROP,
                "periods": {"type": "integer", "description": "预测天数（默认 7）"},
                "method": {"type": "string", "description": "linear（默认）/moving_avg"},
                "window": {"type": "integer", "description": "移动平均窗口（默认 7）"},
                "time_range": _TIME_RANGE_PROP,
            },
            "required": ["metric"],
        },
    ),
    "anomaly_detect": OperatorSpec(
        "anomaly_detect", "异常检测",
        "日序列异常值检测（z-score / IQR）",
        op_anomaly_detect,
        {
            "type": "object",
            "properties": {
                "metric": _METRIC_PROP,
                "time_range": _TIME_RANGE_PROP,
                "method": {"type": "string", "description": "zscore（默认）/iqr"},
                "threshold": {"type": "number", "description": "zscore 默认 3.0 / iqr 默认 1.5"},
            },
            "required": ["metric"],
        },
    ),
}


async def run_operator(
    db: AsyncSession,
    *,
    operator: str,
    data_source_id: str,
    params: dict[str, Any] | None = None,
    user: User | None = None,
) -> dict[str, Any]:
    """算子统一入口：构建上下文 → 执行 handler → 返回 facts。"""
    name = str(operator or "").strip()
    spec = OPERATORS.get(name)
    if not spec:
        from app.core.data_ask.blueprint_finish import run_http_operator
        try:
            return await run_http_operator(db, name=name, params=params)
        except ValueError as exc:
            if not str(exc).startswith("未知分析算子"):
                raise
        raise ValueError(f"未知分析算子「{operator}」，可用：{', '.join(OPERATORS)}")
    ctx = await build_operator_context(db, data_source_id, user=user)
    try:
        out = await spec.handler(ctx, dict(params or {}))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"算子 {name} 执行失败：{exc}") from exc
    out.setdefault("operator", name)
    out.setdefault("facts", [])
    out.setdefault("meta", {})
    return out
