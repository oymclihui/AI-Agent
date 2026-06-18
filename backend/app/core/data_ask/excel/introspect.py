"""Introspect Excel files for schema registration."""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.core.data_ask.excel.storage import resolve_excel_file
from app.core.data_ask.utils.json_safe import json_safe_value


def _read_excel(path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            df = pd.read_csv(path)
        else:
            df = pd.read_excel(path)
    except ImportError as exc:
        if suffix == ".xls":
            raise ValueError(
                "无法读取旧版 .xls 文件：服务器缺少 xlrd 依赖。"
                "请将文件在 Excel 中另存为 .xlsx 后重新上传。"
            ) from exc
        raise
    except Exception as exc:
        raise ValueError(f"无法读取 Excel 文件 {path.name}: {exc}") from exc
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _dtype_label(series: pd.Series) -> str:
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    return "text"


def introspect_excel_file(source_id: str, filename: str, *, sample_limit: int = 3) -> dict[str, Any]:
    path = resolve_excel_file(source_id, filename)
    df = _read_excel(path)
    columns = [
        {"name": str(col), "type": _dtype_label(df[col]), "nullable": bool(df[col].isna().any())}
        for col in df.columns
    ]
    samples = [json_safe_value(r) for r in df.head(sample_limit).to_dict(orient="records")]
    return {
        "table_name": filename,
        "schema": "excel",
        "columns": columns,
        "partition_columns": [],
        "sample_rows": samples,
        "row_count": int(len(df)),
        "sheet_hint": path.stem,
    }


async def introspect_excel_files(source_id: str, filenames: list[str]) -> list[dict[str, Any]]:
    return [introspect_excel_file(source_id, name) for name in filenames]
