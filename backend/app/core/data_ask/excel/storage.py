"""On-disk storage for Excel folder data sources."""
from __future__ import annotations

import shutil
from pathlib import Path

from app.config import settings

EXCEL_EXTENSIONS = {".xlsx", ".xls", ".csv"}


def excel_root() -> Path:
    root = Path(settings.LOCAL_UPLOADS_DIR).resolve() / "data_ask"
    root.mkdir(parents=True, exist_ok=True)
    return root


def excel_folder(source_id: str) -> Path:
    folder = excel_root() / source_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def ensure_excel_folder(source_id: str) -> Path:
    return excel_folder(source_id)


def resolve_excel_file(source_id: str, filename: str) -> Path:
    safe = Path(filename).name
    if not safe or safe != filename:
        raise ValueError("Invalid file name")
    path = excel_folder(source_id) / safe
    if not path.exists():
        raise FileNotFoundError(f"Excel not found: {safe}")
    if path.suffix.lower() not in EXCEL_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    return path


def list_excel_files(source_id: str) -> list[dict]:
    folder = excel_folder(source_id)
    items: list[dict] = []
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in EXCEL_EXTENSIONS:
            continue
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_at": stat.st_mtime,
            }
        )
    return items


def folder_total_bytes(source_id: str) -> int:
    return sum(item["size_bytes"] for item in list_excel_files(source_id))


def clear_excel_folder(source_id: str) -> None:
    folder = excel_folder(source_id)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)


def remove_excel_folder(source_id: str) -> None:
    shutil.rmtree(excel_folder(source_id), ignore_errors=True)
