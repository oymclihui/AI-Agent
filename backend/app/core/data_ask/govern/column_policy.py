"""Column-level sensitivity checks for generated SQL."""
from __future__ import annotations

import re
from typing import Any

from app.core.auth.permissions import DataScope


def sensitive_columns(semantic_model: dict[str, Any] | None) -> dict[str, set[str]]:
    """Map table -> set of sensitive column names."""
    out: dict[str, set[str]] = {}
    if not semantic_model:
        return out
    for item in semantic_model.get("columns") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("sensitivity") or "").lower() not in ("core", "secret", "high"):
            continue
        table = str(item.get("table") or "*").lower()
        col = str(item.get("name") or "").lower()
        if col:
            out.setdefault(table, set()).add(col)
    for dim in semantic_model.get("dimensions") or []:
        if not isinstance(dim, dict):
            continue
        if str(dim.get("sensitivity") or "").lower() not in ("core", "secret", "high"):
            continue
        table = str(dim.get("table") or "*").lower()
        col = str(dim.get("column") or dim.get("name") or "").lower()
        if col:
            out.setdefault(table, set()).add(col)
    return out


def user_may_access_sensitive(user_is_admin: bool, scope: DataScope | None) -> bool:
    if user_is_admin:
        return True
    if scope and scope.has_permission("org:manage"):
        return True
    return False


def validate_sql_columns(
    sql: str,
    *,
    semantic_model: dict[str, Any] | None,
    user_is_admin: bool,
    scope: DataScope | None,
) -> tuple[bool, str]:
    if user_may_access_sensitive(user_is_admin, scope):
        return True, "OK"
    sens = sensitive_columns(semantic_model)
    if not sens:
        return True, "OK"
    refs = _extract_column_refs(sql)
    blocked: list[str] = []
    for table, cols in sens.items():
        for col in cols:
            if col in refs or (table == "*" and col in refs):
                blocked.append(col)
    if blocked:
        return False, f"Sensitive columns not allowed: {', '.join(sorted(set(blocked)))}"
    return True, "OK"


def _extract_column_refs(sql: str) -> set[str]:
    refs: set[str] = set()
    for m in re.finditer(r"\bSELECT\b([\s\S]*?)\bFROM\b", sql, re.IGNORECASE):
        chunk = m.group(1)
        for part in chunk.split(","):
            part = part.strip()
            if not part or part == "*":
                continue
            token = part.split()[-1].strip('"').strip("`").lower()
            if "." in token:
                token = token.split(".")[-1]
            refs.add(token)
    for m in re.finditer(r"\b(WHERE|AND|OR|ON|GROUP BY|ORDER BY|HAVING)\b[^;]*", sql, re.IGNORECASE):
        for word in re.findall(r"[`\"]?\w+[`\"]?", m.group(0)):
            refs.add(word.strip('"').strip("`").lower())
    return refs
