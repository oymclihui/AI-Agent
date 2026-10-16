"""MySQL connector (read-only, sync driver in thread pool)."""
from __future__ import annotations

import asyncio
from typing import Any

from app.core.data_ask.connectors.base import ColumnMeta, DataConnector, QueryResult, RelationInfo, TableMeta


class MySqlConnector(DataConnector):
    driver = "mysql"

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
        self.schema = schema or database

    def _connect(self):
        try:
            import pymysql
        except ImportError as exc:
            raise RuntimeError("MySQL support requires pymysql: pip install pymysql") from exc
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=15,
            read_timeout=30,
        )

    async def test(self) -> tuple[bool, str]:
        try:
            await asyncio.to_thread(self._ping)
            return True, "Connection OK"
        except Exception as exc:
            return False, str(exc)[:500]

    def _ping(self) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
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
                with conn.cursor() as cur:
                    clauses = [
                        "table_schema = %s",
                        "table_type IN ('BASE TABLE', 'VIEW')",
                    ]
                    params: list[Any] = [self.database]
                    if object_type == "table":
                        clauses.append("table_type = 'BASE TABLE'")
                    elif object_type == "view":
                        clauses.append("table_type = 'VIEW'")
                    if search.strip():
                        clauses.append("table_name LIKE %s")
                        params.append(f"%{search.strip()}%")
                    lim = 200 if search.strip() else limit
                    sql = (
                        "SELECT table_name, table_type FROM information_schema.tables "
                        f"WHERE {' AND '.join(clauses)} ORDER BY table_type, table_name LIMIT {int(lim)}"
                    )
                    cur.execute(sql, params)
                    out: list[RelationInfo] = []
                    for row in cur.fetchall():
                        kind = "view" if str(row["table_type"]).upper() == "VIEW" else "table"
                        out.append(RelationInfo(name=row["table_name"], object_type=kind))
                    return out
            finally:
                conn.close()

        return await asyncio.to_thread(_run)

    async def describe_table(self, table_name: str) -> TableMeta:
        def _run() -> TableMeta:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT column_name, data_type, is_nullable, column_comment
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        ORDER BY ordinal_position
                        """,
                        (self.database, table_name),
                    )
                    cols = [
                        ColumnMeta(
                            name=r["column_name"],
                            data_type=r["data_type"],
                            nullable=(r["is_nullable"] == "YES"),
                            comment=r.get("column_comment") or "",
                        )
                        for r in cur.fetchall()
                    ]
                return TableMeta(name=table_name, schema=self.database, columns=cols)
            finally:
                conn.close()

        return await asyncio.to_thread(_run)

    async def find_shared_keys(
        self,
        columns: list[str],
        exclude_tables: list[str],
    ) -> list[dict[str, str]]:
        safe_cols = [c for c in columns if c]
        if not safe_cols:
            return []

        def _run() -> list[dict[str, str]]:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    marks = ", ".join(["%s"] * len(safe_cols))
                    params: list[Any] = [self.database, *safe_cols]
                    exclude_sql = ""
                    if exclude_tables:
                        exclude_sql = " AND table_name NOT IN (" + ", ".join(["%s"] * len(exclude_tables)) + ")"
                        params.extend(exclude_tables)
                    cur.execute(
                        f"""
                        SELECT table_name, column_name
                        FROM information_schema.columns
                        WHERE table_schema = %s
                          AND column_name IN ({marks})
                          {exclude_sql}
                        LIMIT 80
                        """,
                        params,
                    )
                    out: list[dict[str, str]] = []
                    for row in cur.fetchall():
                        lowered = {str(k).lower(): v for k, v in row.items()}
                        out.append({"table": str(lowered.get("table_name") or ""), "column": str(lowered.get("column_name") or "")})
                    return out
            finally:
                conn.close()

        return await asyncio.to_thread(_run)

    async def sample_rows(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        def _run() -> list[dict[str, Any]]:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT * FROM `{table_name}` LIMIT %s", (limit,))
                    return list(cur.fetchall())
            finally:
                conn.close()

        return await asyncio.to_thread(_run)

    async def execute_select(self, sql: str, *, limit: int = 5000, timeout_s: int = 30) -> QueryResult:
        def _run() -> QueryResult:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(f"SET SESSION MAX_EXECUTION_TIME = {timeout_s * 1000}")
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
