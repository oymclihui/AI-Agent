"""Export parsed wide tables to Excel or CSV."""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd


class Exporter:
    @staticmethod
    def export_excel(df: pd.DataFrame, output_dir: str, filename: str | None = None) -> str:
        os.makedirs(output_dir, exist_ok=True)
        if not filename:
            filename = f"parsed_wide_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if not filename.endswith(".xlsx"):
            filename += ".xlsx"
        file_path = os.path.join(output_dir, filename)
        df.to_excel(file_path, index=False, engine="openpyxl")
        return file_path

    @staticmethod
    def export_csv(df: pd.DataFrame, output_dir: str, filename: str | None = None) -> str:
        os.makedirs(output_dir, exist_ok=True)
        if not filename:
            filename = f"parsed_wide_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if not filename.endswith(".csv"):
            filename += ".csv"
        file_path = os.path.join(output_dir, filename)
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        return file_path
