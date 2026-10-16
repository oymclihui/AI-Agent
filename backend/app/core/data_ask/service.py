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
)
from app.core.data_ask.govern.sql_guard import validate_select_sql
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
from app.core.data_ask.intelligence.nl2sql import analyze_results, generate_sql, generate_sql_candidates, repair_sql
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


async def _resolve_relative_time(
    source: DataSource,
    all_tables: list[dict[str, Any]] | None,
    question: str,
) -> str:
    """把问题中的相对时间（「最近3天」「昨天」等）解析为具体日期，锚定数据最新日期。

    缺少可用的日期列、取不到最新日期或解析失败时，原样返回问题（不引入错误口径）。
    """
    from datetime import date, timedelta

    text = (question or "").strip()
    if not text:
        return question
    window = _RE_REL_WINDOW.search(text)
    day_off = next((off for kw, off in _RE_REL_DAY.items() if kw in text), None)
    if not window and day_off is None:
        return question

    anchor: tuple[str, str] | None = None
    for table in all_tables or []:
        for column in table.get("columns") or []:
            name = str(column.get("name") if isinstance(column, dict) else column)
            col_type = str(column.get("type") if isinstance(column, dict) else "").lower()
            if any(token in col_type for token in ("date", "time")):
                anchor = (str(table.get("table_name")), name)
                break
        if anchor:
            break
    if not anchor:
        return question

    try:
        conn = build_connector_from_source(source)
        try:
            qr = await conn.execute_select(f"SELECT MAX({anchor[1]}) FROM {anchor[0]}", limit=1)
        finally:
            await conn.close()
    except Exception:
        return question
    if not qr.rows or qr.rows[0][0] is None:
        return question
    raw = str(qr.rows[0][0])
    try:
        latest = date(int(raw[:4]), int(raw[5:7]), int(raw[8:10]))
    except Exception:
        return question

    if window:
        count = _count_of(window.group(1))
        unit = window.group(2)
        if not count or count <= 0:
            return question
        if unit in ("天", "日"):
            start = latest - timedelta(days=count - 1)
        elif unit == "周":
            start = latest - timedelta(days=count * 7 - 1)
        elif unit == "月":
            total = latest.year * 12 + (latest.month - 1) - count
            year, month = divmod(total, 12)
            start = date(year, month + 1, 1)
        else:
            start = date(latest.year - count, latest.month, 1)
        phrase = window.group(0)
    else:
        start = latest - timedelta(days=day_off or 0)
        phrase = next(kw for kw, off in _RE_REL_DAY.items() if off == day_off)

    if start > latest:
        return question
    resolved = latest.isoformat() if start == latest else f"{start.isoformat()} 至 {latest.isoformat()}"
    return f"{text}（其中「{phrase}」指 {resolved}，数据最新日期为 {latest.isoformat()}）"


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
    join_graph = infer_join_graph(
        [
            {
                "table_name": m["table_name"],
                "columns": m.get("columns") or [],
            }
            for m in table_meta
        ]
    )
    perm_name = perm_table.table_name if perm_table else None
    return source, table_meta, source.semantic_model, perm_name, join_graph.get("edges") or []


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
) -> list[dict[str, Any]]:
    """问数记忆：golden queries（词面相似）+ 蒸馏示例库（向量相似，阶段二 L2）合并。"""
    try:
        from app.core.data_ask.distill.example_store import gather_memory_examples as _gather

        return await _gather(
            db, data_source_id=data_source_id, question=question, top_k=top_k,
            min_score=min_score, strong_score=strong_score,
        )
    except Exception:
        from app.core.data_ask.intelligence.query_memory import retrieve_similar_queries

        kwargs: dict[str, Any] = {}
        if min_score is not None:
            kwargs["min_score"] = float(min_score)
        return await retrieve_similar_queries(
            db, data_source_id=data_source_id, question=question, top_k=top_k, **kwargs
        )


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
) -> dict[str, Any]:
    _t_start = time.monotonic()
    source = await db.get(DataSource, data_source_id)
    if not source:
        raise ValueError("Data source not found")
    agent_provider, agent_model, agent_goal, agent_backstory = await _resolve_llm(
        db, source, llm_provider, llm_model, spec_override=spec_override,
    )
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
    if history and not sql_override:
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
        )

    source, all_tables, semantic, perm_table, join_edges = await load_source_context(db, data_source_id)
    semantic, _profile_lookup = await load_ds_semantic(db, data_source_id, semantic)
    enrich_table_meta_with_profile(all_tables, _profile_lookup)
    if not source.chat_enabled and execute:
        raise ValueError("Chat Q&A is disabled for this data source")

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
            return await run_overview_analysis(
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
            )

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

    memory_examples = (
        await _gather_memory_examples(
            db, data_source_id=data_source_id, question=standalone,
            top_k=knobs["memory_top_k"], min_score=knobs["memory_min_score"],
            strong_score=knobs["memory_strong_score"],
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
    })

    _t_gen = time.monotonic()
    voted_qr: dict[str, Any] | None = None
    if sql_override:
        sql, explanation = sql_override.strip(), "User provided SQL"
        _tree_add(trace_marks, "candidate", intent_id, {
            "index": 0, "mode": "override",
            "sql": sql[:8000], "explanation": explanation[:500],
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
    if voted_qr is None:
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
    analysis = await analyze_results(
        db,
        question=standalone,
        sql=qr["exec_sql"],
        columns=qr["columns"],
        rows=qr["rows"],
        chart=chart,
        llm_provider=agent_provider,
        llm_model=agent_model,
        user_id=user.id if user else None,
        agent_goal=agent_goal,
        agent_backstory=agent_backstory,
    )
    analysis, next_chart = await _attach_forecast(
        str(source.id), qr["columns"], qr["rows"], standalone, analysis, chart
    )
    if trace_marks is not None:
        trace_marks["analysis_ms"] = int((time.monotonic() - _t_ana) * 1000)
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
        "standalone_question": standalone,
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
    marks: dict[str, int] | None = None,
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
            memory_hits=int(m.get("memory_hits") or 0),
            duration_ms=duration_ms,
            rewrite_ms=m.get("rewrite_ms"),
            gen_ms=m.get("gen_ms"),
            exec_ms=m.get("exec_ms"),
            analysis_ms=m.get("analysis_ms"),
            result_signature=sig,
            clarification=bool(r.get("clarification")),
            cached=cached,
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
    perm_rules = permission_config_from_rules(source.permission_rules) if hasattr(source, 'permission_rules') and source.permission_rules else {}
    apply_perm = bool(perm_table and scope)
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
            "chart": None, "analysis_mode": "ml",
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
    scope_sql = build_permission_scope_sql(
        user_key=_user_key(user),
        permission_table=perm_table,
        scope_column=perm_rules["scope_column"],
        user_column=perm_rules["user_column"],
        dialect=str(source.driver),
    )
    return inject_permission_filter(
        sql,
        data_column=perm_rules["data_column"],
        scope_subquery=scope_sql,
        dialect=str(source.driver),
    )


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
    current_exec = exec_sql
    # P1-A：评估路径可用 spec_override 压低重试上限构造预算点；线上 None=MAX_SQL_RETRIES
    retry_limit = MAX_SQL_RETRIES if max_sql_retries is None else max(0, int(max_sql_retries))

    for attempt in range(retry_limit + 1):
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
    yield json.dumps({"event": "done", "row_count": result.get("row_count", 0), "trace_id": result.get("trace_id"), "memory_hits": int(result.get("memory_hits") or 0)}, ensure_ascii=False) + "\n"


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
