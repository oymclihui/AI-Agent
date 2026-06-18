"""Unified connector interface for business data sources."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RelationInfo:
    name: str
    object_type: str  # table | view


@dataclass
class ColumnMeta:
    name: str
    data_type: str
    nullable: bool = True
    comment: str = ""


@dataclass
class TableMeta:
    name: str
    schema: str = "public"
    columns: list[ColumnMeta] = field(default_factory=list)
    row_estimate: int | None = None
    partition_columns: list[str] = field(default_factory=list)


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool = False


class DataConnector(ABC):
    driver: str

    @abstractmethod
    async def test(self) -> tuple[bool, str]:
        ...

    @abstractmethod
    async def list_tables(self) -> list[str]:
        ...

    async def list_relations(
        self,
        *,
        search: str = "",
        object_type: str | None = None,
        limit: int = 120,
    ) -> list[RelationInfo]:
        """Tables and views available for data ask configuration."""
        from app.core.data_ask.connectors.relations import filter_relations

        names = await self.list_tables()
        rels = [RelationInfo(name=n, object_type="table") for n in names]
        filtered, _, _ = filter_relations(rels, search=search, object_type=object_type, limit=limit)
        return filtered

    @abstractmethod
    async def describe_table(self, table_name: str) -> TableMeta:
        ...

    @abstractmethod
    async def sample_rows(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def execute_select(self, sql: str, *, limit: int = 5000, timeout_s: int = 30) -> QueryResult:
        ...

    async def close(self) -> None:
        pass
