"""AnalysisSpec 执行器：规格 → 单条只读 SQL → 结果 + 事实 + 图表提示。

P6：外层 execute_spec 提供结果缓存（Redis，TTL 可配，行级权限签名入 key），
内层 _execute_spec_uncached 依次尝试 预聚合拦截 → impact 专用路径 → 标准编译路径。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.analysis.derived import DerivedError, derive, impact_result
from app.core.analysis.facts import build_facts
from app.core.analysis.preagg import try_preagg
from app.core.analysis.spec import (
    SpecError,
    build_sql,
    chart_hint,
    normalize_spec,
    query_timeout,
    spec_hash,
)
from app.core.cache.redis_cache import cache_get_json, cache_set_json
from app.core.data_ask.connectors.factory import build_connector_from_source
from app.core.data_ask.govern.column_policy import validate_sql_columns
from app.core.data_ask.govern.sql_guard import validate_select_sql
from app.db.models import DataSourceTable, DataSourceTableRole, RowPermission

ANALYSIS_CACHE_TTL = int(os.getenv("ANALYSIS_CACHE_TTL", "300"))


class AnalysisError(RuntimeError):
    """执行期错误（SQL 拒绝 / 数据源不可用 / 超时）。"""

    def __init__(self, message: str, code: str = "execution_failed"):
        super().__init__(message)
        self.code = code


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def _primary_table(db: AsyncSession, data_source_id: str) -> str:
    result = await db.execute(
        select(DataSourceTable.table_name)
        .where(
            DataSourceTable.data_source_id == data_source_id,
            DataSourceTable.role == DataSourceTableRole.data,
        )
        .order_by(DataSourceTable.created_at.asc())
        .limit(1)
    )
    table = result.scalar_one_or_none()
    if not table:
        raise AnalysisError("该数据源未配置可查询的数据表", "no_table")
    return str(table)


# 表达式中的 SQL 关键字（非列引用）
_SQL_KEYWORDS = {
    "SUM", "COUNT", "AVG", "MIN", "MAX", "NULLIF", "COALESCE", "DISTINCT", "AS",
    "CASE", "WHEN", "THEN", "ELSE", "END", "CAST", "DECIMAL", "INT", "INTEGER",
    "FLOAT", "DOUBLE", "VARCHAR", "DATE", "YEAR", "MONTH", "DAY", "IF", "IFNULL",
    "ROUND", "ABS", "NULL", "TRUE", "FALSE", "AND", "OR", "NOT", "IN", "IS",
}
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _expr_columns(expr: str) -> set[str] | None:
    """sqlglot 解析指标表达式取真实列名（标量子查询里的表名不算列）。

    解析失败返回 None，调用方回退正则（保持旧行为）。
    """
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(f"SELECT {expr} AS __m FROM __t", read="mysql")
        return {c.name for c in tree.find_all(exp.Column) if c.name}
    except Exception:
        return None


def _spec_required_columns(spec: dict[str, Any]) -> set[str]:
    """提取规格涉及的列名（维度 / 时间字段 / 过滤字段 / 指标表达式中的列）。"""
    need: set[str] = set()
    for d in spec.get("dimensions") or []:
        need.add(str(d))
    tr = spec.get("time_range") or None
    if tr and tr.get("field"):
        need.add(str(tr["field"]))
    for f in spec.get("filters") or []:
        if f.get("field"):
            need.add(str(f["field"]))
    for m in spec.get("metrics") or []:
        expr = str(m.get("expr") or "")
        cols = _expr_columns(expr)
        if cols is None:
            cols = {tok for tok in _IDENT_RE.findall(expr) if tok.upper() not in _SQL_KEYWORDS}
        need |= cols
    for o in spec.get("order_by") or []:
        if o.get("field") and IDENT.match(str(o["field"])):
            need.add(str(o["field"]))
    return {n for n in need if n}


def _table_column_names(t: DataSourceTable) -> set[str]:
    cm = t.column_meta or {}
    cols = cm.get("columns") if isinstance(cm, dict) else cm
    names: set[str] = set()
    if isinstance(cols, list):
        for c in cols:
            nm = c.get("name") if isinstance(c, dict) else str(c)
            if nm:
                names.add(str(nm))
    return names


def _norm_expr(expr: Any) -> str:
    return re.sub(r"\s+", "", str(expr or "")).upper()


def _metric_table_hint(semantic_model: Any, spec: dict[str, Any]) -> str | None:
    """语义模型中指标声明的表（如门店维表指标 vs 商品明细表指标）。

    规格内全部指标声明同一张表时返回该表名；否则返回 None 交由列覆盖路由决定。
    """
    sm = semantic_model or {}
    metrics = sm.get("metrics") if isinstance(sm, dict) else None
    if not metrics:
        return None
    by_name: dict[str, dict[str, Any]] = {}
    by_expr: dict[str, dict[str, Any]] = {}
    for m in metrics:
        if not isinstance(m, dict) or not m.get("table"):
            continue
        by_name[str(m.get("name") or "")] = m
        by_expr[_norm_expr(m.get("expr"))] = m
    tables: set[str] = set()
    for m in spec.get("metrics") or []:
        hit = by_name.get(str(m.get("name") or "")) or by_expr.get(_norm_expr(m.get("expr")))
        if hit:
            tables.add(str(hit["table"]))
    return tables.pop() if len(tables) == 1 else None


async def _resolve_table(
    db: AsyncSession,
    data_source_id: str,
    spec: dict[str, Any],
    default_table: str,
    semantic_model: Any = None,
) -> str:
    """按规格所需列选择数据表：优先选覆盖全部列的第一张表（多业务表数据源的必要路由）。

    语义模型为指标声明了表时优先该表（如门店数取自门店维表，而非商品明细表）。
    没有任何表能覆盖全部所需列时回退默认主表——由 SQL 执行期如实报错，
    不做跨表拼接（无 join 定义时拼接会引入未经确认的口径）。
    """
    need = _spec_required_columns(spec)
    hint = _metric_table_hint(semantic_model, spec)
    tables = (
        await db.execute(
            select(DataSourceTable)
            .where(
                DataSourceTable.data_source_id == data_source_id,
                DataSourceTable.role == DataSourceTableRole.data,
            )
            .order_by(DataSourceTable.created_at.asc())
        )
    ).scalars().all()
    ordered = sorted(tables, key=lambda t: 0 if hint and str(t.table_name) == hint else 1)
    for t in ordered:
        cols = _table_column_names(t)
        if cols and (not need or need <= cols):
            return str(t.table_name)
    # 无单表能覆盖：区分「字段不存在」与「跨表混算」，给出可读原因
    if need:
        owners: dict[str, list[str]] = {}
        for t in tables:
            cols = _table_column_names(t)
            for c in need & cols:
                owners.setdefault(c, []).append(str(t.table_name))
        unresolved = sorted(c for c in need if c not in owners)
        if unresolved:
            raise AnalysisError(
                f"字段不存在于该数据源任何表: {', '.join(unresolved[:8])}", "column_unknown")
        parts = sorted({ts[0] for ts in owners.values() if ts})
        if len(parts) > 1:
            raise AnalysisError(
                f"该规格涉及多张业务表（{', '.join(parts)}），不可在同一分析中混算", "cross_table")
    return default_table


async def apply_row_permissions(
    db: AsyncSession, data_source_id: str, spec: dict[str, Any], user: Any
) -> dict[str, Any]:
    """行级权限注入（SQL 出口统一护栏）：把该用户在此数据源上的
    维度白名单合并进 spec.filters。管理员不受限；空 allowed_values = 不可见任何行。"""
    if user is None or bool(getattr(user, "is_admin", False)):
        return spec
    perms = (
        await db.execute(
            select(RowPermission).where(
                RowPermission.data_source_id == str(data_source_id),
                RowPermission.user_id == str(getattr(user, "id", "")),
                RowPermission.active.is_(True),
            )
        )
    ).scalars().all()
    if not perms:
        return spec
    extra: dict[str, list[Any]] = {}
    for p in perms:
        vals = list(p.allowed_values or [])
        extra.setdefault(str(p.dimension_field), []).extend(vals)
    merged = [dict(f) for f in spec.get("filters") or []]
    for field, values in extra.items():
        # 同字段多条权限取并集；与用户自带筛选取交集（in 后再 eq 由 SQL AND 语义天然保证）
        uniq = list(dict.fromkeys(values))
        merged.append({"field": field, "op": "in", "value": uniq})
    spec = dict(spec)
    spec["filters"] = merged
    return spec


async def _run_base_query(
    db: AsyncSession, source: DataSource, spec: dict[str, Any], user: Any, table: str
) -> tuple[list[str], list[list[Any]], str]:
    """执行一条基础查询（build_sql → 双重校验 → 连接器），返回 (columns, rows, sql)。"""
    driver = str(getattr(source, "driver", "") or "")
    sql = build_sql(spec, table, driver)
    ok, msg = validate_select_sql(sql, allowed_tables={table}, dialect=driver)
    if not ok:
        raise AnalysisError(msg, "sql_rejected")
    ok, msg = validate_sql_columns(
        sql,
        semantic_model=getattr(source, "semantic_model", None) or {},
        user_is_admin=bool(getattr(user, "is_admin", False)),
        scope=None,
    )
    if not ok:
        raise AnalysisError(msg, "column_denied")
    connector = build_connector_from_source(source)
    try:
        qr = await connector.execute_select(sql, limit=spec["limit"], timeout_s=query_timeout())
    except Exception as exc:  # 连接器内部异常统一转换为可读错误
        raise AnalysisError(f"查询执行失败: {exc}", "execution_failed") from exc
    finally:
        await connector.close()
    columns = [str(c) for c in qr.columns]
    rows = [list(r) for r in qr.rows]
    rows.sort(key=lambda r: str(r[0]))  # 远端不保证 ORDER BY 语义，按期间确定性排序
    return columns, rows, sql


async def _execute_impact(
    db: AsyncSession, source: DataSource, spec: dict[str, Any], user: Any, table: str
) -> dict[str, Any]:
    """A4 因果推断（双重差分）：处理组/对照组两条按日序列，Python 确定性计算净效应。"""
    treat_opt = spec["options"]["treatment"]
    field, value = str(treat_opt["field"]), treat_opt["value"]
    subs: dict[str, dict[str, Any]] = {}
    for key, op in (("treat", "eq"), ("ctrl", "ne")):
        subs[key] = {
            **spec,
            "type": "timeseries",
            "base": "timeseries",  # impact 规格的 base 不是 timeseries，必须显式覆盖
            "time_range": {**spec["time_range"], "granularity": "day"},
            "filters": [dict(f) for f in spec.get("filters") or []] + [{"field": field, "op": op, "value": value}],
        }
    started = time.perf_counter()
    t_cols, t_rows, t_sql = await _run_base_query(db, source, subs["treat"], user, table)
    c_cols, c_rows, c_sql = await _run_base_query(db, source, subs["ctrl"], user, table)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    try:
        result = impact_result(spec, t_rows, c_rows)
    except DerivedError as exc:
        raise AnalysisError(str(exc), getattr(exc, "code", "derived_failed")) from exc
    return {
        "run_id": str(uuid.uuid4()),
        "spec_hash": spec_hash(spec),
        "spec": spec,
        "columns": result["columns"],
        "rows": result["rows"],
        "row_count": len(result["rows"]),
        "facts": result["facts"],
        "chart": result["chart"],
        "query": {
            "sql": t_sql,
            "sql_control": c_sql,
            "elapsed_ms": elapsed_ms,
            "truncated": False,
        },
        "error": None,
    }


async def _perm_signature(db: AsyncSession, data_source_id: str, user: Any) -> str:
    """行级权限签名：同签名用户共享缓存；管理员/匿名 = open。"""
    if user is None or bool(getattr(user, "is_admin", False)):
        return "open"
    perms = (
        await db.execute(
            select(RowPermission).where(
                RowPermission.data_source_id == str(data_source_id),
                RowPermission.user_id == str(getattr(user, "id", "")),
                RowPermission.active.is_(True),
            )
        )
    ).scalars().all()
    if not perms:
        return "open"  # 无任何权限行 = 无注入过滤，与 open 口径一致，可共享缓存
    raw = json.dumps(
        sorted([str(p.dimension_field), sorted(str(v) for v in (p.allowed_values or []))] for p in perms),
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


async def execute_spec(
    db: AsyncSession,
    source: Any,
    spec_raw: dict[str, Any],
    *,
    user: Any = None,
) -> dict[str, Any]:
    """带结果缓存的执行入口：命中缓存直接返回（facts 注明来源），否则实算并写缓存。"""
    try:
        spec = normalize_spec(spec_raw)
    except SpecError:
        raise
    key = ""
    if ANALYSIS_CACHE_TTL > 0:
        sig = await _perm_signature(db, source.id, user)
        key = "analysis:cache:" + hashlib.sha256(
            f"{spec_hash(spec)}|{source.id}|{sig}".encode("utf-8")
        ).hexdigest()
        cached = await cache_get_json(key)
        if isinstance(cached, dict) and cached.get("columns") is not None:
            age = max(0, int(time.time() - float(cached.get("_ts") or time.time())))
            facts = [dict(f) for f in cached.get("facts") or []]
            facts.insert(0, {
                "text": f"结果来自查询缓存（{age} 秒前生成，TTL {ANALYSIS_CACHE_TTL} 秒），与同口径直查一致",
                "from": "cache",
            })
            q = dict(cached.get("query") or {})
            q["cache"] = {"hit": True, "key": key[-12:], "age_s": age, "ttl": ANALYSIS_CACHE_TTL}
            return {
                "run_id": str(uuid.uuid4()),
                "spec_hash": spec_hash(spec),
                "spec": cached.get("spec") or spec,
                "columns": cached["columns"],
                "rows": cached["rows"],
                "row_count": len(cached["rows"]),
                "facts": facts,
                "chart": cached.get("chart"),
                "query": q,
                "error": None,
            }
    result = await _execute_spec_uncached(db, source, spec_raw, user=user)
    if key and result.get("error") is None and result.get("columns") is not None:
        payload = {
            "spec": result.get("spec"),
            "columns": result["columns"],
            "rows": result["rows"],
            "facts": result.get("facts"),
            "chart": result.get("chart"),
            "query": {k: v for k, v in (result.get("query") or {}).items() if k != "cache"},
            "_ts": time.time(),
        }
        await cache_set_json(key, payload, ttl=ANALYSIS_CACHE_TTL)
    q = result.get("query")
    if isinstance(q, dict):
        q["cache"] = {"hit": False, "key": key[-12:] if key else "", "age_s": None, "ttl": ANALYSIS_CACHE_TTL}
    return result


async def _execute_spec_uncached(
    db: AsyncSession,
    source: Any,
    spec_raw: dict[str, Any],
    *,
    user: Any = None,
) -> dict[str, Any]:
    """执行一条分析规格；所有数值均由数据库返回，不做二次加工。"""
    try:
        spec = normalize_spec(spec_raw)
    except SpecError:
        raise
    spec = await apply_row_permissions(db, source.id, spec, user)

    table = await _primary_table(db, source.id)
    # 多业务表数据源：按语义模型声明 + 规格所需列路由到合适的表（如客流指标 → 客流表）
    table = await _resolve_table(db, source.id, spec, table, getattr(source, "semantic_model", None))
    if spec["type"] == "impact":
        return await _execute_impact(db, source, spec, user, table)
    pre = await try_preagg(db, source, spec)
    if pre is not None:
        return pre
    driver = str(getattr(source, "driver", "") or "")
    sql = build_sql(spec, table, driver)

    ok, msg = validate_select_sql(sql, allowed_tables={table}, dialect=driver)
    if not ok:
        raise AnalysisError(msg, "sql_rejected")
    ok, msg = validate_sql_columns(
        sql,
        semantic_model=getattr(source, "semantic_model", None) or {},
        user_is_admin=bool(getattr(user, "is_admin", False)),
        scope=None,
    )
    if not ok:
        raise AnalysisError(msg, "column_denied")

    connector = build_connector_from_source(source)
    started = time.perf_counter()
    try:
        qr = await connector.execute_select(sql, limit=spec["limit"], timeout_s=query_timeout())
    except Exception as exc:  # 连接器内部异常统一转换为可读错误
        raise AnalysisError(f"查询执行失败: {exc}", "execution_failed") from exc
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        await connector.close()

    columns = [str(c) for c in qr.columns]
    rows = [list(r) for r in qr.rows]
    # 远端引擎不保证 ORDER BY 语义：对基础结果集做确定性排序
    if spec["type"] == "timeseries":
        rows.sort(key=lambda r: str(r[0]))
    elif spec["type"] in ("distribution", "topn"):
        mi = len(spec["dimensions"])
        if mi < len(columns):
            rows.sort(key=lambda r: _to_float(r[mi]) or 0.0, reverse=True)
    chart = chart_hint(spec)
    try:
        result = derive(spec, columns, rows)
    except DerivedError as exc:
        raise AnalysisError(str(exc), getattr(exc, "code", "derived_failed")) from exc
    if result is not None:
        columns = result["columns"]
        rows = result["rows"]
        facts = result["facts"]
        chart = result["chart"]
    else:
        facts = build_facts(spec, columns, rows)

    return {
        "run_id": str(uuid.uuid4()),
        "spec_hash": spec_hash(spec),
        "spec": spec,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "facts": facts,
        "chart": chart,
        "query": {"sql": sql, "elapsed_ms": elapsed_ms, "truncated": bool(getattr(qr, "truncated", False))},
        "error": None,
    }
