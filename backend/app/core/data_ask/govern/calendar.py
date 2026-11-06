"""业务日历。问数里的「今天」用 Asia/Shanghai 的日历日，不用数据库 CURRENT_DATE，也不用 MAX(RQ)。"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta

_REL_CACHE = re.compile(
    r"今天|今日|昨天|昨日|前天|本周|这周|上周|本月|这月|上月|今年|去年|"
    r"最近|近\s*[0-9一二三四五六七八九十两]|过去"
)
_NO_CACHE = ("同期", "同比", "环比")


def business_today() -> date:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Shanghai")).date()
    except Exception:
        return (datetime.utcnow() + timedelta(hours=8)).date()


def shift_year(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def shift_year_iso(iso: str) -> str:
    return shift_year(date.fromisoformat(iso)).isoformat()


def _month_end(day: date) -> date:
    return day.replace(day=monthrange(day.year, day.month)[1])


def previous_window(start: date, end: date) -> tuple[date, date]:
    """环比窗口：单日→前一日；月初至今→上月同日；完整自然月→上一个完整月；其余等长前移。"""
    if start == end:
        prev = start - timedelta(days=1)
        return prev, prev
    if start.day == 1 and end == _month_end(start):
        prev_last = start - timedelta(days=1)
        return prev_last.replace(day=1), _month_end(prev_last)
    if start.day == 1 and end.month == start.month and end.year == start.year:
        prev_last = start - timedelta(days=1)
        prev_start = prev_last.replace(day=1)
        day_n = min(end.day, _month_end(prev_start).day)
        return prev_start, prev_start.replace(day=day_n)
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    return prev_start, prev_end


def is_context_followup(question: str) -> bool:
    return any(word in (question or "") for word in _NO_CACHE)


def question_cache_key_text(question: str) -> str:
    """相对时间问句把日历日写进缓存键，过了零点不再命中昨天的结果。"""
    text = question or ""
    if _REL_CACHE.search(text):
        return f"{text}\n@asof:{business_today().isoformat()}"
    return text
