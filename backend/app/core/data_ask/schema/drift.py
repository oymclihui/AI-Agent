"""Detect schema drift between remote DB and registered metadata."""
from __future__ import annotations

from typing import Any

from app.core.data_ask.connectors.factory import build_connector_from_source
from app.core.data_ask.schema.introspect import introspect_tables


from app.db.models import DataSourceTableRole


async def detect_schema_drift(source, tables: list[Any]) -> dict[str, Any]:
    data_tables = [
        t for t in tables
        if (t.role.value if hasattr(t.role, "value") else t.role) == DataSourceTableRole.data.value
    ]
    if not data_tables:
        return {"changed": False, "tables": []}

    names = [t.table_name for t in data_tables]
    remote = await introspect_tables(source, names)
    remote_by = {m["table_name"]: m for m in remote}
    drifted: list[dict[str, Any]] = []

    for t in data_tables:
        stored_cols = {
            str(c.get("name") if isinstance(c, dict) else c).lower()
            for c in ((t.column_meta or {}).get("columns") or [])
        }
        remote_meta = remote_by.get(t.table_name) or {}
        remote_cols = {
            str(c.get("name") if isinstance(c, dict) else c).lower()
            for c in (remote_meta.get("columns") or [])
        }
        added = sorted(remote_cols - stored_cols)
        removed = sorted(stored_cols - remote_cols)
        if added or removed:
            drifted.append(
                {
                    "table_name": t.table_name,
                    "added_columns": added,
                    "removed_columns": removed,
                }
            )

    return {"changed": bool(drifted), "tables": drifted}
