"""NL → SQL via LLM."""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.intelligence.query_memory import format_memory_prompt
from app.core.data_ask.semantic.mdl import expand_metrics_in_prompt, format_semantic_context
from app.models_hub.router import ModelRouter


def _schema_prompt(tables: list[dict[str, Any]], driver: str, join_edges: list[dict[str, str]] | None = None) -> str:
    dialect = driver
    if driver == "doris":
        dialect = "Apache Doris (MySQL-compatible SQL)"
    if driver == "hana":
        dialect = "SAP HANA SQL"
    parts = [f"Database dialect: {dialect}"]
    for t in tables:
        cols = ", ".join(
            f"{c['name']}({c['type']})" if isinstance(c, dict) else str(c)
            for c in (t.get("columns") or [])
        )
        parts.append(f"Table {t['table_name']}: {cols}")
        if t.get("partition_columns"):
            parts.append(f"  Partitions: {', '.join(t['partition_columns'])}")
        samples = t.get("sample_rows") or []
        if samples:
            parts.append(f"  Sample rows (up to 3): {json.dumps(samples[:3], ensure_ascii=False, default=str)}")
        jk = t.get("join_keys") or {}
        if jk:
            parts.append(f"  Join hints: {json.dumps(jk, ensure_ascii=False)}")
    if join_edges:
        edge_txt = "; ".join(f"{e['from']}.{e.get('label', '?')} -> {e['to']}" for e in join_edges[:6])
        parts.append(f"Suggested joins: {edge_txt}")
    return "\n".join(parts)


async def generate_sql(
    db: AsyncSession,
    *,
    question: str,
    driver: str,
    tables: list[dict[str, Any]],
    semantic_model: dict[str, Any] | None,
    llm_provider: str | None,
    llm_model: str | None,
    permission_hint: str = "",
    memory_examples: list[dict[str, Any]] | None = None,
    join_edges: list[dict[str, str]] | None = None,
    user_id: str | None = None,
) -> tuple[str, str]:
    """Return (sql, explanation)."""
    system = (
        "You are a senior data analyst. Generate a single read-only SELECT query.\n"
        "Rules: SELECT or WITH only; no DDL/DML; use correct dialect; prefer explicit column names.\n"
        "Return JSON: {\"sql\": \"...\", \"explanation\": \"...\"}\n"
    )
    user = (
        f"{format_semantic_context(semantic_model)}"
        f"{expand_metrics_in_prompt(semantic_model)}"
        f"{format_memory_prompt(memory_examples or [])}"
        f"{_schema_prompt(tables, driver, join_edges)}\n"
        f"{permission_hint}\n"
        f"Question: {question}"
    )
    return await _invoke_sql_llm(
        db, system=system, user=user, llm_provider=llm_provider, llm_model=llm_model, user_id=user_id
    )


async def repair_sql(
    db: AsyncSession,
    *,
    question: str,
    driver: str,
    tables: list[dict[str, Any]],
    failed_sql: str,
    error_message: str,
    llm_provider: str | None,
    llm_model: str | None,
    permission_hint: str = "",
    join_edges: list[dict[str, str]] | None = None,
    user_id: str | None = None,
) -> tuple[str, str]:
    system = (
        "You fix broken SQL queries. Return JSON: {\"sql\": \"...\", \"explanation\": \"...\"}\n"
        "Only SELECT/WITH; fix syntax/dialect/table/column errors based on the error message."
    )
    user = (
        f"{_schema_prompt(tables, driver, join_edges)}\n"
        f"{permission_hint}\n"
        f"Question: {question}\n"
        f"Failed SQL:\n{failed_sql}\n"
        f"Error: {error_message}\n"
        "Provide corrected SQL."
    )
    return await _invoke_sql_llm(
        db, system=system, user=user, llm_provider=llm_provider, llm_model=llm_model, user_id=user_id
    )


async def _invoke_sql_llm(
    db: AsyncSession,
    *,
    system: str,
    user: str,
    llm_provider: str | None,
    llm_model: str | None,
    user_id: str | None = None,
) -> tuple[str, str]:
    llm = await ModelRouter.get_llm(
        db=db,
        provider=llm_provider,
        model=llm_model,
        user_id=user_id,
        temperature=0.2,
    )
    resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    try:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            data = json.loads(m.group())
            return str(data.get("sql") or "").strip(), str(data.get("explanation") or "")
    except json.JSONDecodeError:
        pass
    sql_match = re.search(r"```sql?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if sql_match:
        return sql_match.group(1).strip(), text
    return text.strip(), ""


async def analyze_results(
    db: AsyncSession,
    *,
    question: str,
    sql: str,
    columns: list[str],
    rows: list[list[Any]],
    llm_provider: str | None,
    llm_model: str | None,
    user_id: str | None = None,
) -> str:
    preview_rows = rows[:30]
    data_text = json.dumps({"columns": columns, "rows": preview_rows}, ensure_ascii=False, default=str)
    system = "你是数据分析顾问。根据查询结果用中文回答用户问题，给出结论与建议。简洁专业。"
    user = f"问题: {question}\nSQL: {sql}\n结果: {data_text}"
    llm = await ModelRouter.get_llm(
        db=db,
        provider=llm_provider,
        model=llm_model,
        user_id=user_id,
        temperature=0.3,
    )
    resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    return resp.content if isinstance(resp.content, str) else str(resp.content)
