"""Schema introspection and relationship graph."""
from __future__ import annotations

import re
from typing import Any

from app.core.data_ask.connectors.factory import build_connector_from_source
from app.core.data_ask.utils.json_safe import json_safe_value

_KEY_COLUMN = re.compile(
    r"(?:^id$|_id$|id$|_bh$|bh$|_dm$|dm$|_code$|code$|_no$|no$|_key$|key$)$",
    re.IGNORECASE,
)
_SKIP_COLUMNS = {
    "name",
    "status",
    "type",
    "remark",
    "comment",
    "desc",
    "description",
    "txmc",
    "title",
    "note",
}
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_key_column(name: str) -> bool:
    text = (name or "").strip()
    if len(text) < 3 or text.lower() in _SKIP_COLUMNS:
        return False
    return bool(_KEY_COLUMN.search(text))


def _column_names(table: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for column in table.get("columns") or []:
        if isinstance(column, dict):
            name = str(column.get("name") or "")
        else:
            name = str(column)
        if name:
            names.append(name)
    return names


async def introspect_tables(source, table_names: list[str]) -> list[dict[str, Any]]:
    driver = str(getattr(source, "driver", "") or "")
    if driver in ("excel_folder", "excel_template"):
        from app.core.data_ask.excel.introspect import introspect_excel_files

        return await introspect_excel_files(str(source.id), table_names)

    conn = build_connector_from_source(source)
    try:
        out: list[dict[str, Any]] = []
        for name in table_names:
            meta = await conn.describe_table(name)
            samples = [json_safe_value(r) for r in await conn.sample_rows(name, limit=20)]
            out.append(
                {
                    "table_name": meta.name,
                    "schema": meta.schema,
                    "columns": [
                        {
                            "name": c.name,
                            "type": c.data_type,
                            "nullable": c.nullable,
                            "comment": c.comment or "",
                        }
                        for c in meta.columns
                    ],
                    "partition_columns": meta.partition_columns,
                    "sample_rows": samples,
                }
            )
        return out
    finally:
        await conn.close()


def infer_join_graph(tables: list[dict[str, Any]]) -> dict[str, Any]:
    """Edges between selected tables that share a key-like column."""
    nodes = [{"id": t["table_name"], "label": t["table_name"]} for t in tables]
    edges: list[dict[str, str]] = []
    col_map: dict[str, dict[str, str]] = {}
    for table in tables:
        named: dict[str, str] = {}
        for name in _column_names(table):
            if is_key_column(name):
                named[name.lower()] = name
        col_map[table["table_name"]] = named
    names = list(col_map.keys())
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            shared = sorted(set(col_map[left]) & set(col_map[right]))
            for key in shared[:3]:
                column = col_map[left][key]
                edges.append(
                    {
                        "from": left,
                        "to": right,
                        "label": column,
                        "from_column": column,
                        "to_column": col_map[right][key],
                        "kind": "inferred",
                    }
                )
    return {"nodes": nodes, "edges": edges}


async def catalog_related_tables(source, tables: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Other tables in the same database that share a key column with the selection."""
    driver = str(getattr(source, "driver", "") or "")
    if driver in ("excel_folder", "excel_template"):
        return []
    owners: dict[str, list[str]] = {}
    for table in tables:
        for name in _column_names(table):
            if is_key_column(name) and _SAFE_IDENT.match(name):
                owners.setdefault(name.lower(), []).append(table["table_name"])
    if not owners:
        return []
    selected = {str(table.get("table_name") or "") for table in tables}
    columns = []
    seen: set[str] = set()
    for table in tables:
        for name in _column_names(table):
            if name.lower() in owners and name.lower() not in seen:
                seen.add(name.lower())
                columns.append(name)
    conn = build_connector_from_source(source)
    try:
        found = await conn.find_shared_keys(columns[:12], sorted(selected))
    except Exception:
        return []
    finally:
        await conn.close()
    related: list[dict[str, str]] = []
    used: set[tuple[str, str, str]] = set()
    for row in found:
        other = str(row.get("table") or "")
        column = str(row.get("column") or "")
        if not other or other in selected or not _SAFE_IDENT.match(other):
            continue
        for origin in owners.get(column.lower(), []):
            mark = (origin, other, column.lower())
            if mark in used:
                continue
            used.add(mark)
            related.append(
                {
                    "from": origin,
                    "to": other,
                    "label": column,
                    "from_column": column,
                    "to_column": column,
                    "kind": "catalog",
                }
            )
            if len(related) >= 24:
                return related
    return related
