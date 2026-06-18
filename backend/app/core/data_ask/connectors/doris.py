"""Apache Doris connector (MySQL wire protocol, default port 9030)."""
from __future__ import annotations

import asyncio

from app.core.data_ask.connectors.base import QueryResult, RelationInfo
from app.core.data_ask.connectors.mysql import MySqlConnector


class DorisConnector(MySqlConnector):
    driver = "doris"

    async def list_relations(self) -> list[RelationInfo]:
        def _run() -> list[RelationInfo]:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    try:
                        cur.execute(
                            """
                            SELECT table_name, table_type FROM information_schema.tables
                            WHERE table_schema = %s
                            ORDER BY table_name
                            """,
                            (self.database,),
                        )
                        rows = cur.fetchall()
                        if rows:
                            out: list[RelationInfo] = []
                            for row in rows:
                                ttype = str(row.get("table_type") or row.get("TABLE_TYPE") or "BASE TABLE")
                                kind = "view" if "VIEW" in ttype.upper() else "table"
                                name = row.get("table_name") or row.get("TABLE_NAME")
                                if name:
                                    out.append(RelationInfo(name=name, object_type=kind))
                            return out
                    except Exception:
                        pass
                    cur.execute("SHOW TABLES")
                    rows = cur.fetchall()
                    if not rows:
                        return []
                    key = list(rows[0].keys())[0]
                    return [RelationInfo(name=r[key], object_type="table") for r in rows]
            finally:
                conn.close()

        return await asyncio.to_thread(_run)

    async def list_tables(self) -> list[str]:
        rels = await self.list_relations()
        return [r.name for r in rels if r.object_type == "table"]

    async def execute_select(self, sql: str, *, limit: int = 5000, timeout_s: int = 30) -> QueryResult:
        def _run() -> QueryResult:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    wrapped = f"SELECT * FROM ({sql.rstrip(';')}) AS _data_ask_q LIMIT {limit + 1}"
                    cur.execute(wrapped)
                    rows_raw = cur.fetchall()
                    if not rows_raw:
                        return QueryResult(columns=[], rows=[], row_count=0)
                    keys = list(rows_raw[0].keys())
                    truncated = len(rows_raw) > limit
                    rows = [[r[k] for k in keys] for r in rows_raw[:limit]]
                    return QueryResult(columns=keys, rows=rows, row_count=len(rows), truncated=truncated)
            finally:
                conn.close()

        return await asyncio.to_thread(_run)
