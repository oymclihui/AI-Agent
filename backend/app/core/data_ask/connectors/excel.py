"""Excel folder connector — each registered file acts as a logical table."""
from __future__ import annotations

from typing import Any

from app.core.data_ask.connectors.base import ColumnMeta, DataConnector, QueryResult, TableMeta
from app.core.data_ask.excel.introspect import _read_excel, introspect_excel_file
from app.core.data_ask.excel.storage import excel_folder, list_excel_files
from app.core.data_ask.utils.json_safe import json_safe_value


class ExcelFolderConnector(DataConnector):
    driver = "excel_folder"

    def __init__(self, *, source_id: str) -> None:
        self.source_id = source_id

    async def test(self) -> tuple[bool, str]:
        folder = excel_folder(self.source_id)
        if not folder.exists():
            return False, "Excel folder not found"
        count = len(list_excel_files(self.source_id))
        return True, f"Excel folder OK ({count} file(s))"

    async def list_tables(self) -> list[str]:
        return [item["name"] for item in list_excel_files(self.source_id)]

    async def describe_table(self, table_name: str) -> TableMeta:
        meta = introspect_excel_file(self.source_id, table_name)
        cols = [
            ColumnMeta(name=c["name"], data_type=c["type"], nullable=c.get("nullable", True))
            for c in meta.get("columns") or []
        ]
        return TableMeta(name=table_name, schema="excel", columns=cols, row_estimate=meta.get("row_count"))

    async def sample_rows(self, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
        from app.core.data_ask.excel.storage import resolve_excel_file

        path = resolve_excel_file(self.source_id, table_name)
        df = _read_excel(path)
        return [json_safe_value(r) for r in df.head(limit).to_dict(orient="records")]

    async def execute_select(self, sql: str, *, limit: int = 5000, timeout_s: int = 30) -> QueryResult:
        raise NotImplementedError("Excel folder sources use Python analysis, not SQL execution")
