"""Filter helpers for table/view relation lists."""
from __future__ import annotations

from typing import Any

DEFAULT_RELATION_LIMIT = 120
SEARCH_RELATION_LIMIT = 200


def filter_relations(
    rels: list[Any],
    *,
    search: str = "",
    object_type: str | None = None,
    limit: int = DEFAULT_RELATION_LIMIT,
) -> tuple[list[Any], int, bool]:
    """Return (filtered, total_matched, truncated)."""
    total = len(rels)
    out = rels
    if object_type in ("table", "view"):
        out = [r for r in out if r.object_type == object_type]
    q = search.strip().lower()
    if q:
        out = [r for r in out if q in r.name.lower()]
    matched = len(out)
    cap = SEARCH_RELATION_LIMIT if q else limit
    truncated = matched > cap
    return out[:cap], matched, truncated
