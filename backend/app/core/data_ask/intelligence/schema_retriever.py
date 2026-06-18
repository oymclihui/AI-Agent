"""Rank registered tables by relevance to the user question."""
from __future__ import annotations

import re
from typing import Any


def _tokens(text: str) -> set[str]:
    parts = re.findall(r"[\w\u4e00-\u9fff]+", (text or "").lower())
    return {p for p in parts if len(p) >= 2}


def rank_tables(question: str, tables: list[dict[str, Any]], *, top_k: int = 5) -> list[dict[str, Any]]:
    if not tables:
        return []
    if len(tables) <= top_k:
        return list(tables)

    qtok = _tokens(question)
    scored: list[tuple[float, dict[str, Any]]] = []
    for t in tables:
        score = 0.0
        tname = str(t.get("table_name") or "").lower()
        if tname and tname in question.lower():
            score += 5.0
        for tok in qtok:
            if tok in tname:
                score += 2.0
        for col in t.get("columns") or []:
            cname = str(col.get("name") if isinstance(col, dict) else col).lower()
            if cname in qtok or any(tok in cname for tok in qtok):
                score += 1.0
            desc = str(col.get("description") or "").lower() if isinstance(col, dict) else ""
            if desc and any(tok in desc for tok in qtok):
                score += 0.5
        for m in t.get("metrics") or []:
            if isinstance(m, dict):
                for field in ("name", "definition"):
                    val = str(m.get(field) or "").lower()
                    if val and any(tok in val for tok in qtok):
                        score += 1.5
        scored.append((score, t))

    scored.sort(key=lambda x: (-x[0], str(x[1].get("table_name") or "")))
    picked = [t for s, t in scored if s > 0][:top_k]
    if len(picked) < min(2, len(tables)):
        picked = [t for _, t in scored[:top_k]]
    return picked
