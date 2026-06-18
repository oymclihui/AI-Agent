"""End-to-end data ask query pipeline."""
from __future__ import annotations

import json
import re
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
from app.core.data_ask.analysis.python_runner import load_frames, run_python_analysis, validate_python_code
from app.core.data_ask.excel.retention import release_ephemeral_excel_workspace
from app.core.data_ask.intelligence.nlpython import analyze_python_results, generate_python, repair_python
from app.core.data_ask.intelligence.nl2sql import analyze_results, generate_sql, repair_sql
from app.core.data_ask.intelligence.query_memory import retrieve_similar_queries
from app.core.data_ask.intelligence.schema_retriever import rank_tables
from app.core.data_ask.schema.introspect import infer_join_graph, introspect_tables
from app.db.models import DataSource, DataSourceTable, DataSourceTableRole, User

MAX_SQL_RETRIES = 2
MAX_PYTHON_RETRIES = 2
SCHEMA_TOP_K = 5


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
) -> tuple[str | None, str | None]:
    agent_provider = llm_provider
    agent_model = llm_model
    if source.agent_id:
        from app.db.models import Agent as AgentModel

        agent = await db.get(AgentModel, source.agent_id)
        if agent:
            agent_provider = agent_provider or agent.llm_provider
            agent_model = agent_model or agent.llm_model
    return agent_provider, agent_model


async def run_data_ask(
    db: AsyncSession,
    *,
    data_source_id: str,
    question: str,
    user: User | None,
    sql_override: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    execute: bool = True,
) -> dict[str, Any]:
    source = await db.get(DataSource, data_source_id)
    if not source:
        raise ValueError("Data source not found")
    if str(source.driver) == "excel_folder":
        return await run_excel_data_ask(
            db,
            source=source,
            question=question,
            user=user,
            python_override=sql_override,
            llm_provider=llm_provider,
            llm_model=llm_model,
            execute=execute,
        )

    source, all_tables, semantic, perm_table, join_edges = await load_source_context(db, data_source_id)
    if not source.chat_enabled and execute:
        raise ValueError("Chat Q&A is disabled for this data source")

    scope = await resolve_data_scope(db, user) if user else None
    ranked = rank_tables(question, all_tables, top_k=SCHEMA_TOP_K)
    allowed = {t["table_name"] for t in all_tables}
    if perm_table:
        allowed.add(perm_table)

    perm_rules = permission_config_from_rules(source.permission_rules)
    apply_perm = bool(perm_table) and not bypass_row_permission(user, scope)
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

    agent_provider, agent_model = await _resolve_llm(db, source, llm_provider, llm_model)
    memory_examples = await retrieve_similar_queries(db, data_source_id=data_source_id, question=question)

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
            permission_hint=perm_hint,
            memory_examples=memory_examples,
            join_edges=join_edges,
            user_id=user.id if user else None,
        )

    ok, msg = validate_select_sql(sql, allowed_tables=allowed)
    if not ok:
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
        return {
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
        }

    exec_sql = _wrap_permission(sql, apply_perm, perm_table, perm_rules, user, source)
    qr = await _execute_with_retry(
        db,
        source=source,
        question=question,
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
    )

    analysis = await analyze_results(
        db,
        question=question,
        sql=qr["exec_sql"],
        columns=qr["columns"],
        rows=qr["rows"],
        llm_provider=llm_provider,
        llm_model=llm_model,
        user_id=user.id if user else None,
    )

    await log_query(
        db,
        user_id=user.id if user else None,
        data_source_id=data_source_id,
        question=question,
        sql_text=qr["exec_sql"],
        row_count=qr["row_count"],
        success=True,
    )

    chart = _suggest_chart(qr["columns"], qr["rows"])
    return {
        "answer": analysis,
        "sql": qr["exec_sql"],
        "display_sql": qr["display_sql"],
        "explanation": qr.get("explanation") or explanation,
        "columns": qr["columns"],
        "rows": qr["rows"],
        "row_count": qr["row_count"],
        "truncated": qr["truncated"],
        "chart": chart,
        "analysis_mode": "sql",
    }


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

    _, all_tables, semantic, _, _ = await load_source_context(db, source.id)
    if not all_tables:
        raise ValueError("No Excel files selected for analysis")

    ranked = rank_tables(question, all_tables, top_k=SCHEMA_TOP_K)
    filenames = [t["table_name"] for t in ranked]
    agent_provider, agent_model = await _resolve_llm(db, source, llm_provider, llm_model)
    memory_examples = await retrieve_similar_queries(db, data_source_id=source.id, question=question)

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

    frames = load_frames(source.id, filenames)
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

    chart = _suggest_chart(qr["columns"], qr["rows"])
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
    }


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
) -> dict[str, Any]:
    display_sql = sql
    explanation = ""
    last_error = ""
    current_sql = sql
    current_exec = exec_sql

    for attempt in range(MAX_SQL_RETRIES + 1):
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
            if attempt >= MAX_SQL_RETRIES:
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
                user_id=user.id if user else None,
            )
            ok, msg = validate_select_sql(fixed_sql, allowed_tables=allowed)
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


async def stream_data_ask(
    db: AsyncSession,
    **kwargs: Any,
) -> AsyncIterator[str]:
    result = await run_data_ask(db, **kwargs)
    yield json.dumps({"event": "sql", "sql": result["sql"], "display_sql": result.get("display_sql")}, ensure_ascii=False) + "\n"
    if result.get("generated_only"):
        yield json.dumps({"event": "done", "generated_only": True}, ensure_ascii=False) + "\n"
        return
    yield json.dumps({"event": "table", "columns": result["columns"], "rows": result["rows"][:100]}, ensure_ascii=False, default=str) + "\n"
    if result.get("chart"):
        yield json.dumps({"event": "chart", "chart": result["chart"]}, ensure_ascii=False) + "\n"
    text = result["answer"]
    chunk = 80
    for i in range(0, len(text), chunk):
        yield json.dumps({"event": "token", "token": text[i : i + chunk]}, ensure_ascii=False) + "\n"
    yield json.dumps({"event": "done", "row_count": result["row_count"]}, ensure_ascii=False) + "\n"


def _suggest_chart(columns: list[str], rows: list[list[Any]]) -> dict[str, Any] | None:
    if not columns or not rows or len(columns) < 2:
        return None
    cat_idx = 0
    num_idx = next((i for i, c in enumerate(columns) if i > 0), 1)
    labels = [str(r[cat_idx]) for r in rows[:12]]
    values = []
    for r in rows[:12]:
        try:
            values.append(float(r[num_idx]))
        except (TypeError, ValueError):
            values.append(0)
    return {"type": "bar", "labels": labels, "values": values, "series": columns[num_idx]}
