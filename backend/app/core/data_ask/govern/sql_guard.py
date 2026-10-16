"""SQL safety: SELECT-only, single statement, table whitelist."""
from __future__ import annotations

import re

try:
    import sqlglot
    from sqlglot import exp

    _HAS_SQLGLOT = True
except ImportError:
    _HAS_SQLGLOT = False

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|EXEC|EXECUTE|CALL|MERGE|REPLACE)\b",
    re.IGNORECASE,
)
_MULTI_STMT = re.compile(r";\s*\S")

# sqlglot 26 dialect names. vastbase is PostgreSQL-compatible. HANA is not
# bundled; Oracle is the closest parser for quoted identifiers.
_DIALECT_MAP = {
    "postgresql": "postgres",
    "postgres": "postgres",
    "pg": "postgres",
    "vastbase": "postgres",
    "mysql": "mysql",
    "doris": "doris",
    "starrocks": "starrocks",
    "hive": "hive",
    "hana": "oracle",
}


def sqlglot_dialect(driver: str | None) -> str:
    key = (driver or "postgres").strip().lower()
    return _DIALECT_MAP.get(key, "postgres")


def validate_select_sql(
    sql: str,
    *,
    allowed_tables: set[str] | None = None,
    dialect: str | None = None,
) -> tuple[bool, str]:
    text = (sql or "").strip()
    if not text:
        return False, "SQL is empty"
    if _FORBIDDEN.search(text):
        return False, "Only SELECT queries are allowed"
    if _MULTI_STMT.search(text.rstrip(";")):
        return False, "Multiple statements are not allowed"
    upper = text.upper()
    if not upper.startswith("SELECT") and not upper.startswith("WITH"):
        return False, "Query must start with SELECT or WITH"

    if _HAS_SQLGLOT:
        ok, msg, refs = _validate_with_sqlglot(text, sqlglot_dialect(dialect))
        if not ok:
            return False, msg
    else:
        refs = _extract_table_refs(text)

    if allowed_tables:
        unknown = refs - {_normalize_table(t) for t in allowed_tables}
        if unknown:
            return False, f"Tables not in whitelist: {', '.join(sorted(unknown))}"
    return True, "OK"


def _validate_with_sqlglot(text: str, dialect: str) -> tuple[bool, str, set[str]]:
    try:
        parsed = sqlglot.parse_one(text, read=dialect)
    except Exception as exc:
        return False, f"Invalid SQL ({dialect}): {exc}", set()

    if parsed.find(exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter):
        return False, "Only SELECT queries are allowed", set()

    if not isinstance(parsed, (exp.Select, exp.Union, exp.With)):
        if not parsed.find(exp.Select):
            return False, "Query must be SELECT", set()

    refs: set[str] = set()
    for table in parsed.find_all(exp.Table):
        name = table.name
        if name:
            refs.add(_normalize_table(name))
    if not refs:
        refs = _extract_table_refs(text)
    return True, "OK", refs


def _normalize_table(name: str) -> str:
    return name.strip().strip('"').strip("`").split(".")[-1].lower()


def _extract_table_refs(sql: str) -> set[str]:
    refs: set[str] = set()
    for m in re.finditer(r"\bFROM\s+([`\"]?[\w.]+[`\"]?)", sql, re.IGNORECASE):
        refs.add(_normalize_table(m.group(1)))
    for m in re.finditer(r"\bJOIN\s+([`\"]?[\w.]+[`\"]?)", sql, re.IGNORECASE):
        refs.add(_normalize_table(m.group(1)))
    return refs
