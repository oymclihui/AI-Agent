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
    """读取行级权限列配置。

    不做 country_code/user_id 之类的默认值兜底：历史上这些默认值被直接拼进
    SQL，新数据源（真实列是 RYID/FDBH 等）一问数就报「未知列」。
    未配置时留空，交给 resolve_permission_columns 按真实列自动推断；
    推断不出来就显式报错，绝不生成非法 SQL 或退化为不加过滤。
    """
    rules = rules or {}
    return {
        "user_column": str(rules.get("user_column") or "").strip(),
        "scope_column": str(rules.get("scope_column") or "").strip(),
        "data_column": str(rules.get("data_column") or "").strip(),
    }


_PERM_USER_CANDIDATES = ("RYID", "YGID", "EMPLOYEE_NO", "EMP_NO", "USER_ID", "USERID", "工号")
_PERM_SCOPE_CANDIDATES = ("FDBH", "FDMC", "ORG_ID", "ORGID", "STORE_ID", "门店编号", "门店")


async def read_table_columns(source: Any, table_name: str) -> set[str]:
    """读取一张表的列名集合（UPPER）。

    不能用 `SELECT * ... LIMIT 0`：多数驱动在零行时拿不到列描述（Doris/MySQL 实测
    返回空列名），会被误判成「读不到列」。这里改用 information_schema / DESC，
    最后才用 LIMIT 1 兜底。
    """
    table = str(table_name or "").strip()
    if not table:
        return set()
    driver = str(getattr(source, "driver", "") or "").lower()
    bare = table.split(".")[-1]
    from app.core.data_ask.connectors.factory import build_connector_from_source

    if driver in ("mysql", "doris", "starrocks", "hive"):
        probes: list[tuple[str, str]] = [
            (f"SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = '{bare}'", "first_col")
        ]
    else:
        probes = [
            (f"SELECT column_name FROM information_schema.columns WHERE table_name = '{bare}'", "first_col")
        ]
    probes.append((f"DESC {table}", "first_col"))
    probes.append((f"SELECT * FROM {table} LIMIT 1", "columns"))

    try:
        conn = build_connector_from_source(source)
    except Exception:
        return set()
    try:
        for sql, mode in probes:
            try:
                qr = await conn.execute_select(sql, limit=200)
            except Exception:
                continue
            names: set[str] = set()
            if mode == "first_col":
                for row in qr.rows or []:
                    cells = list(row or [])
                    if cells and cells[0]:
                        names.add(str(cells[0]).upper())
            else:
                for column in qr.columns or []:
                    raw = column.get("name") if isinstance(column, dict) else column
                    if raw:
                        names.add(str(raw).upper())
            if names:
                return names
    finally:
        try:
            await conn.close()
        except Exception:
            pass
    return set()


async def resolve_permission_columns(
    source: Any,
    permission_table: str,
    rules: dict[str, Any] | None,
    business_columns: set[str] | None,
) -> tuple[dict[str, str], str | None]:
    """校正并校验行级权限列，返回 (生效配置, 错误信息)。

    新数据源/新表接入时最常见的坑：
    1. permission_rules 为空或沿用旧默认列（country_code/user_id），但真实列是 RYID/FDBH；
    2. 数据列（data_column）在业务表里不存在。
    这里按权限表真实列自动纠正，并在无法唯一确定时显式报错（fail-closed）。
    """
    rules = rules or {}
    user_col = str(rules.get("user_column") or "").strip().upper()
    scope_col = str(rules.get("scope_column") or "").strip().upper()
    data_col = str(rules.get("data_column") or "").strip().upper()

    perm_cols = await read_table_columns(source, permission_table)
    if not perm_cols:
        return {}, f"无法读取权限表 {permission_table} 的列（请确认表名与连接权限）"

    biz_cols = {str(c or "").upper() for c in (business_columns or set()) if str(c or "").strip()}
    if not biz_cols:
        return {}, "无法读取业务表列，不能校验行级权限数据列"

    def _pick(current: str, candidates: tuple[str, ...], allowed: set[str]) -> str:
        if current and current in allowed:
            return current
        hits = [c for c in candidates if c in allowed]
        return hits[0] if len(hits) == 1 else ""

    user_col = _pick(user_col, _PERM_USER_CANDIDATES, perm_cols)
    scope_col = _pick(scope_col, _PERM_SCOPE_CANDIDATES, perm_cols)
    if not user_col or not scope_col:
        return {}, (
            f"权限表 {permission_table} 中无法唯一确定用户列/范围列"
            f"（配置 {rules.get('user_column') or '空'}/{rules.get('scope_column') or '空'}，"
            f"实际列 {sorted(perm_cols)}）"
        )

    if not data_col or data_col not in biz_cols:
        shared = sorted(c for c in (perm_cols & biz_cols) if c != user_col)
        if len(shared) == 1:
            data_col = shared[0]
        elif not shared:
            return {}, (
                f"权限表 {permission_table} 与业务表没有可用于过滤的公共列"
                f"（权限表列 {sorted(perm_cols)}）"
            )
        else:
            return {}, (
                f"数据列 {rules.get('data_column') or '未配置'} 不在业务表中，"
                f"且候选公共列 {shared} 不唯一，请在数据源设置中指定 data_column"
            )

    return {"user_column": user_col, "scope_column": scope_col, "data_column": data_col}, None


def _quote_ident(name: str, dialect: str) -> str:
    if dialect in ("mysql", "doris", "starrocks", "hive"):
        return f"`{name}`"
    if dialect == "hana":
        return f'"{name}"'
    return f'"{name}"'
