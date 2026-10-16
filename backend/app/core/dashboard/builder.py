"""看板取数层：连接器 + 治理链（守卫/列策略/行权限）+ 锚点校验。

与问数 service.py 同一套治理函数、同一套用参顺序，保证看板口径与问数一致。
任一 SQL 被治理链拒绝或执行失败即抛 DashboardBuildError（失败显式，不静默降级）。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.permissions import resolve_data_scope
from app.core.data_ask.connectors.factory import build_connector_from_source
from app.core.data_ask.govern.access import bypass_row_permission
from app.core.data_ask.govern.column_policy import validate_sql_columns
from app.core.data_ask.govern.permission import (
    build_permission_scope_sql,
    inject_permission_filter,
    permission_config_from_rules,
)
from app.core.data_ask.govern.sql_guard import validate_select_sql
from app.db.models import DataSource, DataSourceTable, DataSourceTableRole, User

from .template import ANCHOR_BASELINE, ANCHOR_TOLERANCE, REQUIRED_COLUMNS, build_metric_sqls

logger = logging.getLogger("dashboard.builder")


class DashboardBuildError(Exception):
    """取数/治理失败（消息面向用户，可安全展示）。"""


def _json_safe(v: Any) -> Any:
    """递归转 JSON 可序列化：Decimal→float，date/datetime→str，bytes→utf-8。"""
    import datetime
    import decimal

    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    return v


async def _registered_tables(db: AsyncSession, source_id: str) -> list[DataSourceTable]:
    res = await db.execute(
        select(DataSourceTable).where(DataSourceTable.data_source_id == str(source_id))
    )
    return list(res.scalars().all())


def pick_data_table(tables: list[DataSourceTable]) -> str:
    """schema_probe：从注册数据表中选出模板所需列最全的一张；缺列即显式失败。"""
    candidates: list[tuple[str, set[str]]] = []
    for t in tables:
        if t.role != DataSourceTableRole.data:
            continue
        meta = t.column_meta if isinstance(t.column_meta, dict) else {}
        cols = {str(c.get("name", "")).upper() for c in (meta.get("columns") or []) if isinstance(c, dict)}
        candidates.append((str(t.table_name), cols))
    for name, cols in candidates:
        if REQUIRED_COLUMNS.issubset(cols):
            return name
    missing_hint = {
        name: sorted(REQUIRED_COLUMNS - cols) for name, cols in candidates
    }
    raise DashboardBuildError(
        f"模板所需列在注册数据表中不满足（需要 {sorted(REQUIRED_COLUMNS)}），各表缺列：{missing_hint}"
    )


def _user_key(user: User | None) -> str:
    import re

    if not user:
        return "anonymous"
    key = str(user.employee_no or user.id)
    if not re.match(r"^[\w\-.@]+$", key):
        return str(user.id)
    return key


async def fetch_snapshot(db: AsyncSession, source: DataSource, user: User) -> dict[str, Any]:
    """执行 13 个聚合 SQL，返回数据快照（全部数值直查，零转录）。"""
    tables = await _registered_tables(db, str(source.id))
    table = pick_data_table(tables)
    sqls = build_metric_sqls(table)
    driver = str(source.driver)
    dialect = "mysql" if driver in ("mysql", "doris") else driver

    semantic = source.semantic_model if isinstance(source.semantic_model, dict) else {}
    scope = await resolve_data_scope(db, user)
    perm_rules = permission_config_from_rules(source.permission_rules)
    perm_table = next(
        (t for t in tables if t.role == DataSourceTableRole.permission), None
    )
    apply_perm = bool(perm_table) and not bypass_row_permission(user, scope)
    allowed = {str(t.table_name) for t in tables if t.role == DataSourceTableRole.data}
    is_admin = bool(user and user.is_admin)

    conn = build_connector_from_source(source)
    out: dict[str, Any] = {"_table": table, "_govern": {"row_permission": apply_perm}}
    try:
        for key, sql in sqls.items():
            ok, msg = validate_select_sql(sql, allowed_tables=allowed, dialect=dialect)
            if not ok:
                raise DashboardBuildError(f"SQL 守卫拒绝[{key}]：{msg}")
            col_ok, col_msg = validate_sql_columns(
                sql, semantic_model=semantic, user_is_admin=is_admin, scope=scope
            )
            if not col_ok:
                raise DashboardBuildError(f"列策略拒绝[{key}]：{col_msg}")
            exec_sql = sql
            if apply_perm and perm_table is not None:
                scope_sql = build_permission_scope_sql(
                    user_key=_user_key(user),
                    permission_table=str(perm_table.table_name),
                    scope_column=perm_rules["scope_column"],
                    user_column=perm_rules["user_column"],
                    dialect=dialect,
                )
                exec_sql = inject_permission_filter(
                    sql,
                    data_column=perm_rules["data_column"],
                    scope_subquery=scope_sql,
                    dialect=dialect,
                )
            try:
                qr = await conn.execute_select(exec_sql, limit=100000, timeout_s=120)
            except Exception as exc:
                raise DashboardBuildError(f"取数失败[{key}]：{str(exc)[:400]}") from exc
            rows = [list(r) for r in (qr.rows or [])]
            if key == "anchor":
                r0 = rows[0] if rows else [None] * 5
                out["anchor"] = {
                    "month_xsje": r0[0], "month_ml": r0[1], "recent3_xsje": r0[2],
                    "max_rq": str(r0[3])[:10] if r0[3] else None,
                    "min_rq": str(r0[4])[:10] if r0[4] else None,
                }
            else:
                out[key] = rows
            logger.info("dashboard fetch %s rows=%d", key, len(rows))
    finally:
        try:
            await conn.close()
        except Exception:
            pass
    if not out.get("kpi"):
        raise DashboardBuildError("KPI 聚合为空：数据表无数据或全部被权限过滤")
    return _json_safe(out)


def check_anchor(snapshot: dict[str, Any]) -> dict[str, Any]:
    """锚点比对：快照锚点 vs 蓝图基线，偏差 >0.1% 记 warn（显式披露，不拦截）。"""
    anchor = snapshot.get("anchor") or {}
    detail: dict[str, Any] = {"baseline_as_of": ANCHOR_BASELINE["as_of"], "items": []}
    worst = "pass"
    for key, label in (
        ("month_xsje", "当月销售额"),
        ("month_ml", "当月毛利"),
        ("recent3_xsje", "近3天销售额"),
    ):
        base = float(ANCHOR_BASELINE[key])
        raw = anchor.get(key)
        val = float(raw) if raw is not None else None
        if val is None:
            rel, status = None, "fail"
        else:
            rel = abs(val - base) / abs(base) if base else (0.0 if val == 0 else 1.0)
            status = "pass" if rel <= ANCHOR_TOLERANCE else "warn"
        if status != "pass":
            worst = status if status == "fail" or worst != "fail" else worst
            if status == "fail":
                worst = "fail"
        detail["items"].append({
            "key": key, "label": label, "value": val, "baseline": base,
            "deviation": (round(rel, 6) if rel is not None else None), "status": status,
        })
    if any(i["status"] == "fail" for i in detail["items"]):
        worst = "fail"
    elif any(i["status"] == "warn" for i in detail["items"]):
        worst = "warn"
    detail["status"] = worst
    return detail
