"""Row-level permission injection via permission table."""
from __future__ import annotations

import re
from typing import Any

try:
    import sqlglot
    from sqlglot import exp

    _HAS_SQLGLOT = True
except ImportError:
    _HAS_SQLGLOT = False


def build_permission_scope_sql(
    *,
    user_key: str,
    permission_table: str,
    scope_column: str,
    user_column: str = "user_id",
    dialect: str = "postgresql",
) -> str:
    """Return subquery: scope values visible to user."""
    pt = _quote_ident(permission_table, dialect)
    uc = _quote_ident(user_column, dialect)
    sc = _quote_ident(scope_column, dialect)
    safe_user = user_key.replace("'", "''")
    return f"SELECT {pt}.{sc} FROM {pt} WHERE {pt}.{uc} = '{safe_user}'"


def inject_permission_filter(
    sql: str,
    *,
    data_column: str,
    scope_subquery: str,
    dialect: str = "postgresql",
) -> str:
    """Filter base-table scans before aggregation. Fall back to an outer wrap."""
    pushed = _pushdown_permission(sql, data_column, scope_subquery, dialect)
    if pushed:
        return pushed
    dc = _quote_ident(data_column, dialect)
    inner = sql.rstrip(";").strip()
    return (
        f"SELECT * FROM ({inner}) AS _perm_base "
        f"WHERE {dc} IN ({scope_subquery})"
    )


def _pushdown_permission(sql: str, data_column: str, scope_subquery: str, dialect: str) -> str | None:
    if not _HAS_SQLGLOT:
        return None
    from app.core.data_ask.govern.sql_guard import sqlglot_dialect

    read = sqlglot_dialect(dialect)
    try:
        tree = sqlglot.parse_one(sql, read=read)
        predicate = _permission_predicate(data_column, scope_subquery, dialect, read)
    except Exception:
        return None
    if predicate is None:
        return None
    cte_names = {str(cte.alias).lower() for cte in tree.find_all(exp.CTE) if cte.alias}
    scope_norm = _normalize_sql(scope_subquery)
    applied = False
    for select in list(tree.find_all(exp.Select)):
        if not _reads_physical_table(select, cte_names):
            continue
        # 跳过权限表子查询自身，避免在 scope 子查询里再套一层同样的过滤
        if _normalize_sql(select.sql()) == scope_norm:
            continue
        # 模型已按权限提示写过等价过滤条件时不再重复注入
        if _already_restricted(select, data_column, scope_subquery):
            applied = True
            continue
        # 给注入的 data_column 限定到该 SELECT 的主表（FROM 第一张表），避免多表 JOIN 下列歧义
        tables = _direct_tables(select)
        pred = predicate.copy()
        if tables:
            alias = tables[0].alias_or_name
            for col in pred.find_all(exp.Column):
                if not col.table and col.name and col.name.lower() == data_column.lower():
                    col.set("table", exp.to_identifier(alias))
        _and_where(select, pred)
        applied = True
    if not applied:
        return None
    rendered = tree.sql(dialect=read)
    if data_column.lower() not in rendered.lower():
        return None
    return rendered


def _already_restricted(select, data_column: str, scope_subquery: str) -> bool:
    """该 SELECT 作用域内是否已有等价的 data_column IN (scope_subquery) 条件。"""
    where = select.args.get("where")
    if where is None:
        return False
    target = _normalize_sql(scope_subquery)
    for node in where.find_all(exp.In):
        if _nearest_select(node) is not select:
            continue
        col = node.this
        if not isinstance(col, exp.Column) or (col.name or "").lower() != data_column.lower():
            continue
        query = node.args.get("query")
        if query is None:
            exprs = node.expressions or []
            query = exprs[0] if len(exprs) == 1 else None
        if query is None:
            continue
        if _normalize_sql(query.sql()) == target:
            return True
    return False


def _normalize_sql(text: str) -> str:
    cleaned = (text or "").replace("`", "").replace('"', "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower().rstrip(";")
    while cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _permission_predicate(data_column: str, scope_subquery: str, dialect: str, read: str):
    quoted = _quote_ident(data_column, dialect)
    parsed = sqlglot.parse_one(f"SELECT 1 WHERE {quoted} IN ({scope_subquery})", read=read)
    where = parsed.args.get("where")
    if where is None:
        return None
    return where.this


def _reads_physical_table(select, cte_names: set[str]) -> bool:
    for table in _direct_tables(select):
        if table.name and table.name.lower() not in cte_names:
            return True
    return False


def _direct_tables(select):
    nodes = []
    if select.args.get("from") is not None:
        nodes.append(select.args["from"])
    nodes.extend(select.args.get("joins") or [])
    tables = []
    for node in nodes:
        for table in node.find_all(exp.Table):
            if _nearest_select(table) is select:
                tables.append(table)
    return tables


def _nearest_select(node):
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.Select):
            return parent
        parent = parent.parent
    return None


def _and_where(select, predicate) -> None:
    current = select.args.get("where")
    if current is None:
        select.set("where", exp.Where(this=predicate))
        return
    select.set("where", exp.Where(this=exp.and_(current.this, predicate)))


def permission_config_from_rules(rules: dict[str, Any] | None) -> dict[str, str]:
    rules = rules or {}
    return {
        "user_column": str(rules.get("user_column") or "user_id"),
        "scope_column": str(rules.get("scope_column") or "country_code"),
        "data_column": str(rules.get("data_column") or "country_code"),
    }


def _quote_ident(name: str, dialect: str) -> str:
    if dialect in ("mysql", "doris", "starrocks", "hive"):
        return f"`{name}`"
    if dialect == "hana":
        return f'"{name}"'
    return f'"{name}"'
