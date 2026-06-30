"""Scan directories for Excel files."""

from __future__ import annotations

import os
from pathlib import Path

EXCEL_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".csv"}


def scan_excel_files(folder_path: str | Path, *, recursive: bool = False) -> list[str]:
    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"Directory not found: {folder}")
    if not folder.is_dir():
        raise ValueError(f"Not a directory: {folder}")

    excel_files: list[str] = []
    if recursive:
        for root, _, files in os.walk(folder):
            for filename in files:
                if Path(filename).suffix.lower() in EXCEL_EXTENSIONS:
                    excel_files.append(str(Path(root) / filename))
    else:
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in EXCEL_EXTENSIONS:
                excel_files.append(str(path))

    excel_files.sort()
    return excel_files
