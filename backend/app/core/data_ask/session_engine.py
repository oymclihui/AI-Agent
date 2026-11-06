"""会话引擎 v1（蓝图 L2）：Redis 会话状态 + 确定性追问改写 + 建议追问 chips。

- 会话状态：dataask:sess:{user_id}，TTL 默认 30 分钟，复用 redis_cache（降级安全）
- 确定性追问改写：无对话历史时，「那上周呢」+ 状态里的指标 → 「上周销售额是多少」，
  不依赖 LLM；解析不出有效组合返回 None，交还既有链路
- 建议追问：基于本次回答意图的确定性模板（3 个 chips）
"""
from __future__ import annotations

import os
import re
import time
from datetime import date
from typing import Any

from app.core.cache.redis_cache import cache_get_json, cache_set_json
from app.core.data_ask.govern.calendar import previous_window, shift_year_iso
from app.core.data_ask.metric_layer import METRICS, store_phrase_in

SESS_TTL = int(os.getenv("DATAASK_SESS_TTL", "1800"))

_RE_TIME_PHRASE = re.compile(
    r"最近[0-9一二三四五六七八九十两]+[天日周月年]|今天|昨天|前天|"
    r"上个星期|上个月|上周|本周|这周|这星期|本月|这月|上月"
)
# 指代/省略句式：命中才尝试确定性改写
_RE_REFERENTIAL = re.compile(r"^[那么再还又]|呢[？?。!！]?$|换(成|个|一下)|看看?")

# 同义词最长优先（「毛利率」先于「毛利」）
_SYN_SORTED: list[tuple[str, str]] = sorted(
    ((syn, met.name) for met in METRICS.values() for syn in met.synonyms),
    key=lambda x: len(x[0]), reverse=True,
)

# 关联指标（chips 用）
_RELATED = {
    "销售额": "毛利率", "毛利": "毛利率", "销售成本": "毛利率",
    "毛利率": "客单价", "客单价": "销售额",
    "交易笔数": "客单价", "客流营业额": "销售额",
    "门店数": "店均销售额", "日均销售额": "店均销售额", "店均销售额": "日均销售额",
}


def _sess_key(user: Any) -> str:
    uid = getattr(user, "id", None) if user is not None else None
    return f"dataask:sess:{uid or 'anon'}"


async def load_session(user: Any) -> dict[str, Any] | None:
    try:
        val = await cache_get_json(_sess_key(user))
        return val if isinstance(val, dict) else None
    except Exception:
        return None


async def save_session(user: Any, state: dict[str, Any]) -> None:
    try:
        await cache_set_json(_sess_key(user), state, ttl=SESS_TTL)
    except Exception:
        pass


_PHRASES = (
    "最新营业日", "今天", "今日", "昨天", "昨日", "前天",
    "本周", "上周", "本月", "上月", "今年", "去年",
)
_ANN_WINDOW = re.compile(
    r"「(?:本期|今天|今日|昨天|昨日|前天|本周|上周|本月|上月|今年|去年|最新营业日)」"
    r"指\s*(\d{4}-\d{2}-\d{2})(?:\s*至\s*(\d{4}-\d{2}-\d{2}))?"
)


def _phrase_of(text: str) -> str | None:
    head = text.split("（", 1)[0]
    for phrase in _PHRASES:
        if phrase in head or phrase in text:
            return phrase
    match = _RE_TIME_PHRASE.search(text)
    return match.group(0) if match else None


def extract_state(result: dict[str, Any]) -> dict[str, Any]:
    """从问数结果提取会话状态。同期追问要靠窗口和门店，不能只记时间词。"""
    standalone = str(result.get("standalone_question") or "")
    intent = result.get("metric_intent") or {}
    metrics = list(intent.get("metric_names") or [])
    if not metrics:
        for syn, name in _SYN_SORTED:
            if syn in standalone:
                metrics = [name]
                break
    window_time = dict(intent.get("time") or {})
    if not window_time.get("start"):
        match = _ANN_WINDOW.search(standalone)
        if match:
            window_time = {"start": match.group(1), "end": match.group(2) or match.group(1)}
    phrase = _phrase_of(standalone)
    window = None
    if window_time.get("start"):
        window = {
            "start": window_time["start"],
            "end": window_time.get("end") or window_time["start"],
            "phrase": phrase,
        }
    store_phrase = intent.get("store_phrase") or store_phrase_in(standalone)
    return {
        "standalone": standalone,
        "route": result.get("route") or "",
        "metrics": metrics,
        "dimension": intent.get("dimension"),
        "time": window_time,
        "time_phrase": phrase,
        "window": window,
        "filters": {"store_phrase": store_phrase} if store_phrase else {},
        "compare": result.get("compare"),
        "sql": str(result.get("display_sql") or result.get("sql") or "")[:4000],
        "ts": int(time.time()),
    }


_RE_YOY = re.compile(r"同期|同比|去年同期|和去年比|比去年")
_RE_MOM = re.compile(r"环比|比上一期|和上期比")
_RE_LATEST_ASK = re.compile(r"看最新一天|最新营业日|最新一天")


def _span_text(start: str, end: str) -> str:
    return start if start == end else f"{start} 至 {end}"


def resolve_followup(question: str, state: dict[str, Any]) -> str | None:
    """确定性追问改写。只说「同期」时沿用上一句的指标、门店和窗口。"""
    text = str(question or "").strip()
    if not text or not state:
        return None
    metrics = state.get("metrics") or []
    if not metrics:
        return None
    metric_name = str(metrics[0])
    swap = next((name for syn, name in _SYN_SORTED if syn in text), None)
    if swap:
        metric_name = swap
    store = str((state.get("filters") or {}).get("store_phrase") or "")
    window = state.get("window") or {}
    phrase = str(window.get("phrase") or state.get("time_phrase") or "")
    start, end = window.get("start"), window.get("end")

    if _RE_LATEST_ASK.search(text) and len(text) <= 16:
        return f"最新营业日{store}{metric_name}是多少"
    if _RE_YOY.search(text) or _RE_MOM.search(text):
        if start and end and _RE_YOY.search(text):
            current = _span_text(str(start), str(end))
            previous = _span_text(shift_year_iso(str(start)), shift_year_iso(str(end)))
            return (
                f"{phrase}{store}{metric_name}，对比去年同期"
                f"（其中「本期」指 {current}，「同期」指 {previous}）"
            )
        if start and end and _RE_MOM.search(text):
            prev_start, prev_end = previous_window(date.fromisoformat(str(start)), date.fromisoformat(str(end)))
            current = _span_text(str(start), str(end))
            previous = _span_text(prev_start.isoformat(), prev_end.isoformat())
            return (
                f"{phrase}{store}{metric_name}，对比上一期"
                f"（其中「本期」指 {current}，「上期」指 {previous}）"
            )
        if phrase:
            tag = "对比去年同期" if _RE_YOY.search(text) else "对比上一期"
            return f"{phrase}{store}{metric_name}，{tag}"
        return None

    if not _RE_REFERENTIAL.search(text):
        return None

    dim_kind = None
    if re.search(r"每天|每日|按天|按日|走势|趋势", text):
        dim_kind = "day"
    elif re.search(r"按门店|各门店|哪个门店|门店排名|分店", text):
        dim_kind = "store"

    time_match = _RE_TIME_PHRASE.search(text)
    time_word = time_match.group(0) if time_match else None

    if dim_kind == "day":
        return f"{time_word or '最近7天'}每天{store}{metric_name}走势"
    if dim_kind == "store":
        return f"{time_word or phrase or '今天'}各门店{metric_name}"
    if time_word:
        return f"{time_word}{store}{metric_name}是多少"
    if swap:
        return f"{phrase or '今天'}{store}{metric_name}是多少"
    return None


def build_suggestions(state: dict[str, Any]) -> list[str]:
    """3 个建议追问 chips（确定性模板，无 LLM）。"""
    metrics = state.get("metrics") or []
    dim = state.get("dimension")
    t = state.get("time") or {}
    single = bool(t.get("start")) and t.get("start") == t.get("end")
    chips: list[str] = []
    if metrics and (state.get("window") or state.get("time_phrase")) and not state.get("compare"):
        chips.append("同期")
    if metrics:
        m = str(metrics[0])
        related = _RELATED.get(m)
        if single:
            chips.append(f"上周{m}是多少")
            if dim != "day":
                chips.append(f"最近7天每天{m}走势")
            if related:
                chips.append(f"昨天{related}是多少")
        else:
            chips.append(f"昨天{m}是多少")
            if related:
                chips.append(f"上周{related}是多少")
            if dim is None:
                chips.append(f"各门店{m}")
    if len(chips) < 3:
        for fb in ("最近7天每天销售额走势", "今天毛利率是多少", "各门店销售额"):
            if fb not in chips:
                chips.append(fb)
    out: list[str] = []
    for c in chips:
        if c and c not in out:
            out.append(c)
    return out[:3]
