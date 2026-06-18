"""Schema introspection and relationship graph."""
from __future__ import annotations

from typing import Any

from app.core.data_ask.connectors.factory import build_connector_from_source
from app.core.data_ask.utils.json_safe import json_safe_value


async def introspect_tables(source, table_names: list[str]) -> list[dict[str, Any]]:
    driver = str(getattr(source, "driver", "") or "")
    if driver == "excel_folder":
        from app.core.data_ask.excel.introspect import introspect_excel_files

        return await introspect_excel_files(str(source.id), table_names)

    conn = build_connector_from_source(source)
    try:
        out: list[dict[str, Any]] = []
        for name in table_names:
            meta = await conn.describe_table(name)
            samples = [json_safe_value(r) for r in await conn.sample_rows(name, limit=3)]
            out.append(
                {
                    "table_name": meta.name,
                    "schema": meta.schema,
                    "columns": [
                        {"name": c.name, "type": c.data_type, "nullable": c.nullable}
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
    """Heuristic FK/join edges by matching column names."""
    nodes = [{"id": t["table_name"], "label": t["table_name"]} for t in tables]
    edges: list[dict[str, str]] = []
    col_map: dict[str, set[str]] = {}
    for t in tables:
        col_map[t["table_name"]] = {c["name"].lower() for c in t.get("columns") or []}
    names = list(col_map.keys())
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            shared = col_map[a] & col_map[b]
            join_keys = [c for c in shared if c.endswith("_id") or c in ("bu_code", "country_code", "dept_id")]
            for key in join_keys[:2]:
                edges.append({"from": a, "to": b, "label": key})
    return {"nodes": nodes, "edges": edges}
