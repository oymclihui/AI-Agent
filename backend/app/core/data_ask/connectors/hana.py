"""SAP HANA connector (read-only, sync hdbcli in thread pool)."""
from __future__ import annotations

import asyncio
from typing import Any

from app.core.data_ask.connectors.base import ColumnMeta, DataConnector, QueryResult, RelationInfo, TableMeta


class HanaConnector(DataConnector):
    driver = "hana"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        schema: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.schema = (schema or user or database).upper()

    def _connect(self):
        try:
            from hdbcli import dbapi
        except ImportError as exc:
            raise RuntimeError(
                "SAP HANA support requires hdbcli: pip install hdbcli"
            ) from exc
        kwargs: dict[str, Any] = {
            "address": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "connectTimeout": 15000,
        }
        if self.database:
            kwargs["databaseName"] = self.database
        if self.schema:
            kwargs["currentSchema"] = self.schema
        return dbapi.connect(**kwargs)

    async def test(self) -> tuple[bool, str]:
        try:
            await asyncio.to_thread(self._ping)
            return True, "Connection OK"
        except Exception as exc:
            return False, str(exc)[:500]

    def _ping(self) -> None:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM DUMMY")
            cur.close()
        finally:
            conn.close()

    async def list_tables(self) -> list[str]:
        rels = await self.list_relations()
        return [r.name for r in rels if r.object_type == "table"]

    async def list_relations(
        self,
        *,
        search: str = "",
        object_type: str | None = None,
        limit: int = 120,
    ) -> list[RelationInfo]:
        def _run() -> list[RelationInfo]:
            conn = self._connect()
            try:
                cur = conn.cursor()
                schema_esc = self.schema.replace("'", "''")
                clauses = [f"SCHEMA_NAME = '{schema_esc}'"]
                if object_type == "table":
                    clauses.append("OBJECT_TYPE = 'TABLE'")
                elif object_type == "view":
                    clauses.append("OBJECT_TYPE = 'VIEW'")
                else:
                    clauses.append("OBJECT_TYPE IN ('TABLE', 'VIEW')")
                if search.strip():
                    esc = search.strip().replace("'", "''")
                    clauses.append(f"OBJECT_NAME LIKE '%{esc}%'")
                lim = 200 if search.strip() else limit
                sql = (
                    "SELECT OBJECT_NAME, OBJECT_TYPE FROM SYS.OBJECTS "
                    f"WHERE {' AND '.join(clauses)} ORDER BY OBJECT_TYPE, OBJECT_NAME LIMIT {int(lim)}"
                )
                cur.execute(sql)
                rows = cur.fetchall()
                cur.close()
                out: list[RelationInfo] = []
                for row in rows:
                    if isinstance(row, dict):
                        name = row.get("OBJECT_NAME") or row.get("TABLE_NAME")
                        otype = row.get("OBJECT_TYPE")
                    else:
                        name, otype = row[0], row[1]
                    if not name:
                        continue
                    kind = "view" if "VIEW" in str(otype).upper() else "table"
                    out.append(RelationInfo(name=str(name), object_type=kind))
                return out
            finally:
                conn.close()

        return await asyncio.to_thread(_run)

    async def describe_table(self, table_name: str) -> TableMeta:
        def _run() -> TableMeta:
            conn = self._connect()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT COLUMN_NAME, DATA_TYPE_NAME, IS_NULLABLE, COMMENTS
                    FROM SYS.TABLE_COLUMNS
                    WHERE SCHEMA_NAME = ? AND TABLE_NAME = ?
                    ORDER BY POSITION
                    """,
                    (self.schema, table_name),
                )
                rows = cur.fetchall()
                cur.close()
                cols: list[ColumnMeta] = []
                for row in rows:
                    if isinstance(row, dict):
                        cols.append(
                            ColumnMeta(
                                name=str(row["COLUMN_NAME"]),
                                data_type=str(row["DATA_TYPE_NAME"]),
                                nullable=str(row.get("IS_NULLABLE") or "").upper() in ("TRUE", "YES", "1"),
                                comment=str(row.get("COMMENTS") or ""),
                            )
                        )
                    else:
                        cols.append(
                            ColumnMeta(
                                name=str(row[0]),
                                data_type=str(row[1]),
                                nullable=str(row[2] or "").upper() in ("TRUE", "YES", "1"),
                                comment=str(row[3] or "") if len(row) > 3 else "",
                            )
                        )
                return TableMeta(name=table_name, schema=self.schema, columns=cols)
            finally:
                conn.close()

        return await asyncio.to_thread(_run)

    async def sample_rows(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        def _run() -> list[dict[str, Any]]:
            conn = self._connect()
            try:
                cur = conn.cursor()
                ident = f'"{self.schema}"."{table_name}"'
                cur.execute(f"SELECT * FROM {ident} LIMIT ?", (limit,))
                cols = [d[0] for d in (cur.description or [])]
                out = []
                for row in cur.fetchall():
                    if isinstance(row, dict):
                        out.append(row)
                    else:
                        out.append(dict(zip(cols, row)))
                cur.close()
                return out
            finally:
                conn.close()

        return await asyncio.to_thread(_run)

    async def execute_select(self, sql: str, *, limit: int = 5000, timeout_s: int = 30) -> QueryResult:
        def _run() -> QueryResult:
            conn = self._connect()
            try:
                cur = conn.cursor()
                wrapped = f"SELECT * FROM ({sql.rstrip(';')}) AS _data_ask_q LIMIT {limit + 1}"
                cur.execute(wrapped)
                cols = [d[0] for d in (cur.description or [])]
                raw = cur.fetchall()
                cur.close()
                if not raw:
                    return QueryResult(columns=[], rows=[], row_count=0)
                truncated = len(raw) > limit
                rows: list[list[Any]] = []
                for row in raw[:limit]:
                    if isinstance(row, dict):
                        rows.append([row.get(c) for c in cols])
                    else:
                        rows.append(list(row))
                return QueryResult(columns=cols, rows=rows, row_count=len(rows), truncated=truncated)
            finally:
                conn.close()

        return await asyncio.to_thread(_run)
