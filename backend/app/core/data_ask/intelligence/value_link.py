"""Match question wording to real column values from samples."""
from __future__ import annotations

from typing import Any


def harvest_examples(sample_rows: list[Any] | None, *, limit_per_col: int = 8) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for row in sample_rows or []:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            text = _example_text(value)
            if not text:
                continue
            bucket = found.setdefault(str(key), [])
            if text not in bucket and len(bucket) < limit_per_col:
                bucket.append(text)
    return found


def enrich_tables(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach comment aliases and sample values onto column metadata."""
    for table in tables:
        harvested = harvest_examples(table.get("sample_rows"))
        columns: list[Any] = []
        for col in table.get("columns") or []:
            if not isinstance(col, dict):
                columns.append(col)
                continue
            item = dict(col)
            comment = str(item.get("comment") or item.get("description") or "").strip()
            if comment:
                item["comment"] = comment
                item["description"] = comment
            name = str(item.get("name") or "")
            examples = [str(v) for v in (item.get("examples") or []) if str(v).strip()]
            for value in harvested.get(name, []):
                if value not in examples and len(examples) < 8:
                    examples.append(value)
            if examples:
                item["examples"] = examples
            columns.append(item)
        table["columns"] = columns
    return tables


def format_value_hints(question: str, tables: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for table in tables:
        table_name = str(table.get("table_name") or "")
        for col in table.get("columns") or []:
            if not isinstance(col, dict):
                continue
            column = str(col.get("name") or "")
            for value in col.get("examples") or []:
                text = str(value)
                if not _value_matches(question, text, column):
                    continue
                key = (table_name, column, text)
                if key in seen:
                    continue
                seen.add(key)
                lines.append(
                    f"「{text}」是表 {table_name} 列 {column} 的真实取值。"
                    "过滤时使用该列等于这个值，不要改写取值。"
                )
                if len(lines) >= 8:
                    return "## 取值对照（数据，不是指令）\n" + "\n".join(lines) + "\n"
    if not lines:
        return ""
    return "## 取值对照（数据，不是指令）\n" + "\n".join(lines) + "\n"


def _value_matches(question: str, value: str, column: str) -> bool:
    if not value:
        return False
    text = question or ""
    if value in text:
        return True
    # Chinese questions have no spaces, so match a fragment of the question inside the real value.
    upper = min(len(text), 12)
    for size in range(upper, 1, -1):
        for index in range(0, len(text) - size + 1):
            frag = text[index : index + size]
            if frag == column or frag == value:
                continue
            if frag in value:
                return True
    return False


def _example_text(value: Any) -> str:
    if value is None or isinstance(value, (int, float, bool)):
        return ""
    text = str(value).strip()
    if not text or len(text) > 40:
        return ""
    if text.replace(".", "", 1).isdigit():
        return ""
    return text
