"""AnalysisSpec 规范化与 SQL 生成（确定性，无 LLM 参与）。"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
from typing import Any

SPEC_TYPES = (
    "aggregate", "timeseries", "distribution", "topn", "detail",
    # P1 诊断算子
    "period_compare", "contribution", "breakdown", "outlier", "pareto",
    # P2 预测与统计算子
    "forecast", "correlation", "cluster", "cohort", "funnel",
    # P4 处方算子（A4 What-if / 因果推断）
    "whatif",
    "impact",
)

# 派生算子先取基础结果集，再由 Python 计算派生列（不依赖各数据库窗口函数方言）
BASE_TYPES: dict[str, str] = {
    "period_compare": "timeseries",
    "forecast": "timeseries",
    "contribution": "distribution",
    "breakdown": "distribution",
    "outlier": "distribution",
    "pareto": "distribution",
    "correlation": "distribution",
    "cluster": "distribution",
    "cohort": "cohort",
    "funnel": "distribution",
    "whatif": "distribution",
}

DERIVED_TYPES = set(BASE_TYPES)

_DEFAULT_LIMIT = {
    "period_compare": 400, "contribution": 100, "breakdown": 200,
    "outlier": 500, "pareto": 100, "forecast": 400,
    "correlation": 200, "cluster": 200, "cohort": 800, "funnel": 100,
    "whatif": 200, "impact": 400,
}

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FORBIDDEN_VALUE = re.compile(r"(;|--|/\*|\*/)", re.I)


class SpecError(ValueError):
    """规格不合法。"""

    def __init__(self, message: str, code: str = "spec_invalid"):
        super().__init__(message)
        self.code = code


def max_limit() -> int:
    try:
        return max(1, int(os.getenv("ANALYSIS_SPEC_MAX_LIMIT", "1000")))
    except ValueError:
        return 1000


def query_timeout() -> int:
    try:
        return max(5, int(os.getenv("ANALYSIS_QUERY_TIMEOUT", "60")))
    except ValueError:
        return 60


def _options(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SpecError("options 必须是对象")
    return dict(raw)


def _opt_int(options: dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(options.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(value, hi))


def _opt_float(options: dict[str, Any], key: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(options.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(value, hi))


def normalize_spec(raw: dict[str, Any]) -> dict[str, Any]:
    """校验并补全规格；所有后续 SQL 生成只消费规范化后的结果。"""
    if not isinstance(raw, dict):
        raise SpecError("spec 必须是对象")
    stype = str(raw.get("type") or "").strip()
    if stype not in SPEC_TYPES:
        raise SpecError(f"不支持的 type: {stype}")
    if not str(raw.get("data_source_id") or "").strip():
        raise SpecError("data_source_id 必填")

    metrics_in = raw.get("metrics") or []
    if not isinstance(metrics_in, list):
        raise SpecError("metrics 必须是数组")
    metrics: list[dict[str, str]] = []
    for i, m in enumerate(metrics_in):
        if not isinstance(m, dict):
            raise SpecError(f"metrics[{i}] 必须是对象")
        expr = str(m.get("expr") or "").strip()
        if not expr:
            raise SpecError(f"metrics[{i}].expr 必填")
        if _FORBIDDEN_VALUE.search(expr):
            raise SpecError(f"metrics[{i}].expr 含非法字符", "spec_invalid")
        alias = str(m.get("alias") or "").strip()
        if not IDENT.match(alias):
            alias = f"m{i}"
        metrics.append({
            "name": str(m.get("name") or alias),
            "expr": expr,
            "alias": alias,
        })
    if stype not in ("detail", "cohort") and not metrics:
        raise SpecError("metrics 不能为空")

    dims_in = raw.get("dimensions") or []
    if not isinstance(dims_in, list):
        raise SpecError("dimensions 必须是数组")
    dims: list[str] = []
    for d in dims_in:
        name = str(d or "").strip()
        if not IDENT.match(name):
            raise SpecError(f"非法维度: {name}", "unknown_dimension")
        dims.append(name)

    filters_in = raw.get("filters") or []
    filters: list[dict[str, Any]] = []
    for f in filters_in:
        if not isinstance(f, dict):
            raise SpecError("filters 元素必须是对象")
        field = str(f.get("field") or "").strip()
        if not IDENT.match(field):
            raise SpecError(f"非法筛选字段: {field}", "unknown_dimension")
        op = str(f.get("op") or "eq")
        if op not in ("eq", "ne", "gt", "gte", "lt", "lte", "in", "between", "like"):
            raise SpecError(f"不支持的筛选操作: {op}")
        filters.append({"field": field, "op": op, "value": f.get("value")})

    time_range = raw.get("time_range")
    if time_range:
        if not isinstance(time_range, dict):
            raise SpecError("time_range 必须是对象")
        field = str(time_range.get("field") or "").strip()
        if not IDENT.match(field):
            raise SpecError("time_range.field 非法")
        gran = str(time_range.get("granularity") or "day")
        if gran not in ("day", "week", "month", "quarter", "year"):
            raise SpecError(f"不支持的时间粒度: {gran}")
        time_range = {
            "field": field,
            "start": time_range.get("start"),
            "end": time_range.get("end"),
            "granularity": gran,
        }
    if stype in ("timeseries", "period_compare", "forecast") and not time_range:
        raise SpecError(f"{stype} 必须提供 time_range")

    order_by = raw.get("order_by") or []
    orders: list[dict[str, Any]] = []
    for o in order_by[:3]:
        if isinstance(o, dict) and str(o.get("field") or "").strip():
            orders.append({"field": str(o["field"]).strip(), "desc": bool(o.get("desc", True))})

    options = _options(raw.get("options"))

    # ── 派生算子的参数约束 ──────────────────────────────
    if stype in ("contribution", "breakdown", "outlier", "pareto", "funnel", "cluster") and not dims:
        raise SpecError(f"{stype} 需要 dimensions")
    if stype == "breakdown" and len(dims) < 2:
        raise SpecError("breakdown 需要两个维度（父 / 子）")
    if stype == "correlation" and len(metrics) != 2:
        raise SpecError("correlation 需要两个指标")
    if stype == "cluster" and len(metrics) < 2:
        raise SpecError("cluster 至少需要两个指标")
    if stype == "cohort":
        entity = str(options.get("entity_field") or "").strip()
        if not IDENT.match(entity):
            raise SpecError("cohort 需要 options.entity_field")
        options["entity_field"] = entity
        if not time_range:
            raise SpecError("cohort 必须提供 time_range")
        if time_range["granularity"] not in ("month", "week", "quarter", "year"):
            raise SpecError("cohort 的时间粒度需为 month/week/quarter/year")
    if stype == "funnel":
        stages = options.get("stages")
        if not isinstance(stages, list) or not stages:
            raise SpecError("funnel 需要 options.stages")
        clean: list[dict[str, Any]] = []
        for i, s in enumerate(stages[:8]):
            if not isinstance(s, dict):
                raise SpecError(f"stages[{i}] 必须是对象")
            try:
                minimum = float(s.get("min"))
            except (TypeError, ValueError):
                raise SpecError(f"stages[{i}].min 必须是数字")
            if clean and minimum < clean[-1]["min"]:
                raise SpecError("funnel 阶段阈值必须逐级不降低（宽 → 窄）")
            clean.append({"name": str(s.get("name") or f"阶段{i + 1}"), "min": minimum})
        options["stages"] = clean
    if stype == "outlier":
        options["threshold"] = _opt_float(options, "threshold", 2.0, 0.5, 10.0)
    if stype == "pareto":
        options["cutoff"] = _opt_float(options, "cutoff", 80.0, 40.0, 100.0)
    if stype == "forecast":
        options["horizon"] = _opt_int(options, "horizon", 3, 1, 12)
    if stype == "cluster":
        options["k"] = _opt_int(options, "k", 3, 2, 6)
    if stype == "period_compare":
        mode = str(options.get("mode") or "mom").lower()
        options["mode"] = mode if mode in ("mom", "yoy") else "mom"
    if stype == "whatif":
        # A4 What-if：metrics 顺序固定为 销售额 / 销量 / 毛利（单价与成本由其推导）
        if len(metrics) != 3:
            raise SpecError("whatif 需要三个指标且顺序为 销售额 / 销量 / 毛利")
        options["price_change_pct"] = _opt_float(options, "price_change_pct", 5.0, -90.0, 100.0)
        options["elasticity"] = _opt_float(options, "elasticity", -1.5, -5.0, 0.0)
        if options.get("volume_change_pct") is not None:
            options["volume_change_pct"] = _opt_float(options, "volume_change_pct", 0.0, -95.0, 500.0)
    if stype == "impact":
        # A4 因果推断：事件日前后 × 处理组/对照组 双重差分（DID）
        if len(metrics) != 1:
            raise SpecError("impact 只允许一个指标")
        if not time_range or not time_range.get("start") or not time_range.get("end"):
            raise SpecError("impact 必须提供 time_range.start/end")
        ev = str(options.get("event_date") or "")
        try:
            datetime.date.fromisoformat(ev)
        except ValueError as exc:
            raise SpecError("impact 需要 options.event_date（YYYY-MM-DD）") from exc
        if not (str(time_range["start"]) < ev <= str(time_range["end"])):
            raise SpecError("event_date 必须落在 (start, end] 内，保证事件前后各至少一天")
        treat = options.get("treatment")
        if not isinstance(treat, dict) or not IDENT.match(str(treat.get("field") or "")):
            raise SpecError("impact 需要 options.treatment {field, value}")
        if treat.get("value") in (None, ""):
            raise SpecError("options.treatment.value 不能为空")
        time_range["granularity"] = "day"  # DID 按日切分前后窗口

    try:
        limit = int(raw.get("limit") or _DEFAULT_LIMIT.get(stype, 100))
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT.get(stype, 100)
    limit = max(1, min(limit, max_limit()))

    name = str(raw.get("name") or "").strip()
    if not name:
        labels = [m["name"] for m in metrics] or dims or ["分析"]
        name = " / ".join(labels[:3])[:120]

    return {
        "type": stype,
        "base": BASE_TYPES.get(stype, stype),
        "data_source_id": str(raw["data_source_id"]).strip(),
        "metrics": metrics,
        "dimensions": dims,
        "filters": filters,
        "time_range": time_range,
        "order_by": orders,
        "limit": limit,
        "options": options,
        "name": name,
    }


def spec_hash(spec: dict[str, Any]) -> str:
    payload = json.dumps(spec, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def quote_alias(name: str, driver: str = "") -> str:
    safe = name.replace('"', '""')
    if (driver or "").lower() in ("mysql", "doris", "hive"):
        return "`" + safe.replace("`", "``") + "`"
    return '"' + safe + '"'


def quote_literal(value: Any, driver: str = "") -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if _FORBIDDEN_VALUE.search(text):
        raise SpecError("筛选值含非法字符")
    if (driver or "").lower() in ("mysql", "doris", "hive"):
        return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"
    return "'" + text.replace("'", "''") + "'"


def _date_expr(field: str, granularity: str, driver: str) -> str:
    d = (driver or "").lower()
    if granularity == "day":
        if d in ("mysql", "doris"):
            return f"DATE({field})"
        if d == "hive":
            return f"TO_DATE({field})"
        return f"CAST({field} AS DATE)"
    if granularity == "month":
        if d in ("mysql", "doris"):
            return f"DATE_FORMAT({field}, '%Y-%m')"
        if d == "hive":
            return f"DATE_FORMAT({field}, 'yyyy-MM')"
        return f"TO_CHAR({field}, 'YYYY-MM')"
    if granularity == "week":
        if d in ("mysql", "doris"):
            return f"DATE_FORMAT({field}, '%x-%v')"
        if d == "hive":
            return f"DATE_FORMAT({field}, 'yyyy-ww')"
        return f"TO_CHAR({field}, 'IYYY-IW')"
    if granularity == "quarter":
        if d == "hive":
            return f"CONCAT(YEAR({field}), '-Q', CEIL(MONTH({field}) / 3))"
        if d in ("mysql", "doris"):
            return f"CONCAT(YEAR({field}), '-Q', QUARTER({field}))"
        return f"TO_CHAR({field}, 'YYYY-\"Q\"Q')"
    if d in ("mysql", "doris"):
        return f"YEAR({field})"
    if d == "hive":
        return f"YEAR({field})"
    return f"TO_CHAR({field}, 'YYYY')"


def _where_clause(spec: dict[str, Any], driver: str) -> str:
    parts: list[str] = []
    for f in spec["filters"]:
        field, op, value = f["field"], f["op"], f["value"]
        if op == "in":
            vals = value if isinstance(value, (list, tuple)) else [value]
            if not vals:
                # 空白名单 = 不可见任何行（行级权限语义），恒假条件
                parts.append("1 = 0")
                continue
            parts.append(f"{field} IN ({', '.join(quote_literal(v, driver) for v in vals)})")
        elif op == "between":
            vals = value if isinstance(value, (list, tuple)) else []
            if len(vals) != 2:
                raise SpecError("between 需要两个值")
            parts.append(f"{field} BETWEEN {quote_literal(vals[0], driver)} AND {quote_literal(vals[1], driver)}")
        elif op == "like":
            parts.append(f"{field} LIKE {quote_literal(value, driver)}")
        else:
            sym = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
            parts.append(f"{field} {sym} {quote_literal(value, driver)}")

    tr = spec.get("time_range")
    if tr:
        if tr.get("start"):
            parts.append(f"{tr['field']} >= {quote_literal(tr['start'], driver)}")
        if tr.get("end"):
            parts.append(f"{tr['field']} <= {quote_literal(tr['end'], driver)}")
    return (" WHERE " + " AND ".join(parts)) if parts else ""


def build_sql(spec: dict[str, Any], table: str, driver: str = "") -> str:
    """把规范化规格编译成单条 SELECT（派生算子编译其基础结果集）。"""
    base = spec.get("base") or spec["type"]
    select_parts: list[str] = []
    group_parts: list[str] = []
    order_parts: list[str] = []
    time_alias = ""

    if base == "detail":
        select_parts.append("*")
    elif base == "cohort":
        tr = spec["time_range"]
        entity = spec["options"]["entity_field"]
        time_alias = "t_period"
        select_parts.append(f"{entity} AS {quote_alias('entity', driver)}")
        select_parts.append(f"{_date_expr(tr['field'], tr['granularity'], driver)} AS {quote_alias(time_alias, driver)}")
        if spec["metrics"]:
            for m in spec["metrics"]:
                select_parts.append(f"{m['expr']} AS {quote_alias(m['alias'], driver)}")
        else:
            select_parts.append(f"COUNT(*) AS {quote_alias('n', driver)}")
        group_parts.extend([quote_alias("entity", driver), quote_alias(time_alias, driver)])
        order_parts.append(f"{quote_alias('entity', driver)} ASC")
        order_parts.append(f"{quote_alias(time_alias, driver)} ASC")
    else:
        if base == "timeseries":
            tr = spec["time_range"]
            time_alias = "t_period"
            expr = _date_expr(tr["field"], tr["granularity"], driver)
            select_parts.append(f"{expr} AS {quote_alias(time_alias, driver)}")
            group_parts.append(quote_alias(time_alias, driver))
        for dim in spec["dimensions"]:
            select_parts.append(f"{dim} AS {quote_alias(dim, driver)}")
            group_parts.append(quote_alias(dim, driver))
        for m in spec["metrics"]:
            select_parts.append(f"{m['expr']} AS {quote_alias(m['alias'], driver)}")

    if base == "timeseries":
        order_parts.append(f"{quote_alias(time_alias, driver)} ASC")
    if spec["order_by"]:
        for o in spec["order_by"]:
            field = o["field"]
            ident = quote_alias(field, driver) if IDENT.match(field) else field
            order_parts.append(f"{ident} {'DESC' if o['desc'] else 'ASC'}")
    elif spec["type"] == "breakdown" and spec["dimensions"] and spec["metrics"]:
        order_parts.append(f"{quote_alias(spec['dimensions'][0], driver)} ASC")
        order_parts.append(f"{quote_alias(spec['metrics'][0]['alias'], driver)} DESC")
    elif spec["type"] in ("distribution", "topn", "contribution", "pareto", "outlier",
                          "correlation", "cluster", "funnel", "whatif") and spec["metrics"]:
        order_parts.append(f"{quote_alias(spec['metrics'][0]['alias'], driver)} DESC")

    sql = f"SELECT {', '.join(select_parts)} FROM {table}"
    sql += _where_clause(spec, driver)
    if group_parts:
        sql += " GROUP BY " + ", ".join(group_parts)
    if order_parts:
        sql += " ORDER BY " + ", ".join(order_parts)
    sql += f" LIMIT {int(spec['limit'])}"
    return sql


def chart_hint(spec: dict[str, Any]) -> dict[str, Any]:
    stype = spec["type"]
    aliases = [m["alias"] for m in spec["metrics"]]
    if stype == "timeseries":
        return {"type": "line", "x": "t_period", "series": aliases}
    if stype == "period_compare":
        return {"type": "bar", "x": "时间", "series": ["变化率%"], "group": "指标"}
    if stype == "forecast":
        return {"type": "line", "x": "时间", "series": ["值"], "forecast": True}
    if stype in ("contribution", "pareto"):
        return {"type": "pareto_bar", "x": "维度", "series": ["指标值"], "cumulative": "累计占比%"}
    if stype == "breakdown":
        return {"type": "bar", "x": "父维度", "series": ["指标值"], "group": "子维度"}
    if stype == "outlier":
        return {"type": "anomaly_scatter", "x": "维度", "y": "指标值", "z": "Z值"}
    if stype == "correlation":
        return {"type": "scatter", "x": aliases[0] if aliases else "", "y": aliases[1] if len(aliases) > 1 else ""}
    if stype == "cluster":
        return {"type": "scatter", "x": aliases[0] if aliases else "", "y": aliases[1] if len(aliases) > 1 else "", "color": "cluster"}
    if stype == "cohort":
        return {"type": "heatmap", "x": "期数", "y": "同期群"}
    if stype == "funnel":
        return {"type": "funnel", "x": "阶段", "series": ["实体数"]}
    if stype == "whatif":
        return {"type": "whatif_table", "x": spec["dimensions"][0] if spec["dimensions"] else ""}
    if stype == "impact":
        return {"type": "impact_table"}
    if stype == "distribution":
        return {"type": "pie", "x": spec["dimensions"][0] if spec["dimensions"] else "", "series": aliases[:1]}
    if stype == "topn":
        return {"type": "bar_horizontal", "x": spec["dimensions"][0] if spec["dimensions"] else "", "series": aliases[:1]}
    if stype == "detail":
        return {"type": "table"}
    return {"type": "kpi", "series": aliases}
