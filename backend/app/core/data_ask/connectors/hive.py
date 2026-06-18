"""Hive / Kylin-compatible connector via HiveServer2 (optional pyhive)."""
from __future__ import annotations

import asyncio
from typing import Any

from app.core.data_ask.connectors.base import ColumnMeta, DataConnector, QueryResult, TableMeta


class HiveConnector(DataConnector):
    driver = "hive"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        schema: str = "default",
        auth: str = "CUSTOM",
    ) -> None:
        self.host = host
        self.port = port or 10000
        self.user = user
        self.password = password
        self.database = database or schema or "default"
        self.auth = auth

    def _connect(self):
        try:
            from pyhive import hive
        except ImportError as exc:
            raise RuntimeError(
                "Hive support requires pyhive and thrift: pip install pyhive thrift sasl"
            ) from exc
        return hive.connect(
            host=self.host,
            port=self.port,
            username=self.user,
            password=self.password or None,
            database=self.database,
            auth=self.auth,
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
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
        finally:
            conn.close()

    async def list_tables(self) -> list[str]:
        def _run() -> list[str]:
            conn = self._connect()
            try:
                cur = conn.cursor()
                cur.execute(f"SHOW TABLES IN `{self.database}`")
                rows = cur.fetchall()
                cur.close()
                return [r[0] for r in rows]
            finally:
                conn.close()

        return await asyncio.to_thread(_run)

    async def describe_table(self, table_name: str) -> TableMeta:
        def _run() -> TableMeta:
            conn = self._connect()
            try:
                cur = conn.cursor()
                cur.execute(f"DESCRIBE `{self.database}`.`{table_name}`")
                rows = cur.fetchall()
                cur.close()
                cols: list[ColumnMeta] = []
                partition_cols: list[str] = []
                in_partition = False
                for row in rows:
                    if not row or not row[0]:
                        continue
                    name = str(row[0]).strip()
                    if name.startswith("#"):
                        in_partition = "Partition" in name
                        continue
                    dtype = str(row[1]).strip() if len(row) > 1 else "string"
                    col = ColumnMeta(name=name, data_type=dtype)
                    if in_partition:
                        partition_cols.append(name)
                    else:
                        cols.append(col)
                return TableMeta(
                    name=table_name,
                    schema=self.database,
                    columns=cols,
                    partition_columns=partition_cols,
                )
            finally:
                conn.close()

        return await asyncio.to_thread(_run)

    async def sample_rows(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        def _run() -> list[dict[str, Any]]:
            conn = self._connect()
            try:
                cur = conn.cursor()
                cur.execute(f"SELECT * FROM `{self.database}`.`{table_name}` LIMIT {limit}")
                cols = [d[0] for d in cur.description] if cur.description else []
                out = [dict(zip(cols, row)) for row in cur.fetchall()]
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
                wrapped = f"SELECT * FROM ({sql.rstrip(';')}) _data_ask_q LIMIT {limit + 1}"
                cur.execute(wrapped)
                cols = [d[0] for d in cur.description] if cur.description else []
                raw = cur.fetchall()
                cur.close()
                truncated = len(raw) > limit
                rows = [list(r) for r in raw[:limit]]
                return QueryResult(columns=cols, rows=rows, row_count=len(rows), truncated=truncated)
            finally:
                conn.close()

        return await asyncio.to_thread(_run)
