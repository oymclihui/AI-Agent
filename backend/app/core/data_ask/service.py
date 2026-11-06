"""End-to-end data ask query pipeline."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.permissions import resolve_data_scope
from app.core.data_ask.connectors.factory import build_connector_from_source
from app.core.data_ask.govern.access import bypass_row_permission
from app.core.data_ask.govern.audit import log_query
from app.core.data_ask.govern.column_policy import validate_sql_columns
from app.core.data_ask.govern.permission import (
    build_permission_scope_sql,
    inject_permission_filter,
    permission_config_from_rules,
    resolve_permission_columns,
)
from app.core.data_ask.govern.sql_guard import disambiguate_subquery_columns, validate_select_sql
from app.core.data_ask.govern.fanout import FANOUT_HINT, detect_fanout, rewrite_fanout
from app.core.data_ask.govern.answer_gate import (
    apply_answer_gate,
    bound_undated_sql,
    grain_refusal,
    store_mentions,
)
from app.core.data_ask.govern.calendar import (
    business_today,
    is_context_followup,
    previous_window,
    question_cache_key_text,
    shift_year_iso,
)
from app.core.data_ask.govern.date_scope import annotated_window, fix_single_day_sql, latest_biz_note
from app.core.cache.redis_cache import (
    cache_get_json,
    cache_set_json,
    make_dataask_cache_key,
)
from app.core.data_ask.analysis.python_runner import run_python_analysis, validate_python_code
from app.core.data_ask.excel.session_cache import (
    build_provenance,
    ensure_ready,
    get_all_frames,
    get_all_tables,
)
from app.core.data_ask.excel.retention import release_ephemeral_excel_workspace
from app.core.data_ask.intelligence.nlpython import analyze_python_results, generate_python, repair_python
from app.core.data_ask.intelligence.intent import is_forecast_question, rewrite_question
from app.core.data_ask.metric_layer import plan_period_compare, try_metric_route
from app.core.data_ask.intelligence.answer_mode import (
    MODE_ANALYSIS,
    classify_answer_mode,
    keywords_from_semantic,
)
from app.core.data_ask.intelligence.nl2sql import analyze_results, generate_sql, generate_sql_candidates, repair_sql
from app.core.data_ask.skills_router import match_analysis_skill, skill_used_brief
from app.core.data_ask.analysis.orchestrator import run_skill_orchestration
from app.core.data_ask.intelligence.query_memory import retrieve_similar_queries
from app.core.data_ask.intelligence.schema_retriever import rank_tables
from app.core.data_ask.intelligence.value_link import enrich_tables
from app.core.data_ask.intelligence.candidates import hint_hits, question_needs_variants, rank_probes
from app.core.data_ask.experience.chart_profile import suggest_chart
from app.core.data_ask.experience.overview import is_overview_question, run_overview_analysis
from app.core.data_ask.schema.introspect import infer_join_graph, introspect_tables
from app.core.data_ask.semantic.mdl import expand_metric_sql, metric_gaps
from app.core.data_ask.semantic.loader import enrich_table_meta_with_profile, load_ds_semantic
from app.db.models import DataSource, DataSourceTable, DataSourceTableRole, User

MAX_SQL_RETRIES = 2
MAX_PYTHON_RETRIES = 2
SCHEMA_TOP_K = 5

_RE_REL_WINDOW = re.compile(r"(?:最近|近|过去)\s*([0-9一二三四五六七八九十两]+)\s*(天|日|周|月|年)")
_RE_REL_DAY = {"今天": 0, "昨天": 1, "前天": 2}
# 会话引擎 v1：周/月级相对时间（锚定数据最新日期）
_RE_REL_WEEKMONTH = re.compile(r"上个星期|上个月|上周|本周|这周|这星期|本月|这月|上月")
_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _count_of(token: str) -> int | None:
    """把「3」「三」「十二」「二十」等数量词解析为整数；无法解析返回 None。"""
    if token.isdigit():
        return int(token)
    if "十" in token:
        left, _, right = token.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    return _CN_DIGITS.get(token)


_RE_CN_YMD_EX = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
_RE_CN_MD_EX = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
_RE_DATE_STR = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")

# 日期列识别：类型是 date/time，或列名本身是日期语义。
# 有些库把日期存成 varchar（如 SR_CS_KL.RQ），只按类型判断会漏掉整类数据源。
_DATE_COL_NAMES = ("RQ", "DATE", "DT", "DAY", "BIZ_DATE")
_DATE_COL_KEYS = ("日期", "时间")


async def _latest_biz_date(source: DataSource, all_tables: list[dict[str, Any]] | None):
    """取数据源中首个日期列的最新日期；取不到返回 None。

    同时支持 date 类型与 varchar 存日期字符串的列，避免新数据源因列类型
    不规范导致「显式日期无年份锚定」，进而让 LLM 编造年份。
    """
    from datetime import date as _date

    for table in all_tables or []:
        for column in table.get("columns") or []:
            name = str(column.get("name") if isinstance(column, dict) else column)
            col_type = str(column.get("type") if isinstance(column, dict) else "").lower()
            is_typed = any(token in col_type for token in ("date", "time"))
            is_named = name.upper() in _DATE_COL_NAMES or any(k in name for k in _DATE_COL_KEYS)
            if not (is_typed or is_named):
                continue
            try:
                conn = build_connector_from_source(source)
                try:
                    qr = await conn.execute_select(
                        f"SELECT MAX({name}) FROM {table.get('table_name')}", limit=1,
                    )
                finally:
                    await conn.close()
                raw = str(qr.rows[0][0]) if qr.rows and qr.rows[0][0] is not None else ""
                m = _RE_DATE_STR.match(raw)
                if not m:
                    continue
                return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except Exception:
                continue
    return None


async def _resolve_explicit_dates(
    source: DataSource,
    all_tables: list[dict[str, Any]] | None,
    question: str,
) -> str:
    """把显式中文日期（2026年10月7日 / 10月7日）规范为 ISO 并追加标注。

    LLM 路径没有日期锚定，会把「2026年10月6日」照抄成样例数据里的日期
    （实测出现 2025-01-11）。规范为 ISO + 标注后，指标层与 LLM 都拿到确定日期。
    """
    from datetime import date as _date

    text = (question or "").strip()
    if not text:
        return question
    if "其中「" in text:  # 已由 _resolve_relative_time 标注，避免重复处理
        return question

    def _fmt(y: int, m: int, d: int) -> str | None:
        try:
            return _date(y, m, d).isoformat()
        except Exception:
            return None

    hits: list[tuple[str, str]] = []
    out = text
    latest = await _latest_biz_date(source, all_tables)
    for mm in _RE_CN_YMD_EX.finditer(text):
        iso = _fmt(int(mm.group(1)), int(mm.group(2)), int(mm.group(3)))
        if iso:
            hits.append((mm.group(0), iso))

    if hits:
        for phrase, iso in hits:
            out = out.replace(phrase, iso, 1)
    else:
        mds = list(_RE_CN_MD_EX.finditer(text))
        if not mds or latest is None:
            return question
        for mm in mds:
            iso = _fmt(latest.year, int(mm.group(1)), int(mm.group(2)))
            if iso:
                hits.append((mm.group(0), iso))
        for phrase, iso in hits:
            out = out.replace(phrase, iso, 1)

    if not hits:
        return question
    ann = "、".join(f"「{phrase}」指 {iso}" for phrase, iso in hits)
    tail = f"，数据最新日期为 {latest.isoformat()}" if latest else ""
    return f"{out}（其中{ann}{tail}）"


def _business_columns(all_tables: list[dict[str, Any]] | None) -> set[str]:
    """业务表列名集合（UPPER），用于校验行级权限的数据列是否真实存在。"""
    names: set[str] = set()
    for table in all_tables or []:
        for column in table.get("columns") or []:
            raw = column.get("name") if isinstance(column, dict) else column
            if raw:
                names.add(str(raw).upper())
    return names


_RE_REL_DAY_ORDER = (
    ("今天", 0), ("今日", 0), ("当天", 0),
    ("昨天", 1), ("昨日", 1),
    ("前天", 2),
)


async def _resolve_relative_time(
    source: DataSource,
    all_tables: list[dict[str, Any]] | None,
    question: str,
) -> str:
    """把「今天 / 本月 / 最近 N 天」写成日历窗口。今天是 Asia/Shanghai 的当天，不是 MAX(RQ)。"""
    from datetime import date, timedelta
    from calendar import monthrange

    text = (question or "").strip()
    if not text or "其中「" in text:
        return question
    if any(token in text for token in ("最新营业日", "最新一天", "看最新")):
        latest = await _latest_biz_date(source, all_tables)
        if latest is None:
            return question
        return f"{text}（其中「最新营业日」指 {latest.isoformat()}，业务时区 Asia/Shanghai）"

    window = _RE_REL_WINDOW.search(text)
    day_hit = next(((word, off) for word, off in _RE_REL_DAY_ORDER if word in text), None)
    weekmonth = _RE_REL_WEEKMONTH.search(text)
    year_phrase = None
    if "今年" in text:
        year_phrase = "今年"
    elif "去年" in text and "同期" not in text:
        year_phrase = "去年"
    if not window and day_hit is None and not weekmonth and year_phrase is None:
        return question

    today = business_today()
    latest = await _latest_biz_date(source, all_tables)
    start = end = today
    phrase = ""
    if day_hit:
        phrase, offset = day_hit
        start = end = today - timedelta(days=offset)
    elif weekmonth:
        phrase = weekmonth.group(0)
        monday = today - timedelta(days=today.weekday())
        if "月" in phrase:
            if phrase.startswith("上"):
                total = today.year * 12 + (today.month - 1) - 1
                year, month = divmod(total, 12)
                start = date(year, month + 1, 1)
                end = date(year, month + 1, monthrange(year, month + 1)[1])
            else:
                start = date(today.year, today.month, 1)
                end = today
        elif phrase.startswith("上"):
            start = monday - timedelta(days=7)
            end = start + timedelta(days=6)
        else:
            start = monday
            end = today
    elif window:
        count = _count_of(window.group(1))
        unit = window.group(2)
        if not count or count <= 0:
            return question
        if unit in ("天", "日"):
            start = today - timedelta(days=count - 1)
        elif unit == "周":
            start = today - timedelta(days=count * 7 - 1)
        elif unit == "月":
            total = today.year * 12 + (today.month - 1) - count
            year, month = divmod(total, 12)
            start = date(year, month + 1, 1)
        else:
            start = date(today.year - count, today.month, 1)
        end = today
        phrase = window.group(0)
    elif year_phrase == "今年":
        phrase = "今年"
        start = date(today.year, 1, 1)
        end = today
    else:
        phrase = "去年"
        start = date(today.year - 1, 1, 1)
        end = date(today.year - 1, 12, 31)

    resolved = end.isoformat() if start == end else f"{start.isoformat()} 至 {end.isoformat()}"
    extra = ""
    if re.search(r"同期|同比|和去年比|比去年", text):
        y_start, y_end = shift_year_iso(start.isoformat()), shift_year_iso(end.isoformat())
        extra = f"，「同期」指 {y_start}" + ("" if y_start == y_end else f" 至 {y_end}")
    elif re.search(r"环比|比上一期", text):
        p_start, p_end = previous_window(start, end)
        extra = f"，「上期」指 {p_start.isoformat()}" + ("" if p_start == p_end else f" 至 {p_end.isoformat()}")
    latest_note = f"，最新营业日为 {latest.isoformat()}" if latest else ""
    return f"{text}（其中「{phrase}」指 {resolved}{extra}，业务时区 Asia/Shanghai{latest_note}）"


def _edge_pairs(edge: dict[str, Any]) -> list[tuple[str, str]]:
    """还原一条边上的「本端列 → 对端列」字段对；兼容旧的单列 on。"""
    pairs = [
        (str(p.get("from") or ""), str(p.get("to") or ""))
        for p in (edge.get("pairs") or [])
        if isinstance(p, dict)
    ]
    pairs = [(a, b) for a, b in pairs if a and b]
    if pairs:
        return pairs
    on = str(edge.get("on") or "")
    return [(on, on)] if on else []


def user_join_edges_from_tables(tables: list[Any]) -> list[dict[str, Any]]:
    """从已注册数据表的 join_keys 还原用户自定义的关联边。

    join_keys 结构：{"edges": [{"to": 对端表, "on": "本端列", "pairs": [{"from": 本端列, "to": 对端列}]}]}
    （单表视角、双向存储；pairs 支持 RQ+FDBH 这类复合键）。
    还原时合并双向记录，输出与 infer_join_graph 一致的 edge 结构，
    并标记 kind="user" 以示区别。若用户未定义任何关系返回空列表。
    """
    edges: list[dict[str, Any]] = []
    jk_by_name: dict[str, dict[str, Any]] = {}
    for t in tables:
        role = getattr(t, "role", None)
        role_val = role.value if hasattr(role, "value") else role
        if role_val != "data":
            continue
        name = str(getattr(t, "table_name", "") or "")
        if name:
            jk_by_name[name] = getattr(t, "join_keys", None) or {}
    for src, jk in jk_by_name.items():
        for edge in (jk.get("edges") or []):
            dst = str(edge.get("to") or "")
            if not dst or dst not in jk_by_name:
                continue
            if src >= dst:
                continue
            pairs = _edge_pairs(edge)
            if not pairs:
                # 只有对端表存了关系时，从反向记录还原
                for de in ((jk_by_name.get(dst) or {}).get("edges") or []):
                    if str(de.get("to") or "") == src:
                        pairs = [(b, a) for a, b in _edge_pairs(de)]
                        break
            if not pairs:
                continue
            edges.append({
                "from": src,
                "to": dst,
                "label": ",".join(a for a, _ in pairs),
                "from_column": pairs[0][0],
                "to_column": pairs[0][1],
                "pairs": [
                    {"from_column": a, "to_column": b} for a, b in pairs
                ],
                "kind": "user",
            })
    return edges


async def load_source_context(
    db: AsyncSession,
    data_source_id: str,
) -> tuple[DataSource, list[dict[str, Any]], dict[str, Any] | None, str | None, list[dict[str, str]]]:
    source = await db.get(DataSource, data_source_id)
    if not source:
        raise ValueError("Data source not found")
    result = await db.execute(
        select(DataSourceTable).where(DataSourceTable.data_source_id == data_source_id)
    )
    reg_tables = list(result.scalars().all())
    data_tables = [t for t in reg_tables if t.role == DataSourceTableRole.data]
    perm_table = next((t for t in reg_tables if t.role == DataSourceTableRole.permission), None)
    table_meta: list[dict[str, Any]] = []
    for t in data_tables:
        cols = (t.column_meta or {}).get("columns") or []
        if isinstance(t.column_meta, list):
            cols = t.column_meta
        table_meta.append(
            {
                "table_name": t.table_name,
                "columns": cols,
                "partition_columns": (t.column_meta or {}).get("partition_columns") or [],
                "sample_rows": t.sample_rows or [],
                "join_keys": t.join_keys or {},
            }
        )
    if not table_meta and data_tables:
        table_meta = await introspect_tables(source, [t.table_name for t in data_tables])
    table_meta = enrich_tables(table_meta)
    user_edges = user_join_edges_from_tables(data_tables)
    if user_edges:
        join_graph_edges = user_edges
    else:
        join_graph = infer_join_graph(
            [
                {
                    "table_name": m["table_name"],
                    "columns": m.get("columns") or [],
                }
                for m in table_meta
            ]
        )
        join_graph_edges = join_graph.get("edges") or []
    perm_name = perm_table.table_name if perm_table else None
    return source, table_meta, source.semantic_model, perm_name, join_graph_edges


_CACHE_REF_WORDS = ("它", "这个", "那个", "刚才", "上面", "再", "呢", "那他", "那她")


def _cacheable_question(question: str) -> bool:
    """只缓存独立完整问句；带指代的追问依赖上下文，缓存会串答。"""
    text = " ".join(str(question or "").split())
    if is_context_followup(text):
        return False
    return len(text) >= 6 and not any(w in text for w in _CACHE_REF_WORDS)


def _route_confidence(route_mode: str) -> str:
    """置信度分级（蓝图 L1）：确定性路由=high，LLM 生成+校验=medium。"""
    return "high" if route_mode in ("override", "memory_reuse", "metric", "compare") else "medium"


def _user_key(user: User | None) -> str:
    if not user:
        return "anonymous"
    key = str(user.employee_no or user.id)
    if not re.match(r"^[\w\-.@]+$", key):
        raise ValueError("Invalid user identity for permission filter")
    return key


async def _resolve_llm(
    db: AsyncSession,
    source: DataSource,
    llm_provider: str | None,
    llm_model: str | None,
    spec_override: dict[str, Any] | None = None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """解析问数 LLM 配置；spec_override 非空时优先采用候选版本 spec（评估专用，
    不改动线上 Agent 记录——P0-A 双候选评测的基础）。"""
    agent_provider = llm_provider
    agent_model = llm_model
    agent_goal = None
    agent_backstory = None
    if source.agent_id:
        from app.db.models import Agent as AgentModel

        agent = await db.get(AgentModel, source.agent_id)
        if agent:
            agent_provider = agent_provider or agent.llm_provider
            agent_model = agent_model or agent.llm_model
            agent_goal = (agent.goal or "").strip() or None
            agent_backstory = (agent.backstory or "").strip() or None
    if spec_override:
        agent_provider = spec_override.get("llm_provider") or agent_provider
        agent_model = spec_override.get("llm_model") or agent_model
        agent_goal = (spec_override.get("goal") or "").strip() or agent_goal
        agent_backstory = (spec_override.get("backstory") or "").strip() or agent_backstory
    return agent_provider, agent_model, agent_goal, agent_backstory


async def _gather_memory_examples(
    db: AsyncSession, *, data_source_id: str, question: str, top_k: int = 3,
    min_score: float | None = None,
    strong_score: float | None = None,
    skill_id: str | None = None,
) -> list[dict[str, Any]]:
    """问数记忆：技能专属示例优先，再合并金标与蒸馏示例库。"""
    try:
        from app.core.data_ask.distill.example_store import gather_memory_examples as _gather

        return await _gather(
            db, data_source_id=data_source_id, question=question, top_k=top_k,
            min_score=min_score, strong_score=strong_score, skill_id=skill_id,
        )
    except Exception:
        from app.core.data_ask.intelligence.query_memory import retrieve_similar_queries

        kwargs: dict[str, Any] = {}
        if min_score is not None:
            kwargs["min_score"] = float(min_score)
        return await retrieve_similar_queries(
            db, data_source_id=data_source_id, question=question, top_k=top_k, **kwargs
        )


def _compact_question(text: str) -> str:
    """同问判定用的归一化：去掉空白、标点与大小写差异。"""
    return re.sub(r"[\s，。！？、；：,.!?;:“”\"'（）()]+", "", (text or "").lower())


# P0-C 策略 knobs 硬默认（线上现行行为）：网格扫（replay/knob-sweep）选出的操作点
# 固化到 source.metadata_.policy_knobs 后覆盖；spec_override 仅评估路径注入。

_DEFAULT_POLICY_KNOBS: dict[str, Any] = {
    "memory_min_score": 0.35,
    "memory_top_k": 3,
    "memory_strong_score": 0.85,
    "clarify_metric_min": 2,
    "clarify_vague_time_enabled": True,
    "clarify_relative_time_exempt": True,
}


def _resolve_policy_knobs(
    source: DataSource, spec_override: dict[str, Any] | None
) -> dict[str, Any]:
    """P0-C 记忆先验分档：读取顺序 spec_override > source.metadata_.policy_knobs > 硬默认。"""
    knobs = dict(_DEFAULT_POLICY_KNOBS)
    meta = getattr(source, "metadata_", None) or {}
    stored = meta.get("policy_knobs") if isinstance(meta, dict) else None
    if isinstance(stored, dict):
        knobs.update({k: v for k, v in stored.items() if k in knobs})
    if spec_override:
        knobs.update({k: v for k, v in spec_override.items() if k in knobs})
    try:
        knobs["memory_min_score"] = float(knobs["memory_min_score"])
        knobs["memory_strong_score"] = float(knobs["memory_strong_score"])
    except (TypeError, ValueError):
        knobs["memory_min_score"] = _DEFAULT_POLICY_KNOBS["memory_min_score"]
        knobs["memory_strong_score"] = _DEFAULT_POLICY_KNOBS["memory_strong_score"]
    try:
        knobs["memory_top_k"] = max(1, int(knobs["memory_top_k"]))
        knobs["clarify_metric_min"] = max(1, int(knobs["clarify_metric_min"]))
    except (TypeError, ValueError):
        knobs["memory_top_k"] = _DEFAULT_POLICY_KNOBS["memory_top_k"]
        knobs["clarify_metric_min"] = _DEFAULT_POLICY_KNOBS["clarify_metric_min"]
    knobs["clarify_vague_time_enabled"] = bool(knobs["clarify_vague_time_enabled"])
    knobs["clarify_relative_time_exempt"] = bool(knobs["clarify_relative_time_exempt"])
    return knobs


def _is_direct_calendar_ask(question: str, standalone: str) -> bool:
    """直问今天/同期时走日历取数，不让技能步骤把窗口改成 $本月 或 $最新日。"""
    raw = question or ""
    if any(word in raw for word in ("分析", "为什么", "原因", "趋势", "报告", "怎么看")):
        if not any(word in raw for word in ("同期", "同比", "环比")):
            return False
    blob = f"{raw}\n{standalone or ''}"
    keys = (
        "今天", "今日", "昨天", "昨日", "前天", "本周", "这周", "上周", "本月", "上月",
        "今年", "去年", "同期", "同比", "环比", "最新营业日", "最新一天",
    )
    return any(key in blob for key in keys)


def _scalar_cell(rows: list[Any] | None) -> Any:
    if not rows or not rows[0]:
        return None
    value = rows[0][0]
    return None if value is None else value


def _fmt_num(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _no_data_answer(question: str, metric_intent: dict[str, Any]) -> str:
    names = "、".join(metric_intent.get("metric_names") or []) or "该指标"
    window = metric_intent.get("time") or {}
    start, end = window.get("start"), window.get("end") or window.get("start")
    latest = latest_biz_note(question)
    if ("「今天」" in (question or "") or "「今日」" in (question or "")) and start and start == end:
        tail = f"库里最新营业日是 {latest}。" if latest else ""
        return f"今天（{start}）还没有{names}数据。{tail}要看这一天可以说「看最新一天」。"
    desc = start if start == end else f"{start} 至 {end}"
    return f"{names}暂无数据（{desc} 无记录，可能数据尚未同步）。"


_MEASURE_NAME = re.compile(r"额|利|价|率|量|笔|成本|销售|毛利|客单|营业")
_DATE_COL_NAME = re.compile(r"日期|时间|月份|年份|季度|\bRQ\b", re.I)
_ISO_IN_CELL = re.compile(r"\d{4}-\d{2}-\d{2}")
_RQ_EQ = re.compile(r"RQ\s*=\s*'(\d{4}-\d{2}-\d{2})'", re.I)
_RQ_BETWEEN = re.compile(
    r"RQ\s+BETWEEN\s+'(\d{4}-\d{2}-\d{2})'\s+AND\s+'(\d{4}-\d{2}-\d{2})'",
    re.I,
)


def _cumulative_answer(columns: list[Any], rows: list[Any]) -> str:
    """历史累计用销售表全量，数字按千分位写出，避免模型改口径。"""
    if not rows:
        return "历史累计暂无数据。"
    parts: list[str] = []
    for name, value in zip(columns, rows[0]):
        shown = _fmt_num(value)
        if shown is None:
            continue
        label = str(name)
        unit = "%" if "率" in label else "元"
        parts.append(f"{label} {shown} {unit}")
    body = "，".join(parts) if parts else "暂无数据"
    if "历史累计" in body:
        return body + "。"
    return f"历史累计 {body}。"


def _window_label(question: str, metric_intent: dict[str, Any] | None, sql: str) -> str | None:
    """结果对应的查询窗口。单日就是这一天，区间写成起止。"""
    window = (metric_intent or {}).get("time") or {}
    if window.get("origin") == "cumulative":
        return "历史累计"
    start = window.get("start")
    end = window.get("end") or start
    if not start:
        annotated = annotated_window(question or "")
        if annotated:
            start, end = annotated
    if not start and sql:
        between = _RQ_BETWEEN.search(sql)
        if between:
            start, end = between.group(1), between.group(2)
        else:
            days = list(dict.fromkeys(_RQ_EQ.findall(sql)))
            if len(days) == 1:
                start = end = days[0]
    if not start:
        return None
    return str(start) if start == end else f"{start} 至 {end}"


def _stamp_measure_columns(columns: list[Any], rows: list[Any], label: str) -> list[str]:
    """把日期写进指标列标题。按天展开、或一行一个日期时不再改列名。"""
    names = [str(col) for col in (columns or [])]
    if not label:
        return names
    found: set[str] = set()
    for row in rows or []:
        for cell in row or []:
            found.update(_ISO_IN_CELL.findall(str(cell or "")))
    if len(found) > 1 or any(_DATE_COL_NAME.search(name) for name in names):
        return names
    stamped: list[str] = []
    changed = False
    for name in names:
        if label in name or _DATE_COL_NAME.search(name):
            stamped.append(name)
        elif _MEASURE_NAME.search(name):
            stamped.append(f"{name}（{label}）")
            changed = True
        else:
            stamped.append(name)
    if not changed and len(names) == 1 and label not in names[0]:
        return [f"{names[0]}（{label}）"]
    return stamped


def _stamp_markdown_headers(text: str, label: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        if index + 1 >= len(lines) or "---" not in lines[index + 1]:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        updated: list[str] = []
        changed = False
        for cell in cells:
            if _MEASURE_NAME.search(cell) and label not in cell and not _ISO_IN_CELL.search(cell):
                updated.append(f"{cell}（{label}）")
                changed = True
            else:
                updated.append(cell)
        if changed:
            lines[index] = "| " + " | ".join(updated) + " |"
        break
    return "\n".join(lines)


def _ensure_date_visible(answer: str, label: str | None, mode: str) -> str:
    text = str(answer or "")
    if not label or label in text:
        return text
    if mode in ("L2", "L3"):
        stamped = _stamp_markdown_headers(text, label)
        if label in stamped:
            return stamped
        return f"**{label}**\n\n{text}"
    return f"{label} {text}".strip()


def _coverage_note(question: str, *, has_data: bool) -> str:
    if not has_data or "「同期」" in (question or "") or "「上期」" in (question or ""):
        return ""
    window = annotated_window(question)
    latest = latest_biz_note(question)
    if not window or not latest:
        return ""
    _start, end = window
    if latest < end and latest >= _start:
        return f"数据覆盖到 {latest}。"
    return ""


def _compare_answer(plan: dict[str, Any], current: Any, previous: Any) -> str:
    name = str(plan.get("metric_name") or "该指标")
    unit = str(plan.get("unit") or "")
    unit_text = unit if unit and unit != "元" else ("元" if unit == "元" else "")
    phrase = str(plan.get("phrase") or "")
    store = str(plan.get("store_phrase") or "")
    current_label = str(plan.get("current_label") or "")
    previous_label = str(plan.get("previous_label") or "")
    head = f"{phrase}（{current_label}）" if phrase else f"本期（{current_label}）"
    if store:
        head = f"{store}{head}"
    if current is None:
        other_name = "去年同期" if plan.get("kind") == "yoy" else "上一期"
        if previous is None:
            if phrase in ("今天", "今日"):
                latest = plan.get("latest")
                tail = f"库里最新营业日是 {latest}。" if latest else ""
                return (
                    f"今天（{current_label}）还没有{name}数据。{tail}"
                    f"{other_name}（{previous_label}）也没有数据，不算增幅。"
                )
            return f"{head}{name}暂无数据。{other_name}（{previous_label}）也没有数据，不算增幅。"
        return (
            f"{head}{name}无数据。{other_name}（{previous_label}）{name} {_fmt_num(previous)}{unit_text}。"
            "本期无数据，不算增幅。"
        )
    current_text = _fmt_num(current)
    other = "去年同期" if plan.get("kind") == "yoy" else "上一期"
    line = f"{head}{name} {current_text}{unit_text}。{other}（{previous_label}）{name} "
    if previous is None:
        line += "无数据，不算增幅。"
    else:
        previous_text = _fmt_num(previous)
        try:
            current_num, previous_num = float(current), float(previous)
        except (TypeError, ValueError):
            line += f"{previous_text}{unit_text}。"
        else:
            if previous_num == 0:
                line += f"{previous_text}{unit_text}。对比期为 0，不算增幅。"
            else:
                delta = current_num - previous_num
                line += (
                    f"{previous_text}{unit_text}，差额 {_fmt_num(delta)}{unit_text}，"
                    f"增幅 {delta / previous_num * 100:.2f}%。"
                )
    latest = plan.get("latest")
    window = plan.get("current") or ("", "")
    if current is not None and latest and window[0] <= str(latest) < window[1]:
        line += f"数据覆盖到 {latest}。"
    return line


async def _execute_period_compare(
    db: AsyncSession,
    *,
    source: DataSource,
    user: User | None,
    question: str,
    standalone: str,
    plan: dict[str, Any],
    apply_perm: bool,
    perm_table: str | None,
    perm_rules: dict[str, str],
) -> dict[str, Any]:
    current_sql = str(plan["current_sql"])
    previous_sql = str(plan["previous_sql"])
    current_exec = _wrap_permission(current_sql, apply_perm, perm_table, perm_rules, user, source)
    previous_exec = _wrap_permission(previous_sql, apply_perm, perm_table, perm_rules, user, source)
    conn = build_connector_from_source(source)
    try:
        current_qr = await conn.execute_select(current_exec)
        previous_qr = await conn.execute_select(previous_exec)
    finally:
        await conn.close()
    current_value = _scalar_cell(current_qr.rows)
    previous_value = _scalar_cell(previous_qr.rows)
    analysis = _compare_answer(plan, current_value, previous_value)
    label = "同期" if plan.get("kind") == "yoy" else "上期"
    columns = ["口径", str(plan.get("metric_name") or "数值")]
    rows = [
        [f"本期 {plan.get('current_label')}", current_value],
        [f"{label} {plan.get('previous_label')}", previous_value],
    ]
    display_sql = current_sql + ";\n" + previous_sql
    exec_sql = current_exec + ";\n" + previous_exec
    shown = str(plan.get("explanation") or "")
    if standalone != question:
        shown = f"追问理解为：{standalone}\n{shown}"
    await log_query(
        db,
        user_id=user.id if user else None,
        data_source_id=str(source.id),
        question=question,
        sql_text=exec_sql,
        row_count=2,
        success=True,
    )
    return {
        "answer": analysis,
        "sql": exec_sql,
        "display_sql": display_sql,
        "explanation": shown,
        "columns": columns,
        "rows": rows,
        "row_count": 2,
        "truncated": False,
        "chart": None,
        "analysis_mode": "sql",
        "answer_mode": "L1",
        "standalone_question": standalone,
        "route": "compare",
        "confidence": "high",
        "metric_intent": plan.get("metric_intent"),
        "compare": {
            "kind": plan.get("kind"),
            "start": (plan.get("previous") or ("", ""))[0],
            "end": (plan.get("previous") or ("", ""))[1],
        },
    }


async def _run_data_ask_impl(
    db: AsyncSession,
    *,
    data_source_id: str,
    question: str,
    user: User | None,
    sql_override: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    execute: bool = True,
    history: list[dict[str, Any]] | None = None,
    stage_queue: asyncio.Queue | None = None,
    trace_marks: dict[str, int] | None = None,
    bypass_row_perm: bool = False,
    use_memory: bool = True,
    spec_override: dict[str, Any] | None = None,
    force_answer_mode: str | None = None,
    employee_id: str | None = None,
    skill_id: str | None = None,
) -> dict[str, Any]:
    _t_start = time.monotonic()
    source = await db.get(DataSource, data_source_id)
    if not source:
        raise ValueError("Data source not found")
    agent_provider, agent_model, agent_goal, agent_backstory = await _resolve_llm(
        db, source, llm_provider, llm_model, spec_override=spec_override,
    )
    # 蓝图 P0：分析技能路由——数字员工绑定的分析技能命中后，结论人设/排版/口径可被技能覆盖。
    # 只影响结论层（analyze_results / analyze_python_results 的提示词），不碰 SQL 生成与治理链；
    # 未命中/异常一律 skill_ctx=None，走原硬编码逻辑（零风险兜底）。
    skill_ctx = None
    if employee_id or skill_id:
        try:
            skill_ctx = await match_analysis_skill(
                db, question=question, employee_id=employee_id, skill_id=skill_id,
                data_source_id=data_source_id,
            )
        except Exception:
            skill_ctx = None
    # 蓝图 P1 末：批评意见只生成草案；「发布 / 回滚 / 对比」才动版本。不是这类话则继续问数。
    dialogue_act = False
    try:
        from app.core.chat.reflector import is_dialogue_act
        from app.core.chat.skill_dialogue import handle_skill_dialogue

        dialogue_act = is_dialogue_act(question)
        if dialogue_act:
            dialogue = await handle_skill_dialogue(
                db, source=source, question=question, user=user,
                employee_id=employee_id, skill_id=skill_id, skill_ctx=skill_ctx,
            )
            if dialogue:
                if skill_ctx:
                    dialogue["skill_used"] = skill_used_brief(skill_ctx)
                return dialogue
    except Exception:
        logging.getLogger("data_ask").warning("skill_dialogue_failed", exc_info=True)
        if dialogue_act:
            return {
                "answer": "这句修改没有完成，技能未改动。请换个说法，或稍后再说「发布」。",
                "sql": "", "display_sql": "", "explanation": "",
                "columns": [], "rows": [], "row_count": 0, "truncated": False,
                "chart": None, "analysis_mode": "skill_revision", "answer_mode": "L1",
                "standalone_question": question,
            }
    # P1-A 预算轴：评估专用 SQL 修复重试上限（仅 spec_override 注入，线上默认为 None=MAX_SQL_RETRIES）
    max_sql_retries: int | None = None
    if spec_override and spec_override.get("max_sql_retries") is not None:
        try:
            max_sql_retries = max(0, int(spec_override["max_sql_retries"]))
        except (TypeError, ValueError):
            max_sql_retries = None
    # P0-C 记忆先验分档 knobs：spec_override（评估注入）> source.metadata_.policy_knobs（固化操作点）> 硬默认
    knobs = _resolve_policy_knobs(source, spec_override)
    standalone = question
    if not sql_override:
        # 同期 / 环比 / 那上周呢：先用会话状态补全。补全成功就不再交给模型重猜日期。
        try:
            from app.core.data_ask.session_engine import load_session, resolve_followup
            _sess = await load_session(user)
            if _sess:
                _fq = resolve_followup(question, _sess)
                if _fq:
                    standalone = _fq
        except Exception:
            pass
    if history and not sql_override and standalone == question:
        try:
            standalone = await rewrite_question(
                db,
                question=question,
                history=history,
                llm_provider=agent_provider,
                llm_model=agent_model,
                user_id=user.id if user else None,
            )
        except Exception:
            standalone = question
    if trace_marks is not None:
        trace_marks["rewrite_ms"] = int((time.monotonic() - _t_start) * 1000)
    if str(source.driver) in ("excel_folder", "excel_template"):
        return await run_excel_data_ask(
            db,
            source=source,
            question=standalone,
            user=user,
            python_override=sql_override,
            llm_provider=llm_provider,
            llm_model=llm_model,
            execute=execute,
            skill_style=skill_ctx,
        )

    # 蓝图 P1-②：技能步骤编排——技能带 metadata_.steps 时走算子编排（逐步取 facts →
    # 结论生成），不再走 LLM 生成 SQL 的主链路；无 steps 保持 P0 行为（零改动兜底）。
    # excel 源不参与（无 SQL 算子）；编排失败按普通异常上抛，由外层统一写失败轨迹。
    if (
        execute and not sql_override and skill_ctx and skill_ctx.get("steps")
        and not _is_direct_calendar_ask(question, standalone)
    ):
        try:
            _gate_source, _gate_tables, _gate_semantic, _perm, _edges = await load_source_context(db, data_source_id)
            _gate_semantic, _gate_profile = await load_ds_semantic(db, data_source_id, _gate_semantic)
            enrich_table_meta_with_profile(_gate_tables, _gate_profile)
            blocked = await apply_answer_gate(db, _gate_source, _gate_tables, standalone, data_source_id)
            if blocked:
                return blocked
        except Exception:
            logging.getLogger("data_ask").warning("answer_gate_before_skill_failed", exc_info=True)
        result = await run_skill_orchestration(
            db,
            source=source,
            question=standalone,
            user=user,
            skill_ctx=skill_ctx,
            llm_provider=agent_provider,
            llm_model=agent_model,
            agent_goal=agent_goal,
            agent_backstory=agent_backstory,
            stage_queue=stage_queue,
            trace_marks=trace_marks,
        )
        result["skill_used"] = skill_used_brief(skill_ctx)
        # 治理链已在算子内执行。有事实才沉淀，失败编排不入库。
        if result.get("facts") and result.get("sql") and skill_ctx.get("skill_id"):
            try:
                from app.core.data_ask.skill_memory import save_skill_example

                await save_skill_example(
                    db,
                    data_source_id=str(source.id),
                    skill_id=str(skill_ctx["skill_id"]),
                    question=standalone,
                    sql_text=str(result.get("sql") or ""),
                    source="orchestration",
                    note="编排步骤经治理链产出",
                )
            except Exception:
                logging.getLogger("data_ask").warning("skill_memory_deposit_failed", exc_info=True)
        return result

    source, all_tables, semantic, perm_table, join_edges = await load_source_context(db, data_source_id)
    semantic, _profile_lookup = await load_ds_semantic(db, data_source_id, semantic)
    enrich_table_meta_with_profile(all_tables, _profile_lookup)
    if not source.chat_enabled and execute:
        raise ValueError("Chat Q&A is disabled for this data source")

    if execute and not sql_override:
        blocked = await apply_answer_gate(db, source, all_tables, standalone, data_source_id)
        if blocked:
            return blocked

    # 总体分析：笼统问题自动执行多维度查询 + 多图表
    if execute and not sql_override and is_overview_question(standalone):
        # overview SQL 依赖零售日报字段（RQ/XSJE/ML/XSCB 等），优先选含关键字段的表，避免盲选第一张表
        _ov_keys = {"RQ", "XSJE", "ML", "XSCB"}
        table_name = None
        for _t in all_tables:
            _cols = {
                str(c.get("name") or c.get("column_name") or "").upper()
                for c in (_t.get("columns") or [])
            }
            if _ov_keys & _cols:
                table_name = _t.get("table_name")
                if _ov_keys <= _cols:
                    break
        if not table_name:
            table_name = all_tables[0].get("table_name") if all_tables else None
        if table_name:
            result = await run_overview_analysis(
                db,
                source=source,
                table_name=table_name,
                question=standalone,
                llm_provider=agent_provider,
                llm_model=agent_model,
                agent_goal=agent_goal,
                agent_backstory=agent_backstory,
                user_id=user.id if user else None,
                stage_queue=stage_queue,
                skill_style=skill_ctx,
            )
            result["skill_used"] = skill_used_brief(skill_ctx)
            return result

    scope = await resolve_data_scope(db, user) if user else None
    ranked = rank_tables(standalone, all_tables, top_k=SCHEMA_TOP_K)
    allowed = {t["table_name"] for t in all_tables}
    if perm_table:
        allowed.add(perm_table)

    perm_rules = permission_config_from_rules(source.permission_rules)
    apply_perm = (bool(perm_table) and not bypass_row_permission(user, scope)
                  and not bypass_row_perm)
    perm_hint = ""
    if apply_perm and perm_table:
        # 先校验权限列是否真实存在：配错列时宁可明确报错，也不要生成非法 SQL
        # 或退化为「不加过滤」导致越权看到全量数据。
        effective, perm_error = await resolve_permission_columns(
            source, perm_table, perm_rules, _business_columns(all_tables),
        )
        if perm_error:
            raise ValueError(
                f"行级权限配置与数据源不一致：{perm_error}。"
                "请管理员在数据源设置中校正 permission_rules（用户列 / 范围列 / 数据列）。"
            )
        if effective != {k: str(perm_rules.get(k) or "").upper() for k in effective}:
            logging.getLogger("data_ask").warning(
                "permission_columns_autocorrected ds=%s configured=%s effective=%s",
                str(source.id), dict(perm_rules), effective,
            )
        # 后续所有注入（perm_hint / _wrap_permission / _probe_candidate）统一用校正后的列
        perm_rules = effective
        scope_sql = build_permission_scope_sql(
            user_key=_user_key(user),
            permission_table=perm_table,
            scope_column=perm_rules["scope_column"],
            user_column=perm_rules["user_column"],
            dialect=str(source.driver),
        )
        perm_hint = (
            f"Permission: filter {perm_rules['data_column']} IN ({scope_sql}). "
            "Apply in WHERE clause."
        )

    if not sql_override:
        standalone = await _resolve_relative_time(source, all_tables, standalone)
        # 显式中文日期 → ISO（相对时间已标注时自动跳过）
        standalone = await _resolve_explicit_dates(source, all_tables, standalone)
        # P0-C：clarify 判定统一走参数化版本（默认参数 == 线上现行行为），knobs 可调
        from app.core.data_ask.replay.strategies import clarify_decision

        hint = clarify_decision(
            standalone, all_tables, semantic,
            metric_min=knobs["clarify_metric_min"],
            vague_time_enabled=knobs["clarify_vague_time_enabled"],
            relative_time_exempt=knobs["clarify_relative_time_exempt"],
            time_resolved=True,  # 上行 _resolve_relative_time 已真实改写相对时间为具体日期
        )
        if hint:
            await _emit(stage_queue, {"event": "clarification", "question": hint})
            # P1-D 发现树：反问路径 root + result（意图未定即终止）
            _root = _tree_add(trace_marks, "root", None, {
                "question": question, "standalone": standalone,
                "user_id": str(user.id) if user else None,
            })
            _tree_add(trace_marks, "result", _root, {
                "mode": "clarification", "clarification": hint, "row_count": 0,
            })
            return {
                "answer": hint,
                "sql": "",
                "display_sql": "",
                "explanation": "",
                "columns": [],
                "rows": [],
                "row_count": 0,
                "truncated": False,
                "chart": None,
                "clarification": hint,
                "analysis_mode": "sql",
                "standalone_question": standalone,
            }

    compare_plan = None
    if not sql_override:
        try:
            compare_plan = plan_period_compare(standalone, all_tables)
        except Exception:
            compare_plan = None
    if compare_plan:
        if not execute:
            return {
                "answer": "",
                "sql": compare_plan["current_sql"] + ";\n" + compare_plan["previous_sql"],
                "display_sql": compare_plan["current_sql"],
                "explanation": compare_plan["explanation"],
                "columns": [],
                "rows": [],
                "row_count": 0,
                "truncated": False,
                "chart": None,
                "generated_only": True,
                "standalone_question": standalone,
                "route": "compare",
                "confidence": "high",
                "metric_intent": compare_plan.get("metric_intent"),
            }
        try:
            return await _execute_period_compare(
                db,
                source=source,
                user=user,
                question=question,
                standalone=standalone,
                plan=compare_plan,
                apply_perm=apply_perm,
                perm_table=perm_table,
                perm_rules=perm_rules,
            )
        except Exception:
            logging.getLogger("data_ask").warning("period_compare_failed", exc_info=True)

    memory_examples = (
        await _gather_memory_examples(
            db, data_source_id=data_source_id, question=standalone,
            top_k=knobs["memory_top_k"], min_score=knobs["memory_min_score"],
            strong_score=knobs["memory_strong_score"],
            skill_id=(skill_ctx or {}).get("skill_id") if skill_ctx else None,
        )
        if use_memory else []
    )
    if trace_marks is not None:
        trace_marks["memory_hits"] = len(memory_examples or [])
        if memory_examples:
            # P2 归因链：记录本次生成命中了哪些金标/示例记忆（写入 memory_hit_log）
            trace_marks["memory_matched"] = [
                {
                    "ref": str(e.get("ref_id") or "")[:64],
                    "ref_type": str(e.get("ref_type") or "")[:16],
                    "question": str(e.get("question") or "")[:200],
                    "score": round(float(e.get("score") or 0), 4),
                }
                for e in memory_examples
            ]

    # 同一提问的强记忆直接复用其 SQL：few-shot 提示无法保证模型不改写口径，
    # 而业务要求「纠正过的口径下次必须生效」，因此对完全同问（忽略空白/大小写）
    # 的 strong 示例直接沿用 SQL；执行失败仍由 _execute_with_retry 修复兜底。
    # 同问命中多条时优先金标（反馈时同步写入，纠正后立刻生效；蒸馏示例由 Celery 异步更新，可能滞后）。
    memory_sql = ""
    if not sql_override:
        _asked = _compact_question(standalone)
        _matched: list[dict[str, Any]] = []
        for _ex in memory_examples or []:
            if str(_ex.get("tier") or "strong") != "strong":
                continue
            if _compact_question(str(_ex.get("question") or "")) != _asked:
                continue
            _cand = str(_ex.get("sql") or "").strip()
            if _cand.lower().lstrip("(").startswith(("select", "with")):
                _matched.append(_ex)
        if _matched:
            _golden = [e for e in _matched if str(e.get("ref_type") or "") == "golden"]
            memory_sql = str((_golden or _matched)[0].get("sql") or "").strip()

    # P1-D 发现树：root（提问/改写/用户）+ intent（记忆命中与生成方式）
    root_id = _tree_add(trace_marks, "root", None, {
        "question": question, "standalone": standalone,
        "user_id": str(user.id) if user else None,
    })
    intent_id = _tree_add(trace_marks, "intent", root_id, {
        "use_memory": bool(use_memory),
        "memory_hits": len(memory_examples or []),
        "memory": [
            {"ref": str(e.get("ref_id") or "")[:64],
             "tier": str(e.get("tier") or "strong"),
             "score": e.get("score"), "question": str(e.get("question") or "")[:120]}
            for e in (memory_examples or [])
        ],
        "sql_override": bool(sql_override),
        "memory_reuse": bool(memory_sql),
    })

    _t_gen = time.monotonic()
    voted_qr: dict[str, Any] | None = None
    # 指标层 v1（蓝图 L1）：意图→指标组合→确定性拼 SQL。
    # 优先级：sql_override > memory_sql(金标) > 指标层 > LLM；未命中返回 None 走 LLM。
    metric_hit: dict[str, Any] | None = None
    if not sql_override and not memory_sql:
        try:
            metric_hit = await try_metric_route(source, standalone, all_tables)
        except Exception:
            metric_hit = None
    route_mode = "single"
    metric_intent: dict[str, Any] | None = None
    if sql_override:
        route_mode = "override"
        sql, explanation = sql_override.strip(), "User provided SQL"
        _tree_add(trace_marks, "candidate", intent_id, {
            "index": 0, "mode": "override",
            "sql": sql[:8000], "explanation": explanation[:500],
        })
    elif memory_sql:
        route_mode = "memory_reuse"
        sql, explanation = memory_sql, "沿用已确认的问答口径"
        _tree_add(trace_marks, "candidate", intent_id, {
            "index": 0, "mode": "memory_reuse",
            "sql": sql[:8000], "explanation": explanation[:500],
        })
    elif metric_hit:
        route_mode = "metric"
        sql, explanation = str(metric_hit["sql"]), str(metric_hit["explanation"])
        metric_intent = {k: metric_hit.get(k) for k in (
            "metric_keys", "metric_names", "dimension", "time", "store_phrase", "store_stem",
        )}
        _tree_add(trace_marks, "candidate", intent_id, {
            "index": 0, "mode": "metric",
            "sql": sql[:8000], "explanation": explanation[:500],
            "metrics": metric_hit.get("metric_names") or [],
        })
    elif question_needs_variants(standalone, ranked):
        pairs = await generate_sql_candidates(
            db,
            question=standalone,
            driver=str(source.driver),
            tables=ranked,
            semantic_model=semantic,
            llm_provider=agent_provider,
            llm_model=agent_model,
            permission_hint=perm_hint,
            memory_examples=memory_examples,
            join_edges=join_edges,
            user_id=user.id if user else None,
        )
        probes = [
            await _probe_candidate(
                source=source,
                sql=cand_sql,
                explanation=cand_expl,
                question=standalone,
                semantic=semantic,
                ranked=ranked,
                allowed=allowed,
                user=user,
                scope=scope,
                apply_perm=apply_perm,
                perm_table=perm_table,
                perm_rules=perm_rules,
            )
            for cand_sql, cand_expl in pairs[:2]
        ]
        winner = rank_probes(probes)
        # P1-D 发现树：候选分支（每候选 probe 执行结果 + 胜出标记）
        for _i, _probe in enumerate(probes):
            _tree_add(trace_marks, "candidate", intent_id, {
                "index": _i, "mode": "variants",
                "sql": str(_probe.get("sql") or "")[:8000],
                "explanation": str(_probe.get("explanation") or "")[:500],
                "error": str(_probe.get("error") or "")[:500] or None,
                "row_count": int(_probe.get("row_count") or 0),
                "hint_hits": int(_probe.get("hint_hits") or 0),
                "won": bool(winner is not None and _probe is winner),
            })
        if winner:
            sql = str(winner["sql"])
            explanation = str(winner.get("explanation") or "")
            if len(pairs) > 1:
                explanation = f"多表候选 {len(pairs)} 条，采用可执行结果。\n{explanation}".strip()
            voted_qr = {
                "exec_sql": winner["exec_sql"],
                "display_sql": sql,
                "explanation": explanation,
                "columns": winner["columns"],
                "rows": winner["rows"],
                "row_count": winner["row_count"],
                "truncated": winner["truncated"],
            }
        else:
            sql, explanation = await _align_metrics(
                db,
                sql=pairs[0][0],
                explanation=pairs[0][1],
                question=standalone,
                driver=str(source.driver),
                tables=ranked,
                semantic=semantic,
                llm_provider=agent_provider,
                llm_model=agent_model,
                permission_hint=perm_hint,
                join_edges=join_edges,
                user_id=user.id if user else None,
            )
    else:
        sql, explanation = await generate_sql(
            db,
            question=standalone,
            driver=str(source.driver),
            tables=ranked,
            semantic_model=semantic,
            llm_provider=agent_provider,
            llm_model=agent_model,
            permission_hint=perm_hint,
            memory_examples=memory_examples,
            join_edges=join_edges,
            user_id=user.id if user else None,
        )
        # P1-D 发现树：单路生成分支
        _tree_add(trace_marks, "candidate", intent_id, {
            "index": 0, "mode": "single",
            "sql": sql[:8000], "explanation": str(explanation or "")[:500],
        })
        sql, explanation = await _align_metrics(
            db,
            sql=sql,
            explanation=explanation,
            question=standalone,
            driver=str(source.driver),
            tables=ranked,
            semantic=semantic,
            llm_provider=agent_provider,
            llm_model=agent_model,
            permission_hint=perm_hint,
            join_edges=join_edges,
            user_id=user.id if user else None,
        )

    if trace_marks is not None:
        trace_marks["gen_ms"] = int((time.monotonic() - _t_gen) * 1000)
    if voted_qr is None and route_mode not in ("override", "memory_reuse", "metric"):
        _latest_for_bound = await _latest_biz_date(source, all_tables)
        sql = bound_undated_sql(
            sql, standalone, _latest_for_bound.isoformat() if _latest_for_bound else None,
        )

    if voted_qr is None:
        sql = disambiguate_subquery_columns(sql, dialect=str(source.driver))
        ok, msg = validate_select_sql(sql, allowed_tables=allowed, dialect=str(source.driver))
        if not ok:
            _tree_add(trace_marks, "execution", root_id, {
                "sql": sql[:8000], "ok": False, "error": str(msg)[:500], "stage": "sql_guard",
            })
            await log_query(
                db,
                user_id=user.id if user else None,
                data_source_id=data_source_id,
                question=question,
                sql_text=sql,
                row_count=0,
                success=False,
                error_message=msg,
            )
            raise ValueError(msg)

        col_ok, col_msg = validate_sql_columns(
            sql,
            semantic_model=semantic,
            user_is_admin=bool(user and user.is_admin),
            scope=scope,
        )
        if not col_ok:
            _tree_add(trace_marks, "execution", root_id, {
                "sql": sql[:8000], "ok": False, "error": str(col_msg)[:500], "stage": "column_policy",
            })
            await log_query(
                db,
                user_id=user.id if user else None,
                data_source_id=data_source_id,
                question=question,
                sql_text=sql,
                row_count=0,
                success=False,
                error_message=col_msg,
            )
            raise ValueError(col_msg)

    if not execute:
        preview = {
            "answer": "",
            "sql": sql,
            "display_sql": sql,
            "explanation": explanation,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "chart": None,
            "generated_only": True,
            "standalone_question": standalone,
            "route": route_mode,
            "confidence": _route_confidence(route_mode),
            "metric_intent": metric_intent,
        }
        await _emit_sql_stages(stage_queue, question, preview)
        return preview

    if voted_qr is not None:
        qr = voted_qr
        # P1-D 发现树：胜出候选已 probe 执行（结果记在候选节点，这里补最终执行节点）
        _tree_add(trace_marks, "execution", root_id, {
            "sql": str(qr.get("exec_sql") or "")[:8000], "ok": True,
            "row_count": int(qr.get("row_count") or 0), "from_candidate": True,
        })
    else:
        exec_sql = _wrap_permission(sql, apply_perm, perm_table, perm_rules, user, source)
        _t_exec = time.monotonic()
        qr = await _execute_with_retry(
            db,
            source=source,
            question=standalone,
            sql=sql,
            exec_sql=exec_sql,
            ranked=ranked,
            join_edges=join_edges,
            perm_hint=perm_hint,
            allowed=allowed,
            semantic=semantic,
            user=user,
            scope=scope,
            agent_provider=agent_provider,
            agent_model=agent_model,
            apply_perm=apply_perm,
            perm_table=perm_table,
            perm_rules=perm_rules,
            max_sql_retries=max_sql_retries,
        )
        if trace_marks is not None:
            trace_marks["exec_ms"] = int((time.monotonic() - _t_exec) * 1000)
        # P1-D 发现树：最终执行结果
        _tree_add(trace_marks, "execution", root_id, {
            "sql": str(qr.get("exec_sql") or "")[:8000], "ok": True,
            "row_count": int(qr.get("row_count") or 0),
        })

    _date_label = _window_label(standalone, metric_intent, str(qr.get("display_sql") or ""))
    if _date_label:
        qr["columns"] = _stamp_measure_columns(qr["columns"], qr["rows"], _date_label)
    chart = _suggest_chart(qr["columns"], qr["rows"], standalone)
    if standalone != question and explanation and not str(explanation).startswith("追问理解为"):
        explanation = f"追问理解为：{standalone}\n{explanation}"
    elif standalone != question and not explanation:
        explanation = f"追问理解为：{standalone}"
    await log_query(
        db,
        user_id=user.id if user else None,
        data_source_id=data_source_id,
        question=question,
        sql_text=qr["exec_sql"],
        row_count=qr["row_count"],
        success=True,
    )
    await _emit_sql_stages(
        stage_queue,
        question,
        {
            "sql": qr["exec_sql"],
            "display_sql": qr["display_sql"],
            "columns": qr["columns"],
            "rows": qr["rows"],
            "chart": chart,
            "standalone_question": standalone,
        },
    )

    _t_ana = time.monotonic()
    answer_mode = force_answer_mode or classify_answer_mode(
        standalone,
        qr["columns"],
        qr["rows"],
        extra_keywords=keywords_from_semantic(semantic),
    )
    # 指标层单值查询结果为空：给确定性兜底文案（数据未同步是常态，避免 LLM 自由发挥误导口径）
    _metric_no_data = (
        metric_intent is not None
        and not metric_intent.get("dimension")
        and (
            not qr["rows"]
            or all(v is None for _row in qr["rows"] for v in _row)
        )
    )
    if _metric_no_data:
        analysis = _no_data_answer(standalone, metric_intent)
    elif (metric_intent or {}).get("time", {}).get("origin") == "cumulative" and not (metric_intent or {}).get("dimension"):
        analysis = _cumulative_answer(qr["columns"], qr["rows"])
    else:
        analysis = await analyze_results(
            db,
            question=standalone,
            sql=qr["exec_sql"],
            columns=qr["columns"],
            rows=qr["rows"],
            chart=chart,
            answer_mode=answer_mode,
            llm_provider=agent_provider,
            llm_model=agent_model,
            user_id=user.id if user else None,
            agent_goal=agent_goal,
            agent_backstory=agent_backstory,
            skill_style=skill_ctx,
        )
    coverage = _coverage_note(standalone, has_data=not _metric_no_data)
    if coverage and coverage not in analysis:
        analysis = coverage + analysis
    analysis = _ensure_date_visible(analysis, _date_label, answer_mode)
    analysis, next_chart = await _attach_forecast(
        str(source.id), qr["columns"], qr["rows"], standalone, analysis, chart
    )
    if trace_marks is not None:
        trace_marks["analysis_ms"] = int((time.monotonic() - _t_ana) * 1000)
        trace_marks["answer_mode"] = answer_mode
    if next_chart != chart:
        await _emit_chart_stages(stage_queue, next_chart)
    chart = next_chart
    shown = qr.get("explanation") or explanation
    if standalone != question and shown and not str(shown).startswith("追问理解为"):
        shown = f"追问理解为：{standalone}\n{shown}"
    return {
        "answer": analysis,
        "sql": qr["exec_sql"],
        "display_sql": qr["display_sql"],
        "explanation": shown,
        "columns": qr["columns"],
        "rows": qr["rows"],
        "row_count": qr["row_count"],
        "truncated": qr["truncated"],
        "chart": chart,
        "analysis_mode": "sql",
        "answer_mode": answer_mode,
        "standalone_question": standalone,
        "route": route_mode,
        "confidence": _route_confidence(route_mode),
        "metric_intent": metric_intent,
        "skill_used": skill_used_brief(skill_ctx),
    }



async def write_ask_trace(
    db: AsyncSession,
    *,
    data_source_id: str,
    question: str,
    user: User | None,
    result: dict[str, Any] | None = None,
    success: bool = True,
    error_message: str | None = None,
    duration_ms: int | None = None,
    marks: dict[str, Any] | None = None,
    cached: bool = False,
) -> int | None:
    """写问数轨迹（Agent Evolution 阶段一信号采集）。独立容错，绝不影响主流程。"""
    try:
        import hashlib

        from app.db.models import AskTrace

        r = result or {}
        m = marks or {}
        sig = None
        cols = r.get("columns") or []
        rows = r.get("rows") or []
        if cols:
            sig = hashlib.sha256(
                json.dumps(
                    {"c": [str(c) for c in cols], "n": r.get("row_count"), "h": rows[:5]},
                    ensure_ascii=False, default=str,
                ).encode("utf-8")
            ).hexdigest()[:32]
        row = AskTrace(
            data_source_id=str(data_source_id),
            user_id=str(user.id) if user else None,
            question=(question or "")[:4000],
            standalone_question=(r.get("standalone_question") or "")[:4000] or None,
            sql_text=(r.get("sql") or "")[:8000] or None,
            row_count=r.get("row_count"),
            success=success,
            error_message=(error_message or "")[:2000] or None,
            analysis_mode=r.get("analysis_mode") or None,
            answer_mode=r.get("answer_mode") or None,
            memory_hits=int(m.get("memory_hits") or 0),
            duration_ms=duration_ms,
            rewrite_ms=m.get("rewrite_ms"),
            gen_ms=m.get("gen_ms"),
            exec_ms=m.get("exec_ms"),
            analysis_ms=m.get("analysis_ms"),
            result_signature=sig,
            clarification=bool(r.get("clarification")),
            cached=cached,
            skill_id=(str((r.get("skill_used") or {}).get("skill_id"))[:36] or None)
            if isinstance(r.get("skill_used"), dict) and (r.get("skill_used") or {}).get("skill_id")
            else None,
            skill_version=(
                str((r.get("skill_used") or {}).get("version"))[:16]
                if isinstance(r.get("skill_used"), dict)
                and (r.get("skill_used") or {}).get("version") is not None
                else None
            ),
            steps_profile=(r.get("steps_profile")[:12] if isinstance(r.get("steps_profile"), list) else None),
        )
        db.add(row)
        await db.flush()
        return int(row.id)
    except Exception as exc:  # 轨迹写库失败不影响问数主流程
        logging.getLogger("data_ask_trace").warning("write_ask_trace_failed err=%s", str(exc)[:200])
        return None


def _tree_add(
    marks: dict[str, Any] | None,
    kind: str,
    parent_id: str | None,
    payload: dict[str, Any],
) -> str | None:
    """P1-D 发现树：把节点收集到 marks，由 run_data_ask 收尾统一落库。绝不影响主流程。"""
    if marks is None:
        return None
    try:
        from app.db.base import generate_uuid

        nodes = marks.setdefault("tree_nodes", [])
        run_id = marks.get("tree_run_id")
        if not run_id:
            run_id = generate_uuid()
            marks["tree_run_id"] = run_id
        node_id = generate_uuid()
        nodes.append({
            "id": node_id, "run_id": run_id, "parent_id": parent_id,
            "node_kind": kind, "node_order": len(nodes), "payload": payload,
        })
        return node_id
    except Exception:
        return None


async def _write_ask_tree(
    db: AsyncSession, *, data_source_id: str, trace_id: int | None, marks: dict[str, Any]
) -> None:
    """P1-D：把 run 期间收集的发现树节点落库。独立容错，绝不影响主流程。"""
    nodes = marks.get("tree_nodes") or []
    if not nodes or not trace_id:
        return
    try:
        from app.db.models import DataAskTreeNode

        for n in nodes:
            db.add(DataAskTreeNode(
                id=str(n["id"]), data_source_id=str(data_source_id), trace_id=int(trace_id),
                run_id=str(n["run_id"]), parent_id=n.get("parent_id"),
                node_kind=str(n["node_kind"]), node_order=int(n.get("node_order") or 0),
                payload=n.get("payload"),
            ))
        await db.flush()
    except Exception as exc:
        logging.getLogger("data_ask_trace").warning("write_ask_tree_failed err=%s", str(exc)[:200])


async def _record_memory_hits(
    *,
    data_source_id: str,
    user: User | None,
    question: str,
    trace_id: int | None,
    marks: dict[str, Any],
) -> None:
    """写记忆命中归因日志（P2）。独立容错：失败绝不影响问数主流程。"""
    if not trace_id:
        return
    matched = marks.get("memory_matched") or []
    try:
        from app.db.models import MemoryHitLog
        from app.db.session import AsyncSessionLocal

        scores = [float(m.get("score") or 0) for m in matched if isinstance(m, dict)]
        async with AsyncSessionLocal() as tdb:
            tdb.add(MemoryHitLog(
                trace_id=int(trace_id), data_source_id=str(data_source_id),
                user_id=str(user.id) if user else None,
                question=(question or "")[:2000] or None,
                matched=list(matched),
                match_score=max(scores) if scores else None,
            ))
            await tdb.commit()
    except Exception:
        logging.getLogger("data_ask_trace").warning("memory_hit_log_failed trace=%s", trace_id)


async def run_data_ask(
    db: AsyncSession,
    *,
    data_source_id: str,
    question: str,
    user: User | None,
    **kwargs: Any,
) -> dict[str, Any]:
    """问数入口包装器：计时 + 写 ask_trace + 结果注入 trace_id（阶段一信号采集）。"""
    t0 = time.monotonic()
    marks: dict[str, int] = {}
    # 同问短期缓存：语义提示对模型只是建议，结果必须可复现，重复提问直接复用
    # 蓝图 P0：缓存键纳入技能维度（employee_id/skill_id），否则不同技能命中同一缓存会串风格
    _skill_scope = ""
    if kwargs.get("employee_id"):
        _skill_scope += f":emp:{kwargs['employee_id']}"
    if kwargs.get("skill_id"):
        _skill_scope += f":skill:{kwargs['skill_id']}"
    cache_key = None
    try:
        from app.core.chat.reflector import is_dialogue_act
        _dialogue_act = is_dialogue_act(question)
    except Exception:
        _dialogue_act = False
    if (
        not _dialogue_act
        and kwargs.get("execute", True)
        and not kwargs.get("sql_override")
        and _cacheable_question(question)
    ):
        cache_key = make_dataask_cache_key(
            data_source_id=data_source_id,
            question=question_cache_key_text(question),
            llm_provider=kwargs.get("llm_provider"),
            llm_model=kwargs.get("llm_model"),
            execute=True,
            user_key=_user_key(user) + _skill_scope,
        )
        # 点了门店、或问了客流表没有的维度时，不复用旧缓存。旧缓存里有过「卖场店 = 另一家店的数」。
        _recheck = bool(grain_refusal(question) or store_mentions(question))
        hit = None if _recheck else await cache_get_json(cache_key)
        if isinstance(hit, dict) and hit.get("answer"):
            hit["cached"] = True
            hit["trace_id"] = None
            # 缓存命中也要更新会话状态（否则后续追问会跟到更早的问题上）
            try:
                from app.core.data_ask.session_engine import build_suggestions, extract_state, save_session
                _state = extract_state(hit)
                await save_session(user, _state)
                if not hit.get("suggestions"):
                    hit["suggestions"] = build_suggestions(_state)
            except Exception:
                pass
            return hit
    try:
        result = await _run_data_ask_impl(
            db,
            data_source_id=data_source_id,
            question=question,
            user=user,
            trace_marks=marks,
            **kwargs,
        )
    except Exception as exc:
        try:
            from app.db.session import AsyncSessionLocal

            async with AsyncSessionLocal() as tdb:
                fail_trace_id = await write_ask_trace(
                    tdb, data_source_id=data_source_id, question=question, user=user,
                    success=False, error_message=str(exc)[:1000],
                    duration_ms=int((time.monotonic() - t0) * 1000), marks=marks,
                )
                # P1-D 发现树：失败路径 result 节点 + 落库
                _root = next(
                    (n for n in (marks.get("tree_nodes") or []) if n["node_kind"] == "root"), None
                )
                _tree_add(marks, "result", _root["id"] if _root else None, {
                    "mode": "error", "ok": False, "error": str(exc)[:1000],
                    "row_count": 0, "duration_ms": int((time.monotonic() - t0) * 1000),
                })
                await _write_ask_tree(tdb, data_source_id=data_source_id,
                                      trace_id=fail_trace_id, marks=marks)
                await tdb.commit()
                await _record_memory_hits(
                    data_source_id=data_source_id, user=user, question=question,
                    trace_id=fail_trace_id, marks=marks,
                )
        except Exception:
            pass
        raise
    # 会话引擎 v1：记录会话状态（指标/维度/时间/SQL），附 3 个确定性追问建议
    # （在写缓存前挂上，缓存命中时直接带回）
    try:
        from app.core.data_ask.session_engine import build_suggestions, extract_state, save_session
        state = extract_state(result)
        await save_session(user, state)
        if not result.get("suggestions"):
            result["suggestions"] = build_suggestions(state)
    except Exception:
        pass
    if cache_key:
        await cache_set_json(cache_key, result)
    trace_id = await write_ask_trace(
        db, data_source_id=data_source_id, question=question, user=user,
        result=result, duration_ms=int((time.monotonic() - t0) * 1000), marks=marks,
    )
    # P1-D 发现树：result 节点 + 统一落库（节点收集与 trace_id 关联）
    _root = next(
        (n for n in (marks.get("tree_nodes") or []) if n["node_kind"] == "root"), None
    )
    _tree_add(marks, "result", _root["id"] if _root else None, {
        "mode": result.get("analysis_mode") or "sql", "ok": True,
        "row_count": result.get("row_count"),
        "duration_ms": int((time.monotonic() - t0) * 1000),
        "trace_id": trace_id,
    })
    await _write_ask_tree(db, data_source_id=data_source_id, trace_id=trace_id, marks=marks)
    result["trace_id"] = trace_id
    result["memory_hits"] = int(marks.get("memory_hits") or 0)
    result["tree_run_id"] = marks.get("tree_run_id")
    await _record_memory_hits(
        data_source_id=data_source_id, user=user, question=question,
        trace_id=trace_id, marks=marks,
    )
    return result



# ─── ML analysis mode ──────────────────────────────────────────
ML_KEYWORDS = [
    "预测", "predict", "forecast", "预报",
    "聚类", "cluster", "kmeans", "分群",
    "分类", "classify", "classification",
    "回归", "regression",
    "相关性", "correlation", "corr",
    "异常检测", "anomaly", "outlier",
    "聚类", "segmentation",
    "特征重要性", "feature importance",
    "时间序列", "time series", "arima",
]


def _is_ml_question(question: str) -> bool:
    """Check if the question requires ML analysis."""
    q = question.lower()
    return any(kw in q for kw in ML_KEYWORDS)


FORECAST_KEYWORDS = ["预测", "predict", "forecast", "未来", "下月", "下周", "明年", "预估"]


def _is_forecast_question(question: str) -> bool:
    q = (question or "").lower()
    return any(k in q for k in FORECAST_KEYWORDS)


async def run_ml_data_ask(
    db: AsyncSession,
    *,
    data_source_id: str,
    question: str,
    user: "User | None",
    sql_override: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    execute: bool = True,
) -> dict[str, Any]:
    """ML-enhanced data analysis: SQL data retrieval + Python ML execution."""
    from app.core.data_ask.intelligence.nl2sql import generate_sql, analyze_results
    from app.core.data_ask.service import (
        load_source_context, rank_tables, _resolve_llm,
        _execute_with_retry, _suggest_chart, SCHEMA_TOP_K,
    )
    from app.core.data_ask.analysis.python_runner import run_python_analysis
    from app.core.data_ask.semantic.mdl import expand_metrics_in_prompt, format_semantic_context
    from app.core.data_ask.intelligence.query_memory import format_memory_prompt, retrieve_similar_queries
    from app.core.auth.permissions import resolve_data_scope
    from app.models_hub.router import ModelRouter
    from langchain_core.messages import SystemMessage, HumanMessage
    import pandas as pd
    import numpy as np

    source, all_tables, semantic, perm_table, join_edges = await load_source_context(db, data_source_id)
    semantic, _profile_lookup = await load_ds_semantic(db, data_source_id, semantic)
    enrich_table_meta_with_profile(all_tables, _profile_lookup)
    if not source.chat_enabled and execute:
        raise ValueError("Chat Q&A is disabled for this data source")

    scope = await resolve_data_scope(db, user) if user else None
    ranked = rank_tables(question, all_tables, top_k=SCHEMA_TOP_K)
    allowed = {t["table_name"] for t in all_tables}
    if perm_table:
        allowed.add(perm_table)

    agent_provider, agent_model, agent_goal, agent_backstory = await _resolve_llm(
        db, source, llm_provider, llm_model, spec_override=spec_override
    )
    knobs = _resolve_policy_knobs(source, spec_override)
    memory_examples = await _gather_memory_examples(
        db, data_source_id=data_source_id, question=question,
        top_k=knobs["memory_top_k"], min_score=knobs["memory_min_score"],
        strong_score=knobs["memory_strong_score"],
    )

    # Step 1: Generate SQL to get raw data
    if sql_override:
        sql, explanation = sql_override.strip(), "User provided SQL"
    else:
        sql, explanation = await generate_sql(
            db,
            question=question,
            driver=str(source.driver),
            tables=ranked,
            semantic_model=semantic,
            llm_provider=agent_provider,
            llm_model=agent_model,
            memory_examples=memory_examples,
            join_edges=join_edges,
            user_id=user.id if user else None,
        )

    # Step 2: Execute SQL to get data
    perm_rules = permission_config_from_rules(getattr(source, "permission_rules", None))
    apply_perm = bool(perm_table) and not bypass_row_permission(user, scope)
    if apply_perm and perm_table:
        effective, perm_error = await resolve_permission_columns(
            source, perm_table, perm_rules, _business_columns(all_tables),
        )
        if perm_error:
            raise ValueError(f"行级权限配置与数据源不一致：{perm_error}")
        perm_rules = effective
    exec_sql = sql
    qr = await _execute_with_retry(
        db,
        source=source,
        question=question,
        sql=sql,
        exec_sql=exec_sql,
        ranked=ranked,
        join_edges=join_edges,
        perm_hint="",
        allowed=allowed,
        semantic=semantic,
        user=user,
        scope=scope,
        agent_provider=agent_provider,
        agent_model=agent_model,
        apply_perm=apply_perm,
        perm_table=perm_table,
        perm_rules=perm_rules,
        max_sql_retries=max_sql_retries,
    )

    if not execute:
        return {
            "answer": "ML analysis generated (not executed).",
            "sql": qr.get("exec_sql", sql),
            "display_sql": qr.get("display_sql", sql),
            "explanation": explanation,
            "columns": [], "rows": [], "row_count": 0,
            "truncated": False, "chart": None,
            "analysis_mode": "ml_preview",
        }

    # Step 3: Convert SQL results to DataFrame
    columns = qr.get("columns", [])
    rows = qr.get("rows", [])
    if not columns or not rows:
        return {
            "answer": "No data available for ML analysis.",
            "sql": qr.get("exec_sql", sql),
            "display_sql": qr.get("display_sql", sql),
            "explanation": explanation,
            "columns": columns, "rows": rows,
            "row_count": 0, "truncated": False,
            "chart": None, "analysis_mode": "ml", "answer_mode": "L1",
        }

    df = pd.DataFrame(rows, columns=columns)

    # Step 3.5: 现役 LSTM 优先预测（模型进化：预测类问题走已进化模型，失败/不足则走经典路径）
    forecast_info: dict | None = None
    if _is_forecast_question(question):
        try:
            from app.core.data_ask.ml_evolution.evolution import forecast_with_production
            forecast_info = await forecast_with_production(str(source.id), columns, rows, question)
        except Exception:
            forecast_info = None

    # Step 3.6: 序列形态判定（现役CNN，时序问数自动附加，毫秒级）
    shape_info: dict | None = None
    try:
        from app.core.data_ask.ml_evolution.evolution import classify_with_production
        shape_info = await classify_with_production(str(source.id), columns, rows, question)
    except Exception:
        shape_info = None

    # Step 4: Generate ML Python code via LLM
    data_preview = df.head(5).to_string()
    col_info = [{"name": c, "dtype": str(df[c].dtype)} for c in df.columns]
    numeric_cols = [c for c in df.columns if df[c].dtype in (np.float64, np.int64, float, int)]
    categorical_cols = [c for c in df.columns if c not in numeric_cols]

    ml_system = """You are an ML engineer. Generate Python code for ML analysis.
Rules:
1. Use the variable `df` (pandas DataFrame, already loaded with SQL results)
2. Available libraries: sklearn, statsmodels, scipy, numpy, pandas
3. Assign final result to `result = {}` with keys: columns, rows, summary(str), chart(dict|None)
4. chart format: dict with keys type, labels, values, series, extra
5. Handle small datasets gracefully (use simple models, avoid overfitting)
6. Return predictions, cluster assignments, or correlation values as table rows
7. Include a summary string with key ML metrics (R-squared, silhouette score, etc.)
8. For time series: use statsmodels ARIMA or simple linear regression
9. For clustering: use sklearn KMeans with 2-4 clusters
10. For correlation: use df.corr() and return the matrix
"""

    ml_user = f"""Question: {question}
Data shape: {df.shape[0]} rows, {df.shape[1]} columns
Columns: {col_info}
Numeric columns: {numeric_cols}
Categorical columns: {categorical_cols}
Data preview:
{data_preview}
Generate Python ML code. The variable `df` is already available.
Assign result to `result`.
"""

    llm = await ModelRouter.get_llm(
        db=db,
        provider=agent_provider,
        model=agent_model,
        user_id=user.id if user else None,
        response_style="precise",
    )

    resp = await llm.ainvoke([SystemMessage(content=ml_system), HumanMessage(content=ml_user)])
    ml_code = resp.content if isinstance(resp.content, str) else str(resp.content)

    # Extract code from markdown code blocks if present
    if "```python" in ml_code:
        ml_code = ml_code.split("```python")[1].split("```")[0]
    elif "```" in ml_code:
        ml_code = ml_code.split("```")[1].split("```")[0]

    # Step 5: Execute ML code
    try:
        from app.core.data_ask.analysis.python_runner import run_python_analysis
        frames = {"data": df}
        local_vars: dict = {"frames": frames, "df": df, "result": None}

        # Build safe globals for ML - pre-import common functions
        import sklearn.cluster as _sk_c
        import sklearn.linear_model as _sk_lm
        import sklearn.ensemble as _sk_e
        import sklearn.preprocessing as _sk_p
        import sklearn.decomposition as _sk_d
        import sklearn.metrics as _sk_m
        import sklearn.model_selection as _sk_ms
        ml_globals = {
            '__builtins__': __builtins__,
            'pd': pd, 'np': np,
            'sklearn': __import__('sklearn'),
            'statsmodels': __import__('statsmodels') if _has_statsmodels() else None,
            'scipy': __import__('scipy'),
            'json': json,
            'LinearRegression': _sk_lm.LinearRegression,
            'LogisticRegression': _sk_lm.LogisticRegression,
            'Ridge': _sk_lm.Ridge,
            'Lasso': _sk_lm.Lasso,
            'KMeans': _sk_c.KMeans,
            'DBSCAN': _sk_c.DBSCAN,
            'AgglomerativeClustering': _sk_c.AgglomerativeClustering,
            'RandomForestRegressor': _sk_e.RandomForestRegressor,
            'RandomForestClassifier': _sk_e.RandomForestClassifier,
            'IsolationForest': _sk_e.IsolationForest,
            'StandardScaler': _sk_p.StandardScaler,
            'MinMaxScaler': _sk_p.MinMaxScaler,
            'LabelEncoder': _sk_p.LabelEncoder,
            'OneHotEncoder': _sk_p.OneHotEncoder,
            'PCA': _sk_d.PCA,
            'silhouette_score': _sk_m.silhouette_score,
            'silhouette_samples': _sk_m.silhouette_samples,
            'mean_squared_error': _sk_m.mean_squared_error,
            'r2_score': _sk_m.r2_score,
            'accuracy_score': _sk_m.accuracy_score,
            'classification_report': _sk_m.classification_report,
            'confusion_matrix': _sk_m.confusion_matrix,
            'train_test_split': _sk_ms.train_test_split,
            'cross_val_score': _sk_ms.cross_val_score,
        }
        if _has_statsmodels():
            try:
                from statsmodels.tsa.arima.model import ARIMA
                from statsmodels.tsa.statespace.sarimax import SARIMAX
                import statsmodels.api as sm
                ml_globals['ARIMA'] = ARIMA
                ml_globals['SARIMAX'] = SARIMAX
                ml_globals['sm'] = sm
            except Exception:
                pass

        exec(ml_code, ml_globals, local_vars)
        ml_result = local_vars.get("result")

        if ml_result is None:
            raise ValueError("ML code did not assign result")

        if isinstance(ml_result, pd.DataFrame):
            preview = ml_result.head(500)
            ml_columns = [str(c) for c in preview.columns]
            ml_rows = preview.to_numpy().tolist()
        elif isinstance(ml_result, dict):
            ml_columns = [str(c) for c in (ml_result.get("columns") or [])]
            ml_rows = ml_result.get("rows") or []
        else:
            ml_columns = ["result"]
            ml_rows = [[str(ml_result)]]

    except Exception as e:
        ml_columns = columns
        ml_rows = rows
        ml_result = {"summary": f"ML analysis failed: {e}", "chart": None}

    # Ensure ml_rows and ml_columns are always proper types
    from app.core.data_ask.utils.json_safe import json_safe_value
    # Handle non-list ml_rows (ML code might return int, numpy array, etc.)
    if not isinstance(ml_rows, list):
        if ml_rows is None:
            ml_rows = []
        elif isinstance(ml_rows, (int, float, str)):
            ml_rows = [[ml_rows]]
        else:
            try:
                ml_rows = list(ml_rows)
            except TypeError:
                ml_rows = [[str(ml_rows)]]
    # Ensure each row is a list
    safe_rows = []
    for row in ml_rows:
        if isinstance(row, (list, tuple)):
            safe_rows.append([json_safe_value(v) for v in row])
        else:
            safe_rows.append([json_safe_value(row)])
    ml_rows = safe_rows
    # Ensure ml_columns is a list of strings
    if not isinstance(ml_columns, list):
        ml_columns = [str(ml_columns)] if ml_columns is not None else []
    if not ml_columns:
        ml_columns = ["col_" + str(j+1) for j in range(len(ml_rows[0]) if ml_rows else 0)]
    ml_columns = [str(c) for c in ml_columns]

    # Step 6: Generate analysis text
    summary = ""
    chart = None
    if isinstance(ml_result, dict):
        summary = ml_result.get("summary", "")
        chart = ml_result.get("chart")

    # LLM analysis of ML results
    analysis = await analyze_results(
        db,
        question=question,
        sql=qr.get("exec_sql", sql),
        columns=ml_columns,
        rows=ml_rows[:30],
        answer_mode=MODE_ANALYSIS,
        llm_provider=agent_provider,
        llm_model=agent_model,
        user_id=user.id if user else None,
        agent_goal=agent_goal,
        agent_backstory=agent_backstory,
    )

    if summary:
        analysis = f"{analysis}\n\n**ML模型指标**\n{summary}"

    # Auto chart if not provided
    if not chart:
        try:
            chart = _suggest_chart(ml_columns, ml_rows, question)
        except Exception:
            chart = None

    # 模型进化档案：现役预测结果 / 数据不足提示（数据真实性红线：不足不硬训）
    if forecast_info:
        if forecast_info.get("ok"):
            analysis = f"{analysis}\n\n{forecast_info['answer_section']}"
            if forecast_info.get("chart"):
                chart = forecast_info["chart"]
        elif forecast_info.get("reason"):
            analysis = f"{analysis}\n\n**模型进化档案**\n{forecast_info['reason']}"

    # 序列形态判定（CNN 进化档案）
    if shape_info and shape_info.get("ok"):
        analysis = f"{analysis}\n\n{shape_info['answer_section']}"

    return {
        "answer": analysis,
        "sql": qr.get("exec_sql", sql),
        "display_sql": qr.get("display_sql", sql),
        "explanation": explanation,
        "columns": ml_columns,
        "rows": ml_rows,
        "row_count": len(ml_rows),
        "truncated": len(ml_rows) > 500,
        "chart": chart,
        "analysis_mode": "ml",
        "answer_mode": "L3",
    }


def _has_statsmodels() -> bool:
    try:
        import statsmodels  # noqa
        return True
    except ImportError:
        return False



async def run_excel_data_ask(
    db: AsyncSession,
    *,
    source: DataSource,
    question: str,
    user: User | None,
    python_override: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    execute: bool = True,
    skill_style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not source.chat_enabled and execute:
        raise ValueError("Chat Q&A is disabled for this data source")

    ensure_ready(source.id)
    all_tables = get_all_tables(source.id)
    if not all_tables:
        raise ValueError("No Excel files selected for analysis")

    ranked = rank_tables(question, all_tables, top_k=len(all_tables))
    agent_provider, agent_model, agent_goal, agent_backstory = await _resolve_llm(
        db, source, llm_provider, llm_model, spec_override=spec_override
    )
    knobs = _resolve_policy_knobs(source, spec_override)
    memory_examples = await _gather_memory_examples(
        db, data_source_id=source.id, question=question,
        top_k=knobs["memory_top_k"], min_score=knobs["memory_min_score"],
        strong_score=knobs["memory_strong_score"],
        skill_id=(skill_style or {}).get("skill_id") if skill_style else None,
    )
    _, _, semantic, _, _ = await load_source_context(db, source.id)

    if python_override:
        code, explanation = python_override.strip(), "User provided Python"
    else:
        code, explanation = await generate_python(
            db,
            question=question,
            tables=ranked,
            semantic_model=semantic,
            llm_provider=agent_provider,
            llm_model=agent_model,
            memory_examples=memory_examples,
            user_id=user.id if user else None,
            skill_style=skill_style,
        )

    ok, msg = validate_python_code(code)
    if not ok:
        await log_query(
            db,
            user_id=user.id if user else None,
            data_source_id=source.id,
            question=question,
            sql_text=code,
            row_count=0,
            success=False,
            error_message=msg,
        )
        raise ValueError(msg)

    if not execute:
        return {
            "answer": "",
            "sql": code,
            "display_sql": code,
            "explanation": explanation,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "chart": None,
            "generated_only": True,
            "analysis_mode": "python",
        }

    frames = get_all_frames(source.id)
    provenance = build_provenance(list(frames.keys()), frames)
    last_error = ""
    current_code = code
    qr: dict[str, Any] | None = None

    for attempt in range(MAX_PYTHON_RETRIES + 1):
        try:
            qr = run_python_analysis(current_code, frames=frames)
            break
        except Exception as exc:
            last_error = str(exc)
            await log_query(
                db,
                user_id=user.id if user else None,
                data_source_id=source.id,
                question=question,
                sql_text=current_code,
                row_count=0,
                success=False,
                error_message=last_error,
            )
            if attempt >= MAX_PYTHON_RETRIES:
                raise ValueError(last_error) from exc
            current_code, explanation = await repair_python(
                db,
                question=question,
                tables=ranked,
                failed_code=current_code,
                error_message=last_error,
                llm_provider=agent_provider,
                llm_model=agent_model,
                user_id=user.id if user else None,
            )
            ok, msg = validate_python_code(current_code)
            if not ok:
                raise ValueError(msg) from exc

    if qr is None:
        raise ValueError(last_error or "Python analysis failed")

    analysis = await analyze_python_results(
        db,
        question=question,
        code=current_code,
        columns=qr["columns"],
        rows=qr["rows"],
        inline_summary=qr.get("summary") or "",
        llm_provider=llm_provider,
        llm_model=llm_model,
        user_id=user.id if user else None,
        skill_style=skill_style,
    )

    await log_query(
        db,
        user_id=user.id if user else None,
        data_source_id=source.id,
        question=question,
        sql_text=current_code,
        row_count=qr["row_count"],
        success=True,
    )

    chart = _suggest_chart(qr["columns"], qr["rows"], question)
    files_released = await release_ephemeral_excel_workspace(db, source)
    return {
        "answer": analysis,
        "sql": current_code,
        "display_sql": current_code,
        "explanation": explanation,
        "columns": qr["columns"],
        "rows": qr["rows"],
        "row_count": qr["row_count"],
        "truncated": qr["truncated"],
        "chart": chart,
        "analysis_mode": "python",
        "files_released": files_released,
        "provenance": provenance,
        "skill_used": skill_used_brief(skill_style),
    }


async def _align_metrics(
    db: AsyncSession,
    *,
    sql: str,
    explanation: str,
    question: str,
    driver: str,
    tables: list[dict[str, Any]],
    semantic: dict[str, Any] | None,
    llm_provider: str | None,
    llm_model: str | None,
    permission_hint: str,
    join_edges: list[dict[str, str]],
    user_id: str | None,
) -> tuple[str, str]:
    aligned = expand_metric_sql(sql, question, semantic, tables, driver)
    gaps = metric_gaps(question, semantic, aligned, tables)
    if not gaps:
        return aligned, explanation
    fixed, repaired = await repair_sql(
        db,
        question=question,
        driver=driver,
        tables=tables,
        failed_sql=aligned,
        error_message="SQL must use these metric expressions unchanged: " + "; ".join(gaps),
        llm_provider=llm_provider,
        llm_model=llm_model,
        permission_hint=permission_hint,
        join_edges=join_edges,
        semantic_model=semantic,
        user_id=user_id,
    )
    return expand_metric_sql(fixed, question, semantic, tables, driver), repaired or explanation


async def _probe_candidate(
    *,
    source: DataSource,
    sql: str,
    explanation: str,
    question: str,
    semantic: dict[str, Any] | None,
    ranked: list[dict[str, Any]],
    allowed: set[str],
    user: User | None,
    scope: Any,
    apply_perm: bool,
    perm_table: str | None,
    perm_rules: dict[str, str],
) -> dict[str, Any]:
    expanded = expand_metric_sql(sql, question, semantic, ranked, str(source.driver))
    expanded, _date_note = fix_single_day_sql(question, expanded)
    base = {
        "sql": expanded,
        "explanation": explanation,
        "hint_hits": hint_hits(expanded, ranked, question),
        "error": None,
        "row_count": 0,
        "columns": [],
        "rows": [],
        "truncated": False,
        "exec_sql": expanded,
    }
    expanded = disambiguate_subquery_columns(expanded, dialect=str(source.driver))
    ok, msg = validate_select_sql(expanded, allowed_tables=allowed, dialect=str(source.driver))
    if not ok:
        base["error"] = msg
        return base
    col_ok, col_msg = validate_sql_columns(
        expanded,
        semantic_model=semantic,
        user_is_admin=bool(user and user.is_admin),
        scope=scope,
    )
    if not col_ok:
        base["error"] = col_msg
        return base
    # 扇出硬校验：明细级 JOIN 会把客流/客单价放大几千倍，候选直接判负
    rewritten = rewrite_fanout(expanded)
    if rewritten:
        expanded = rewritten
        base["sql"] = expanded
        base["exec_sql"] = expanded
    if detect_fanout(expanded):
        base["error"] = FANOUT_HINT
        return base
    exec_sql = _wrap_permission(expanded, apply_perm, perm_table, perm_rules, user, source)
    base["exec_sql"] = exec_sql
    conn = build_connector_from_source(source)
    try:
        qr = await conn.execute_select(exec_sql)
    except Exception as exc:
        base["error"] = str(exc)
        return base
    finally:
        await conn.close()
    base.update(
        {
            "columns": qr.columns,
            "rows": qr.rows,
            "row_count": qr.row_count,
            "truncated": qr.truncated,
        }
    )
    return base


def _wrap_permission(
    sql: str,
    apply_perm: bool,
    perm_table: str | None,
    perm_rules: dict[str, str],
    user: User | None,
    source: DataSource,
) -> str:
    if not apply_perm or not perm_table:
        return sql
    missing = [k for k in ("user_column", "scope_column", "data_column") if not perm_rules.get(k)]
    if missing:
        raise ValueError(
            f"行级权限配置不完整（缺少 {', '.join(missing)}），已拒绝执行以避免越权取数"
        )
    scope_sql = build_permission_scope_sql(
        user_key=_user_key(user),
        permission_table=perm_table,
        scope_column=perm_rules["scope_column"],
        user_column=perm_rules["user_column"],
        dialect=str(source.driver),
    )
    from app.core.data_ask.govern.sql_guard import disambiguate_subquery_columns
    result = inject_permission_filter(
        sql,
        data_column=perm_rules["data_column"],
        scope_subquery=scope_sql,
        dialect=str(source.driver),
    )
    return disambiguate_subquery_columns(result, dialect=str(source.driver))


async def _execute_with_retry(
    db: AsyncSession,
    *,
    source: DataSource,
    question: str,
    sql: str,
    exec_sql: str,
    ranked: list[dict[str, Any]],
    join_edges: list[dict[str, str]],
    perm_hint: str,
    allowed: set[str],
    semantic: dict[str, Any] | None,
    user: User | None,
    scope: Any,
    agent_provider: str | None,
    agent_model: str | None,
    apply_perm: bool,
    perm_table: str | None,
    perm_rules: dict[str, str],
    max_sql_retries: int | None = None,
) -> dict[str, Any]:
    display_sql = sql
    explanation = ""
    last_error = ""
    current_sql = sql
    # 单日口径硬约束：昨天/今天类提问，多日范围确定性收敛为最新营业日
    current_sql, _date_note = fix_single_day_sql(question, current_sql)
    if current_sql != sql:
        display_sql = current_sql
    # current_exec 必须无条件赋值：SQL 未被 fix_single_day 改写时，
    # 旧代码会跳过赋值导致 UnboundLocalError（指标层规范 SQL 已是收敛形态，必踩）
    current_exec = _wrap_permission(current_sql, apply_perm, perm_table, perm_rules, user, source)
    # P1-A：评估路径可用 spec_override 压低重试上限构造预算点；线上 None=MAX_SQL_RETRIES
    retry_limit = MAX_SQL_RETRIES if max_sql_retries is None else max(0, int(max_sql_retries))
    fanout_fixes = 0  # 扇出修正独立计数，不占用 SQL 执行重试预算

    for attempt in range(retry_limit + 1):
        # 扇出硬校验：执行前拦截明细级 JOIN，强制按「各自预聚合再关联」范式重写
        while detect_fanout(current_sql):
            rewritten = rewrite_fanout(current_sql)
            if rewritten:
                current_sql = rewritten
                display_sql = rewritten
                current_exec = _wrap_permission(
                    rewritten, apply_perm, perm_table, perm_rules, user, source
                )
                explanation = "客流与销售已各自汇总后再关联，避免明细行放大客流"
                continue
            if fanout_fixes >= 2:
                raise ValueError(FANOUT_HINT)
            fanout_fixes += 1
            fixed_sql, explanation = await repair_sql(
                db,
                question=question,
                driver=str(source.driver),
                tables=ranked,
                failed_sql=current_sql,
                error_message=FANOUT_HINT,
                llm_provider=agent_provider,
                llm_model=agent_model,
                permission_hint=perm_hint,
                join_edges=join_edges,
                semantic_model=semantic,
                user_id=user.id if user else None,
            )
            fixed_sql = disambiguate_subquery_columns(fixed_sql, dialect=str(source.driver))
            ok, msg = validate_select_sql(fixed_sql, allowed_tables=allowed, dialect=str(source.driver))
            if not ok:
                raise ValueError(msg)
            col_ok, col_msg = validate_sql_columns(
                fixed_sql,
                semantic_model=semantic,
                user_is_admin=bool(user and user.is_admin),
                scope=scope,
            )
            if not col_ok:
                raise ValueError(col_msg)
            current_sql = fixed_sql
            display_sql = fixed_sql
            current_exec = _wrap_permission(
                fixed_sql, apply_perm, perm_table, perm_rules, user, source
            )
        conn = build_connector_from_source(source)
        try:
            qr = await conn.execute_select(current_exec)
            return {
                "exec_sql": current_exec,
                "display_sql": display_sql,
                "explanation": explanation,
                "columns": qr.columns,
                "rows": qr.rows,
                "row_count": qr.row_count,
                "truncated": qr.truncated,
            }
        except Exception as exc:
            last_error = str(exc)
            await log_query(
                db,
                user_id=user.id if user else None,
                data_source_id=source.id,
                question=question,
                sql_text=current_exec,
                row_count=0,
                success=False,
                error_message=last_error,
            )
            if attempt >= retry_limit:
                raise ValueError(last_error) from exc
            fixed_sql, explanation = await repair_sql(
                db,
                question=question,
                driver=str(source.driver),
                tables=ranked,
                failed_sql=current_sql,
                error_message=last_error,
                llm_provider=agent_provider,
                llm_model=agent_model,
                permission_hint=perm_hint,
                join_edges=join_edges,
                semantic_model=semantic,
                user_id=user.id if user else None,
            )
            fixed_sql = disambiguate_subquery_columns(fixed_sql, dialect=str(source.driver))
            ok, msg = validate_select_sql(fixed_sql, allowed_tables=allowed, dialect=str(source.driver))
            if not ok:
                raise ValueError(msg) from exc
            col_ok, col_msg = validate_sql_columns(
                fixed_sql,
                semantic_model=semantic,
                user_is_admin=bool(user and user.is_admin),
                scope=scope,
            )
            if not col_ok:
                raise ValueError(col_msg) from exc
            current_sql = fixed_sql
            display_sql = fixed_sql
            current_exec = _wrap_permission(fixed_sql, apply_perm, perm_table, perm_rules, user, source)
        finally:
            await conn.close()

    raise ValueError(last_error or "Query failed")


async def run_multi_data_ask(
    db: AsyncSession,
    *,
    data_source_id: str,
    queries: list[dict[str, str]],
    user: User | None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in queries:
        name = item.get("name") or item.get("question") or "query"
        question = str(item.get("question") or name)
        qr = await run_data_ask(
            db,
            data_source_id=data_source_id,
            question=question,
            user=user,
            llm_provider=llm_provider,
            llm_model=llm_model,
            execute=True,
        )
        results.append({"name": name, **qr})
    return results


async def _attach_forecast(
    source_id: str,
    columns: list[str],
    rows: list[list[Any]],
    question: str,
    analysis: str,
    chart: dict[str, Any] | None,
) -> tuple[str, dict[str, Any] | None]:
    if not is_forecast_question(question):
        return analysis, chart
    try:
        from app.core.data_ask.ml_evolution.evolution import forecast_with_production

        info = await forecast_with_production(source_id, columns, rows, question)
    except Exception:
        return analysis, chart
    if not isinstance(info, dict):
        return analysis, chart
    if info.get("ok") and info.get("answer_section"):
        analysis = f"{analysis}\n\n{info['answer_section']}"
        if info.get("chart"):
            chart = info["chart"]
    elif info.get("reason"):
        analysis = f"{analysis}\n\n**模型进化档案**\n{info['reason']}"
    return analysis, chart


async def stream_data_ask(
    db: AsyncSession,
    **kwargs: Any,
) -> AsyncIterator[str]:
    """Yield SQL and the table before the analysis text is written."""
    queue: asyncio.Queue = asyncio.Queue()
    holder: dict[str, Any] = {}

    async def runner() -> None:
        try:
            holder["result"] = await run_data_ask(db, stage_queue=queue, **kwargs)
        except Exception as exc:
            holder["error"] = exc
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())
    while True:
        item = await queue.get()
        if item is None:
            break
        yield json.dumps(item, ensure_ascii=False, default=str) + "\n"
    await task
    if holder.get("error"):
        raise holder["error"]
    result = holder.get("result") or {}
    if result.get("generated_only"):
        yield json.dumps({"event": "done", "generated_only": True}, ensure_ascii=False) + "\n"
        return
    text = str(result.get("answer") or "")
    chunk = 80
    for i in range(0, len(text), chunk):
        yield json.dumps({"event": "token", "token": text[i : i + chunk]}, ensure_ascii=False) + "\n"
    # 从 result 提取图表，emit chart_data 事件（流式图表）
    _charts = result.get("charts")
    if not _charts and result.get("chart"):
        _charts = [_chat_chart(result.get("chart"))] if _chat_chart(result.get("chart")) else None
    for _chart in (_charts or []):
        if _chart:
            yield json.dumps({"chart_data": _chart}, ensure_ascii=False, default=str) + "\n"
    yield json.dumps({"event": "done", "row_count": result.get("row_count", 0), "trace_id": result.get("trace_id"), "memory_hits": int(result.get("memory_hits") or 0), "answer_mode": result.get("answer_mode"), "route": result.get("route"), "confidence": result.get("confidence"), "suggestions": result.get("suggestions") or []}, ensure_ascii=False) + "\n"


def _suggest_chart(columns: list[str], rows: list[list[Any]], question: str = "") -> dict[str, Any] | None:
    return suggest_chart(columns, rows, question)


def _chat_chart(chart: dict[str, Any] | None) -> dict[str, Any] | None:
    if not chart or not chart.get("labels"):
        return None
    datasets = chart.get("datasets") or [{
        "label": chart.get("series") or "value",
        "data": chart.get("values") or [],
    }]
    kind = chart.get("type") if chart.get("type") in {"bar", "line", "pie", "area", "scatter"} else "bar"
    payload: dict[str, Any] = {"type": kind, "labels": chart.get("labels") or [], "datasets": datasets}
    if chart.get("title"):
        payload["title"] = chart["title"]
    if chart.get("horizontal"):
        payload["horizontal"] = True
    return payload


async def _emit(queue: asyncio.Queue | None, payload: dict[str, Any]) -> None:
    if queue is not None:
        await queue.put(payload)


async def _emit_chart_stages(queue: asyncio.Queue | None, chart: dict[str, Any] | None) -> None:
    if not chart:
        return
    await _emit(queue, {"event": "chart", "chart": chart})
    chat = _chat_chart(chart)
    if chat:
        await _emit(queue, {"chart_data": chat})


async def _emit_sql_stages(queue: asyncio.Queue | None, question: str, result: dict[str, Any]) -> None:
    if queue is None:
        return
    standalone = str(result.get("standalone_question") or "")
    if standalone and standalone != (question or ""):
        await _emit(queue, {"event": "rewrite", "question": standalone})
    await _emit(queue, {
        "event": "sql",
        "sql": result.get("sql"),
        "display_sql": result.get("display_sql"),
    })
    if result.get("generated_only"):
        return
    await _emit(queue, {
        "event": "table",
        "columns": result.get("columns") or [],
        "rows": (result.get("rows") or [])[:100],
    })
    await _emit_chart_stages(queue, result.get("chart"))
