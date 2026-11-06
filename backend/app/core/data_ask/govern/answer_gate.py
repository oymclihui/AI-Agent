"""问数放行前的核对。店名、表粒度、未写日期的全历史、报告数字，都不靠「SQL 能跑」来判断。"""
from __future__ import annotations

import re
import time
from datetime import date
from typing import Any

_STORE_SUFFIX = (
    "广场店", "便利店", "旗舰店", "专卖店", "专营店", "连锁店",
    "大卖场", "超市", "商场", "门市", "分店", "卖场", "门店", "店",
)
_STORE_RE = re.compile(
    r"[\u4e00-\u9fa5A-Za-z0-9]{2,12}?(?:广场店|便利店|旗舰店|专卖店|专营店|连锁店|大卖场|超市|商场|门市|分店|卖场|门店|店)"
)
_NOISE_PREFIX = (
    "系统表中没有", "表中没有", "没有叫", "没有", "不存在",
    "要控制查询门店为", "控制查询门店为", "查询门店为", "要控制", "控制查询",
    "查询", "门店为", "为",
)
_TIME_PREFIX = ("今天", "今日", "昨天", "昨日", "前天", "本周", "上周", "本月", "上月")
_GENERIC_STORE = {
    "各门店", "每个门店", "按门店", "哪个门店", "哪家店", "门店", "这家店", "那家店", "分店",
}
_GRAIN_DIM = re.compile(r"商品|单品|货号|条码|二级分类|品类|分类")
_GRAIN_FLOW = re.compile(r"客流|交易笔数|成交笔数")
_TICKET_OVER = re.compile(r"客单.{0,6}超过|超过\s*\d+(?:\.\d+)?\s*元.{0,8}(?:笔|交易)")
_CUMULATIVE = re.compile(r"累计|全部|历史|至今|所有时间|一共|总共|全量")
_TIME_WORD = re.compile(
    r"今天|今日|昨天|昨日|前天|本周|上周|本月|上月|今年|去年|最新营业日|最新一天|"
    r"\d{4}\s*[-/年]\s*\d{1,2}|\d{1,2}\s*月|同期|同比|环比|最近|近\s*\d+\s*[天日]"
)
_CN_MONTHS = (
    ("十二", 12), ("十一", 11), ("十", 10), ("九", 9), ("八", 8), ("七", 7),
    ("六", 6), ("五", 5), ("四", 4), ("三", 3), ("二", 2), ("一", 1),
)
_ABSENCE = re.compile(r"没有|未提供|缺失|仅含|只有|未包含|不存在")
_MONTH_IN_LINE = re.compile(r"([一二三四五六七八九十]{1,2}|\d{1,2})\s*月")
_STORE_CACHE: dict[str, tuple[float, list[str]]] = {}
_CACHE_TTL = 3600.0


def store_mentions(question: str) -> list[str]:
    """抽出点名的门店。指令里的「没有」「系统表中没有」不算店名的一部分。"""
    found: list[str] = []
    for match in _STORE_RE.finditer(question or ""):
        phrase = match.group(0)
        changed = True
        while changed:
            changed = False
            for noise in _TIME_PREFIX + _NOISE_PREFIX:
                if phrase.startswith(noise) and len(phrase) - len(noise) >= 2:
                    phrase = phrase[len(noise):]
                    changed = True
                    break
        if phrase in _GENERIC_STORE or phrase in _STORE_SUFFIX:
            continue
        if phrase not in found:
            found.append(phrase)
    # 长的优先留下，避免「卖场店」又留下「场店」
    kept: list[str] = []
    for phrase in sorted(found, key=len, reverse=True):
        if any(phrase != other and phrase in other for other in kept):
            continue
        kept.append(phrase)
    return kept


def store_stem(phrase: str) -> str:
    if phrase.endswith("广场店") and len(phrase) > 3:
        return phrase[:-1]
    for suffix in _STORE_SUFFIX:
        if phrase.endswith(suffix) and len(phrase) - len(suffix) >= 2:
            return phrase[: -len(suffix)]
    return phrase


def match_store(phrase: str, names: list[str]) -> tuple[str | None, list[str]]:
    """唯一命中返回标准店名。没命中返回 (None, 最多 5 个现有店名)。多命中返回 (None, 候选)。"""
    cleaned = [str(name).strip() for name in names if str(name or "").strip()]
    if phrase in cleaned:
        return phrase, []
    stem = store_stem(phrase)
    hits = [name for name in cleaned if name.startswith(stem) or stem in name]
    # 「西安」可以命中「西安广场超市」，但「卖场」不能靠包含关系去撞别的店
    strict = [name for name in cleaned if name.startswith(stem)]
    if len(strict) == 1:
        return strict[0], []
    if len(strict) > 1:
        return None, strict[:5]
    return None, cleaned[:5]


def grain_refusal(question: str) -> str | None:
    """客流表只有店和天。问商品、分类或单笔超过多少时，不拿总笔数去答。"""
    text = question or ""
    if _TICKET_OVER.search(text):
        return "客流表只有门店和日期上的合计笔数，没有单笔客单。答不了「客单超过多少元的交易笔数」。"
    if _GRAIN_DIM.search(text) and _GRAIN_FLOW.search(text):
        return (
            "客流表只有日期、门店、交易笔数、营业额，没有商品，也没有二级分类。"
            "销售明细有分类和商品，但没有客流笔数。这个问法两边都对不上，所以不返回交易笔数。"
        )
    return None


def store_refusal(question: str, names: list[str]) -> tuple[str | None, str | None]:
    """返回 (答复, 命中的标准店名)。答复非空表示停。"""
    mentions = store_mentions(question)
    if not mentions:
        return None, None
    if not names:
        phrase = mentions[0]
        return f"门店名单暂时对不上，不能把别的店的数说成「{phrase}」。", None
    matched: list[str] = []
    for phrase in mentions:
        hit, options = match_store(phrase, names)
        if hit:
            matched.append(hit)
            continue
        if options and all(store_stem(phrase) and store_stem(phrase) in name for name in options) and len(options) > 1:
            listed = "、".join(options)
            return f"「{phrase}」对上了多家门店：{listed}。请指定一家。", None
        listed = "、".join(options) if options else "（名单为空）"
        return f"没有叫「{phrase}」的门店。现在的门店是：{listed}。", None
    return None, matched[-1] if matched else None


def chinese_months(question: str) -> list[int]:
    text = question or ""
    used = [False] * len(text)
    found: list[int] = []
    for name, number in _CN_MONTHS:
        token = name + "月"
        start = 0
        while True:
            index = text.find(token, start)
            if index < 0:
                break
            if not any(used[index:index + len(token)]):
                found.append(number)
                for pos in range(index, index + len(token)):
                    used[pos] = True
            start = index + len(token)
    return found


def chinese_month_span(question: str, year: int) -> tuple[date, date] | None:
    months = chinese_months(question)
    if not months:
        return None
    import calendar
    lo, hi = min(months), max(months)
    return date(year, lo, 1), date(year, hi, calendar.monthrange(year, hi)[1])


def bound_undated_sql(sql: str, question: str, latest: str | None) -> str:
    """没写日期、也没要累计时，不让 SQL 把全历史加总。"""
    text = question or ""
    statement = sql or ""
    if not latest or not statement:
        return statement
    if _CUMULATIVE.search(text) or _TIME_WORD.search(text):
        return statement
    if re.search(r"\bRQ\b", statement, re.I):
        return statement
    clause = f"RQ = '{latest}'"
    where = re.search(r"\bWHERE\b", statement, re.I)
    if where:
        return statement[: where.end()] + f" {clause} AND" + statement[where.end():]
    boundary = re.search(r"\bGROUP BY\b|\bORDER BY\b|\bLIMIT\b", statement, re.I)
    if boundary:
        return statement[: boundary.start()] + f" WHERE {clause} " + statement[boundary.start():]
    return statement.rstrip() + f" WHERE {clause}"


def drop_false_absence(text: str, rows: list[list[Any]] | None) -> str:
    """结果里已经有某个月，就去掉「没有这个月」的句子。"""
    blob = " ".join(str(cell) for row in (rows or []) for cell in (row or []))
    present: set[int] = set()
    for match in re.finditer(r"\d{4}-(\d{2})", blob):
        present.add(int(match.group(1)))
    if not present:
        return text
    cn = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十", 11: "十一", 12: "十二"}
    kept: list[str] = []
    for line in (text or "").splitlines():
        if _ABSENCE.search(line):
            claimed = []
            for match in _MONTH_IN_LINE.finditer(line):
                token = match.group(1)
                if token.isdigit():
                    claimed.append(int(token))
                else:
                    for name, number in _CN_MONTHS:
                        if token == name:
                            claimed.append(number)
                            break
            if claimed and any(number in present for number in claimed):
                continue
            # 「仅含十月」而九月也在结果里
            if "仅含" in line and len(present) > 1:
                continue
        kept.append(line)
    return "\n".join(kept).strip()


def refusal_result(question: str, answer: str, reason: str) -> dict[str, Any]:
    return {
        "answer": answer,
        "sql": "",
        "display_sql": "",
        "explanation": reason,
        "columns": [],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "chart": None,
        "analysis_mode": "gate",
        "answer_mode": "L1",
        "standalone_question": question,
        "route": "gate",
        "confidence": "high",
        "gate": reason,
    }


async def load_store_names(source: Any, all_tables: list[dict[str, Any]] | None) -> list[str]:
    from app.core.data_ask.connectors.factory import build_connector_from_source
    from app.core.data_ask.metric_layer import detect_retail_tables

    key = str(getattr(source, "id", "") or "")
    cached = _STORE_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL:
        return list(cached[1])
    _cols_a, _cols_b, names = detect_retail_tables(all_tables)
    table = names.get("a") or names.get("b")
    if not table:
        return []
    conn = build_connector_from_source(source)
    try:
        qr = await conn.execute_select(
            f"SELECT FDMC FROM {table} WHERE FDMC IS NOT NULL GROUP BY FDMC LIMIT 200",
            limit=200,
        )
    finally:
        await conn.close()
    values = [str(row[0]).strip() for row in (qr.rows or []) if row and row[0]]
    _STORE_CACHE[key] = (time.monotonic(), values)
    return values


async def remember_block(data_source_id: str, question: str, reason: str) -> None:
    """拦截进回归集，不进金标。同一问句只记一条。"""
    from sqlalchemy import select

    from app.db.models import AgentEvalSet
    from app.db.session import AsyncSessionLocal

    note = f"gate:{reason}"[:500]
    try:
        async with AsyncSessionLocal() as db:
            found = await db.execute(
                select(AgentEvalSet.id).where(
                    AgentEvalSet.data_source_id == data_source_id,
                    AgentEvalSet.question == question,
                    AgentEvalSet.note.like("gate:%"),
                )
            )
            if found.first():
                return
            db.add(AgentEvalSet(
                data_source_id=data_source_id,
                question=question,
                expected_sql="",
                category="aggregation",
                source="manual",
                difficulty="medium",
                active=True,
                note=note,
            ))
            await db.commit()
    except Exception:
        return


async def apply_answer_gate(
    db: Any,
    source: Any,
    all_tables: list[dict[str, Any]] | None,
    question: str,
    data_source_id: str,
) -> dict[str, Any] | None:
    """命中则直接返回拒答，不再生成 SQL。"""
    del db
    grain = grain_refusal(question)
    if grain:
        await remember_block(data_source_id, question, "grain")
        return refusal_result(question, grain, "grain")
    try:
        names = await load_store_names(source, all_tables)
    except Exception:
        names = []
        if store_mentions(question):
            answer, _hit = store_refusal(question, [])
            if answer:
                await remember_block(data_source_id, question, "store")
                return refusal_result(question, answer, "store")
            return None
    answer, _hit = store_refusal(question, names)
    if answer:
        await remember_block(data_source_id, question, "store")
        return refusal_result(question, answer, "store")
    return None
