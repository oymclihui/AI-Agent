"""Normalize raw Excel cell values (trim, thousands, bracket negatives)."""

from __future__ import annotations

import re


class DataCleaner:
    @staticmethod
    def clean(value):
        if value is None:
            return 0
        if isinstance(value, (int, float)):
            return value

        text = str(value).strip().replace("\n", "").replace("\r", "")
        number = DataCleaner._try_parse_number(text)
        if number is not None:
            return number
        return text

    @staticmethod
    def _try_parse_number(text: str):
        if text == "":
            return 0

        bracket_match = re.match(r"^\(([0-9,]*\.?\d*)\)$", text)
        if bracket_match:
            inner = bracket_match.group(1).replace(",", "")
            try:
                return -float(inner)
            except ValueError:
                return None

        if re.match(r"^-?([0-9,]*\.?\d+)$", text):
            try:
                return float(text.replace(",", ""))
            except ValueError:
                return None
        return None
