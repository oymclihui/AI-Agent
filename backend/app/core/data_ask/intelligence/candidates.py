"""Choose among SQL candidates after a single execution probe."""
from __future__ import annotations

from typing import Any


def question_needs_variants(question: str, tables: list[dict[str, Any]] | None) -> bool:
    names = [str(table.get("table_name") or "").strip() for table in (tables or [])]
    names = [name for name in names if name]
    if len(names) < 2:
        return False
    folded = (question or "").lower()
    return not any(name.lower() in folded for name in names)


def hint_hits(sql: str, tables: list[dict[str, Any]] | None, question: str) -> int:
    hits = 0
    seen: set[str] = set()
    for table in tables or []:
        for col in table.get("columns") or []:
            if not isinstance(col, dict):
                continue
            for example in col.get("examples") or []:
                text = str(example).strip()
                if len(text) < 2 or text in seen:
                    continue
                if text in (question or "") and text in (sql or ""):
                    seen.add(text)
                    hits += 1
    return hits


def rank_probes(probes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Prefer a successful query that returns rows and uses a hinted value."""
    successful = [probe for probe in probes if not probe.get("error")]
    if not successful:
        return None
    with_rows = [probe for probe in successful if (probe.get("row_count") or 0) > 0]
    pool = with_rows or successful
    return max(
        pool,
        key=lambda probe: (
            int(probe.get("hint_hits") or 0),
            1 if (probe.get("row_count") or 0) > 0 else 0,
        ),
    )
