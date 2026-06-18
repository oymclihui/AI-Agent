"""Row-level permission injection via permission table."""
from __future__ import annotations

from typing import Any


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
    return f"SELECT {sc} FROM {pt} WHERE {uc} = '{safe_user}'"


def inject_permission_filter(
    sql: str,
    *,
    data_column: str,
    scope_subquery: str,
    dialect: str = "postgresql",
) -> str:
    """Wrap SQL and filter by scope subquery."""
    dc = _quote_ident(data_column, dialect)
    inner = sql.rstrip(";").strip()
    return (
        f"SELECT * FROM ({inner}) AS _perm_base "
        f"WHERE {dc} IN ({scope_subquery})"
    )


def permission_config_from_rules(rules: dict[str, Any] | None) -> dict[str, str]:
    rules = rules or {}
    return {
        "user_column": str(rules.get("user_column") or "user_id"),
        "scope_column": str(rules.get("scope_column") or "country_code"),
        "data_column": str(rules.get("data_column") or "country_code"),
    }


def _quote_ident(name: str, dialect: str) -> str:
    if dialect in ("mysql", "doris"):
        return f"`{name}`"
    if dialect == "hive":
        return f"`{name}`"
    if dialect == "hana":
        return f'"{name}"'
    return f'"{name}"'
