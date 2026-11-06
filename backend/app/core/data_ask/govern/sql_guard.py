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

# LLM 常写出「AS 交易笔数(客流)」这类带括号的别名 —— 语法非法，sqlglot 直接解析失败。
# 只处理中文别名，避免误伤 CAST(x AS DECIMAL(10,2)) 之类。
_ALIAS_PAREN = re.compile(
    r"\bAS\s+([\u4e00-\u9fa5][^\s,(（]*)\s*[（(]\s*([^（()）]*)\s*[）)]",
    re.IGNORECASE,
)

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


def sanitize_aliases(sql: str) -> str:
    """把「AS 交易笔数(客流)」这类非法别名规范化成「AS 交易笔数_客流」。

    带括号的别名在 SQL 语法上非法，会让 sqlglot/数据库直接报 Unexpected token，
    整条问数失败。这里做确定性修复，不依赖模型是否遵守提示词。
    """
    text = sql or ""

    def _sub(match: "re.Match[str]") -> str:
        base = match.group(1).strip()
        qualifier = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5_]+", "", match.group(2))
        return f"AS {base}_{qualifier}" if qualifier else f"AS {base}"

    return _ALIAS_PAREN.sub(_sub, text)


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


def disambiguate_subquery_columns(sql: str, dialect: str | None = None) -> str:
    """给"只有一张表"的子查询里未限定表名的列补上表前缀，消除 StarRocks 等数据库的歧义报错。

    场景：WHERE x IN (SELECT FDBH FROM SR_FD_QX WHERE RYID='...') —— 子查询列 FDBH 未限定，
    StarRocks 会把外层同名列也纳入作用域，报 Column 'FDBH' is ambiguous。
    仅当子查询 FROM/JOIN 只有一张表时才安全加前缀；多表 JOIN 保持原样。
    """
    if not _HAS_SQLGLOT:
        return sanitize_aliases(sql)
    text = sanitize_aliases((sql or "").strip())
    if not text:
        return sql
    try:
        parsed = sqlglot.parse_one(text, read=sqlglot_dialect(dialect))
    except Exception:
        # 解析失败也保留别名消毒结果，交由后续校验给出最终结论
        return text

    for col in parsed.find_all(exp.Column):
        # 已带表前缀的列不动
        if col.table:
            continue
        # 向上找最近的 Select 祖先，确定该列所属查询作用域
        scope = col.parent
        while scope is not None and not isinstance(scope, exp.Select):
            scope = scope.parent
        if scope is None:
            continue
        tables = _tables_in_select_scope(scope)
        if len(tables) == 1:
            _tname, talias = tables[0]
            col.set("table", exp.to_identifier(talias))

    return parsed.sql(dialect=sqlglot_dialect(dialect))


def _tables_in_select_scope(sel: "exp.Select") -> list[tuple[str, str]]:
    """返回某 Select 作用域内 FROM/JOIN 直接引用的表 [(表名, 别名或表名)]，不含子查询里的表。"""
    tables: list[tuple[str, str]] = []
    frm = sel.args.get("from")
    if frm is not None:
        for t in frm.find_all(exp.Table):
            tables.append((t.name, t.alias_or_name))
    for j in sel.args.get("joins") or []:
        for t in j.find_all(exp.Table):
            tables.append((t.name, t.alias_or_name))
    return tables


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
