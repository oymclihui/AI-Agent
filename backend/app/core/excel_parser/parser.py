"""Extract mapped cell values from Excel workbooks using a template."""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd

from app.core.excel_parser.cell_utils import cell_ref_to_indices
from app.core.excel_parser.cleaner import DataCleaner


class ExcelParser:
    def __init__(self, template: dict):
        self.template = template
        self.sheet_mappings = template.get("sheet_mappings", [])
        self.cleaner = DataCleaner()

    def parse(self, file_path: str) -> list[dict]:
        engine = self._get_engine(file_path)
        try:
            xl = pd.ExcelFile(file_path, engine=engine)
            available_sheets = xl.sheet_names
        except Exception as exc:
            raise ValueError(f"Cannot read Excel [{file_path}]: {exc}") from exc

        result: dict = {}
        matched_sheets: list[str] = []
        matched_any = False

        for sheet_config in self.sheet_mappings:
            sheet_name = sheet_config.get("sheet_name", "")
            field_mapping = sheet_config.get("field_mapping", {})
            if sheet_name not in available_sheets:
                continue

            matched_any = True
            matched_sheets.append(sheet_name)
            try:
                df = pd.read_excel(file_path, sheet_name=sheet_name, engine=engine, header=None)
            except Exception:
                continue

            if isinstance(field_mapping, list):
                for mapping_item in field_mapping:
                    field_name = mapping_item.get("field_name", "")
                    cell_ref = mapping_item.get("cell_ref", "")
                    if not field_name or not cell_ref or field_name in result:
                        continue
                    result[field_name] = self._extract_cell(df, field_name, cell_ref)
            else:
                for field_name, cell_ref in field_mapping.items():
                    if field_name in result:
                        continue
                    result[field_name] = self._extract_cell(df, field_name, cell_ref)

        if not matched_any:
            sheet_list = ", ".join(s.get("sheet_name", "") for s in self.sheet_mappings)
            available_list = ", ".join(available_sheets)
            raise ValueError(
                f"No configured sheets in [{os.path.basename(file_path)}]. "
                f"Expected [{sheet_list}], found [{available_list}]"
            )

        result["source_file"] = file_path
        result["file_name"] = os.path.basename(file_path)
        result["sheet_name"] = ",".join(matched_sheets)
        result["load_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return [result]

    def _extract_cell(self, df: pd.DataFrame, field_name: str, cell_ref: str):
        try:
            row_idx, col_idx = cell_ref_to_indices(cell_ref)
            if row_idx < len(df) and col_idx < len(df.columns):
                raw_value = df.iloc[row_idx, col_idx]
            else:
                raw_value = None
            return self.cleaner.clean(raw_value)
        except Exception:
            return None

    @staticmethod
    def _get_engine(file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        return "xlrd" if ext == ".xls" else "openpyxl"
