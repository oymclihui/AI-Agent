"""Full Excel workbook load — all sheets, all rows (within size guards)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from app.core.data_ask.excel.storage import EXCEL_EXTENSIONS, list_excel_files, resolve_excel_file
from app.core.data_ask.utils.json_safe import json_safe_value


def _dtype_label(series: pd.Series) -> str:
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    return "text"


def read_workbook_frames(source_id: str, filename: str) -> dict[str, pd.DataFrame]:
    path = resolve_excel_file(source_id, filename)
    suffix = path.suffix.lower()
    frames: dict[str, pd.DataFrame] = {}
    if suffix == ".csv":
        df = pd.read_csv(path)
        df.columns = [str(c).strip() for c in df.columns]
        frames[f"{filename}"] = df
        return frames
    try:
        book = pd.ExcelFile(path)
    except ImportError as exc:
        if suffix == ".xls":
            raise ValueError(
                "无法读取旧版 .xls：请将文件另存为 .xlsx 后重新上传。"
            ) from exc
        raise ValueError(f"无法读取 Excel 文件 {filename}: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"无法读取 Excel 文件 {filename}: {exc}") from exc

    for sheet in book.sheet_names:
        df = book.parse(sheet)
        df.columns = [str(c).strip() for c in df.columns]
        key = f"{filename}::{sheet}" if len(book.sheet_names) > 1 else filename
        frames[key] = df
    return frames


def table_meta_from_frame(table_name: str, df: pd.DataFrame, *, file_name: str, sheet_name: str | None) -> dict[str, Any]:
    columns = [
        {"name": str(col), "type": _dtype_label(df[col]), "nullable": bool(df[col].isna().any())}
        for col in df.columns
    ]
    samples = [json_safe_value(r) for r in df.head(3).to_dict(orient="records")]
    return {
        "table_name": table_name,
        "schema": "excel",
        "columns": columns,
        "partition_columns": [],
        "sample_rows": samples,
        "row_count": int(len(df)),
        "sheet_hint": sheet_name or Path(file_name).stem,
        "file_name": file_name,
        "sheet_name": sheet_name,
        "max_row": int(len(df)),
        "column_count": int(len(df.columns)),
    }


def load_all_excel_data(source_id: str) -> dict[str, Any]:
    files = list_excel_files(source_id)
    if not files:
        raise ValueError("No Excel files uploaded")

    all_frames: dict[str, pd.DataFrame] = {}
    all_tables: list[dict[str, Any]] = []
    sheet_count = 0
    total_rows = 0

    for item in files:
        name = item["name"]
        file_frames = read_workbook_frames(source_id, name)
        for table_name, df in file_frames.items():
            sheet_name = table_name.split("::", 1)[1] if "::" in table_name else None
            all_frames[table_name] = df
            meta = table_meta_from_frame(table_name, df, file_name=name, sheet_name=sheet_name)
            all_tables.append(meta)
            sheet_count += 1
            total_rows += int(len(df))

    return {
        "frames": all_frames,
        "tables": all_tables,
        "summary": {
            "file_count": len(files),
            "sheet_count": sheet_count,
            "total_rows": total_rows,
            "table_names": list(all_frames.keys()),
        },
    }
