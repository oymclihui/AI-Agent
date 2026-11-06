"""日期守卫：问句已经标明窗口时，SQL 里的 RQ 必须落在这个窗口内。

不再把多日条件收成「SQL 里出现过的最晚日期」。那个日期常常不是今天。
"""
from __future__ import annotations

import re

_WINDOW = re.compile(
    r"（其中「[^」]*」指\s*(\d{4}-\d{2}-\d{2})(?:\s*至\s*(\d{4}-\d{2}-\d{2}))?"
)
_LATEST = re.compile(r"(?:数据最新日期|最新营业日)为\s*(\d{4}-\d{2}-\d{2})")
_RQ_PRED = re.compile(
    r"\bRQ\s+IN\s*\([^)]*\)"
    r"|\bRQ\s+BETWEEN\s+'[^']+'\s+AND\s+'[^']+'"
    r"|\bRQ\s*(?:>=|<=|>|<)\s*'[^']+'"
    r"|\bRQ\s*=\s*'[^']+'",
    re.I,
)


def annotated_window(question: str) -> tuple[str, str] | None:
    match = _WINDOW.search(question or "")
    if not match:
        return None
    start = match.group(1)
    end = match.group(2) or start
    return start, end


def latest_biz_note(question: str) -> str | None:
    match = _LATEST.search(question or "")
    return match.group(1) if match else None


def fix_single_day_sql(question: str, sql: str) -> tuple[str, str | None]:
    """把 RQ 条件改回问句标注的窗口。同期/环比由两段 SQL 各自带日期，这里不动。"""
    if not sql:
        return sql, None
    if "「同期」" in (question or "") or "「上期」" in (question or ""):
        return sql, None
    window = annotated_window(question)
    if not window:
        return sql, None
    start, end = window
    replacement = f"RQ = '{start}'" if start == end else f"RQ BETWEEN '{start}' AND '{end}'"
    rewritten, count = _RQ_PRED.subn(replacement, sql)
    if count and rewritten != sql:
        return rewritten, "日期守卫：已按当前日期窗口改写"
    return sql, None
