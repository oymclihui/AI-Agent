"""把查询结果表格导出为 xlsx（供 /导出 指令发送文件）。"""
from __future__ import annotations

import os
import re
import tempfile
import uuid
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

MAX_ROWS = 5000
# 纯数字：整数或小数；不以 0 开头（避免工号/编号 00123 被当成数字）
_NUMBER = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")
_MIN_WIDTH = 8
_MAX_WIDTH = 50


def _display_width(text: str) -> int:
    """按中文占 2 列估算显示宽度。"""
    return sum(2 if ord(ch) > 127 else 1 for ch in text)


def _as_number(value: str) -> tuple[Any, str]:
    """数字样式的文本 → (数值, number_format)；非数字返回 (原文, "")。"""
    text = value.strip()
    if not text or len(text) > 15 or not _NUMBER.fullmatch(text):
        return value, ""
    if "." in text:
        return float(text), "#,##0.00"
    return int(text), "#,##0"


def to_xlsx(header: list[str], rows: list[list[str]], title: str = "查询结果") -> str | None:
    """写 xlsx 临时文件并返回路径；无有效表头返回 None。

    表格带冻结首行、列宽自适应、数字千分位与自动筛选，便于直接在 Excel 里分析。
    """
    if not header:
        return None
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = (title or "查询结果")[:31]

        header_fill = PatternFill("solid", fgColor="DDEBF7")
        headers = [str(cell) for cell in header]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        widths = [_display_width(name) for name in headers]
        for row in rows[:MAX_ROWS]:
            values: list[Any] = []
            formats: list[str] = []
            for col_index, raw in enumerate(row):
                text = "" if raw is None else str(raw)
                number, fmt = _as_number(text)
                values.append(number)
                formats.append(fmt)
                if col_index < len(widths):
                    widths[col_index] = max(widths[col_index], _display_width(text))
            ws.append(values)
            current = ws.max_row
            for col_index, fmt in enumerate(formats):
                if fmt:
                    ws.cell(row=current, column=col_index + 1).number_format = fmt

        for index, width in enumerate(widths, 1):
            size = max(_MIN_WIDTH, min(_MAX_WIDTH, width + 4))
            ws.column_dimensions[get_column_letter(index)].width = size

        ws.freeze_panes = "A2"
        if ws.max_row > 1:
            ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{ws.max_row}"

        path = os.path.join(tempfile.gettempdir(), f"wecom_export_{uuid.uuid4().hex}.xlsx")
        wb.save(path)
        return path
    except Exception as exc:
        logger.warning("wecom_export_failed", error=str(exc)[:200])
        return None
