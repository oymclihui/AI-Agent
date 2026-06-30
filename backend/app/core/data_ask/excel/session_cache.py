"""In-process Excel full-data cache for data-ask sessions."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import pandas as pd

from app.core.data_ask.excel.full_load import load_all_excel_data

_lock = asyncio.Lock()
_cache: dict[str, dict[str, Any]] = {}


def get_load_status(source_id: str) -> dict[str, Any]:
    entry = _cache.get(source_id)
    if not entry:
        return {"status": "idle", "sheet_count": 0, "total_rows": 0, "file_count": 0}
    return {
        "status": entry.get("status", "idle"),
        "sheet_count": entry.get("sheet_count", 0),
        "total_rows": entry.get("total_rows", 0),
        "file_count": entry.get("file_count", 0),
        "loaded_at": entry.get("loaded_at"),
        "error": entry.get("error"),
        "table_names": entry.get("table_names") or [],
    }


def get_all_frames(source_id: str) -> dict[str, pd.DataFrame]:
    entry = _cache.get(source_id) or {}
    if entry.get("status") != "ready":
        raise ValueError("Excel data not fully loaded yet")
    frames = entry.get("frames") or {}
    return dict(frames)


def get_all_tables(source_id: str) -> list[dict[str, Any]]:
    entry = _cache.get(source_id) or {}
    if entry.get("status") != "ready":
        raise ValueError("Excel data not fully loaded yet")
    return list(entry.get("tables") or [])


def ensure_ready(source_id: str) -> None:
    status = get_load_status(source_id).get("status")
    if status == "loading":
        raise ValueError("正在加载完整数据，请稍候...")
    if status != "ready":
        raise ValueError("Excel 数据尚未完成全量加载，请先触发 preload")


def build_provenance(filenames: list[str], frames: dict[str, pd.DataFrame]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for name in filenames:
        if name in seen:
            continue
        seen.add(name)
        df = frames.get(name)
        if df is None:
            continue
        if "::" in name:
            file_part, sheet = name.split("::", 1)
            lines.append(f"{file_part} / {sheet} / 共 {len(df)} 行 × {len(df.columns)} 列")
        else:
            lines.append(f"{name} / 共 {len(df)} 行 × {len(df.columns)} 列")
    return lines


async def preload_excel_source(source_id: str, *, force: bool = False) -> dict[str, Any]:
    async with _lock:
        current = _cache.get(source_id)
        if not force and current and current.get("status") == "ready":
            return get_load_status(source_id)

        _cache[source_id] = {
            "status": "loading",
            "sheet_count": 0,
            "total_rows": 0,
            "file_count": 0,
            "loaded_at": None,
            "error": None,
        }

    try:
        payload = await asyncio.to_thread(load_all_excel_data, source_id)
        summary = payload["summary"]
        async with _lock:
            _cache[source_id] = {
                "status": "ready",
                "frames": payload["frames"],
                "tables": payload["tables"],
                "sheet_count": summary["sheet_count"],
                "total_rows": summary["total_rows"],
                "file_count": summary["file_count"],
                "table_names": summary["table_names"],
                "loaded_at": time.time(),
                "error": None,
            }
        return get_load_status(source_id)
    except Exception as exc:
        async with _lock:
            _cache[source_id] = {
                "status": "error",
                "sheet_count": 0,
                "total_rows": 0,
                "file_count": 0,
                "loaded_at": None,
                "error": str(exc)[:500],
            }
        raise


def invalidate_excel_cache(source_id: str) -> None:
    _cache.pop(source_id, None)
