"""日期口径硬约束：单日类提问（昨天/今天）不得生成多日范围 SQL。

模型常把「昨天」写成 RQ IN ('前天','昨天')，导致指标被两天合计。
这里用确定性改写兜底，避免依赖提示词。
"""
from __future__ import annotations

import re

_SINGLE_DAY = ("昨天", "昨日", "今天", "今日", "当天", "上一日", "昨日")
_COMPARE = (
    "趋势", "对比", "环比", "同比", "最近", "近一周", "近7天", "近七天", "本周", "上周",
    "本月", "上月", "每月", "每天", "每日", "走势", "排名", "top", "最高", "最低", "分布", "占比",
)

_IN_LIST = re.compile(r"RQ\s+IN\s*\(\s*'[^']+'(?:\s*,\s*'[^']+')*\s*\)", re.I)
_BETWEEN = re.compile(r"RQ\s+BETWEEN\s+'([^']+)'\s+AND\s+'([^']+)'", re.I)
_SINCE = re.compile(r"RQ\s*(?:>=|>)\s*'([^']+)'", re.I)


def is_single_day_question(question: str) -> bool:
    q = str(question or "").lower()
    if any(k in q for k in _COMPARE):
        return False
    return any(k in q for k in _SINGLE_DAY)


def _latest_in(match_text: str) -> str:
    dates = re.findall(r"'([^']+)'", match_text)
    return max(dates) if dates else ""


def fix_single_day_sql(question: str, sql: str) -> tuple[str, str | None]:
    """返回 (改写后的 SQL, 命中说明)。非单日提问原样返回。"""
    if not sql or not is_single_day_question(question):
        return sql, None
    original = sql

    def _repl_in(m: re.Match) -> str:
        latest = _latest_in(m.group(0))
        return f"RQ = '{latest}'" if latest else m.group(0)

    sql = _IN_LIST.sub(_repl_in, sql)
    sql = _BETWEEN.sub(lambda m: f"RQ = '{max(m.group(1), m.group(2))}'", sql)
    sql = _SINCE.sub(lambda m: f"RQ = '{m.group(1)}'", sql)
    if sql != original:
        return sql, "单日口径修正：多日范围已收敛为最新营业日"
    return sql, None
