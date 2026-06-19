"""PostgreSQL / VastBase connector (read-only)."""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.data_ask.connectors.base import ColumnMeta, DataConnector, QueryResult, RelationInfo, TableMeta
from app.core.database.provisioning import build_engine_kwargs, make_database_url


class PgConnector(DataConnector):
    def __init__(
        self,
        *,
        driver: str,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        schema: str = "public",
        ssl: str = "prefer",
    ) -> None:
        self.driver = driver
        self.schema = schema
        url = make_database_url(
            driver=driver,
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            ssl=ssl,
        )
        self._engine: AsyncEngine = create_async_engine(
            url,
            **build_engine_kwargs(driver, ssl, schema),
        )

    async def test(self) -> tuple[bool, str]:
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True, "Connection OK"
        except Exception as exc:
            return False, str(exc)[:500]

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
        pattern = f"%{search.strip()}%" if search.strip() else None
        type_filter = ""
        if object_type == "table":
            type_filter = "AND table_type = 'BASE TABLE'"
        elif object_type == "view":
            type_filter = "AND table_type = 'VIEW'"
        name_filter = "AND table_name ILIKE :pattern" if pattern else ""
        lim_sql = "LIMIT :lim" if (pattern or limit < 10000) else ""
        q = text(
            f"""
            SELECT table_name, table_type FROM information_schema.tables
            WHERE table_schema = :schema
              AND table_type IN ('BASE TABLE', 'VIEW')
              {type_filter}
              {name_filter}
            ORDER BY table_type, table_name
            {lim_sql}
            """
        )
        params: dict[str, Any] = {"schema": self.schema, "lim": limit if not pattern else 200}
        if pattern:
            params["pattern"] = pattern
        async with self._engine.connect() as conn:
            rows = (await conn.execute(q, params)).fetchall()
        out: list[RelationInfo] = []
        for name, ttype in rows:
            kind = "view" if str(ttype).upper() == "VIEW" else "table"
            out.append(RelationInfo(name=name, object_type=kind))
        return out

    async def describe_table(self, table_name: str) -> TableMeta:
        q = text(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :table
            ORDER BY ordinal_position
            """
        )
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(q, {"schema": self.schema, "table": table_name})
            ).fetchall()
        cols = [
            ColumnMeta(name=r[0], data_type=r[1], nullable=(r[2] == "YES"))
            for r in rows
        ]
        return TableMeta(name=table_name, schema=self.schema, columns=cols)

    async def sample_rows(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        safe = self._quote_table(table_name)
        q = text(f"SELECT * FROM {safe} LIMIT :lim")
        async with self._engine.connect() as conn:
            result = await conn.execute(q, {"lim": limit})
            keys = list(result.keys())
            return [dict(zip(keys, row)) for row in result.fetchall()]

    async def execute_select(self, sql: str, *, limit: int = 5000, timeout_s: int = 30) -> QueryResult:
        wrapped = f"SELECT * FROM ({sql.rstrip(';')}) AS _data_ask_q LIMIT :lim"
        async with self._engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL statement_timeout = '{timeout_s * 1000}'"))
            result = await conn.execute(text(wrapped), {"lim": limit + 1})
            keys = list(result.keys())
            raw = result.fetchall()
        truncated = len(raw) > limit
        from app.core.data_ask.utils.json_safe import json_safe_value

        rows = [[json_safe_value(v) for v in row] for row in raw[:limit]]
        safe_cols = [json_safe_value(k) for k in keys]
        return QueryResult(columns=safe_cols, rows=rows, row_count=len(rows), truncated=truncated)

    def _quote_table(self, table_name: str) -> str:
        parts = table_name.split(".")
        return ".".join(f'"{p}"' for p in parts)

    async def close(self) -> None:
        await self._engine.dispose()
