"""Excel cell reference ↔ zero-indexed (row, col) conversion."""

from __future__ import annotations

import re


def cell_ref_to_indices(cell_ref: str) -> tuple[int, int]:
    match = re.match(r"^([A-Za-z]+)(\d+)$", cell_ref.strip())
    if not match:
        raise ValueError(f"Invalid cell reference: {cell_ref}")

    col_str = match.group(1).upper()
    row_index = int(match.group(2)) - 1

    col_index = 0
    for char in col_str:
        col_index = col_index * 26 + (ord(char) - ord("A") + 1)
    col_index -= 1

    return row_index, col_index
