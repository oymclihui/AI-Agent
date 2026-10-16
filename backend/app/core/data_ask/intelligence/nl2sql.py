"""NL → SQL via LLM."""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.intelligence.query_memory import format_memory_prompt
from app.core.data_ask.experience.chart_profile import chart_facts
from app.core.data_ask.experience.ground_analysis import (
    EMPTY_FALLBACK,
    format_allowed_numbers,
    ground_analysis,
    tidy_numbers,
)
from app.core.data_ask.intelligence.value_link import format_value_hints
from app.core.data_ask.semantic.mdl import (
    expand_metrics_in_prompt,
    format_semantic_context,
    format_terms_context,
)
from app.models_hub.router import ModelRouter

# 比率 / 人均类指标必须用聚合相除表达，不能直接 SUM 一个相关列。
# 否则「毛利率」会被生成成 SUM(ML)（毛利金额），与用户所问口径不符。
_RATIO_RULE = (
    "When the question asks for a rate, ratio or per-unit metric "
    "(毛利率, 净利率, 占比, 转化率, 客单价, 同比/环比, 折扣率 等) and no exact expression "
    "is defined in the semantic context, express it as a ratio of aggregates, e.g. "
    "毛利率 = ROUND(SUM(ML) / SUM(XSJE) * 100, 2). "
    "Never answer a rate question with a plain SUM of a related column.\n"
)

# 问题里出现的具体日期/月份必须原样用于筛选，不能用样本值顶替。
_DATE_RULE = (
    "When the question contains a concrete date or month "
    "(e.g. 10月10日, 2026年10月), filter on that exact value. "
    "For a DATE/DATETIME column use a range or equality, e.g. "
    "RQ >= '2026-10-01' AND RQ <= '2026-10-31' for 10月, "
    "RQ = '2026-10-10' for 10月10日. "
    "If the question omits the year, take the year from the newest dates shown in the "
    "sample rows or partition values, never from an earlier year: with sample rows dated "
    "2026-10-11, the question 10月 means 2026-10, not 2024-10. "
    "Never substitute the sample values shown in the schema for the date asked about.\n"
)


def _schema_prompt(tables: list[dict[str, Any]], driver: str, join_edges: list[dict[str, str]] | None = None) -> str:
    dialect = driver
    if driver == "doris":
        dialect = "Apache Doris (MySQL-compatible SQL)"
    elif driver in ("mysql", "starrocks"):
        dialect = "MySQL-compatible SQL (StarRocks uses the MySQL protocol)"
    elif driver == "vastbase":
        dialect = "Vastbase (PostgreSQL-compatible SQL)"
    elif driver == "hana":
        dialect = "SAP HANA SQL"
    parts = [f"Database dialect: {dialect}", "Schema:"]
    for t in tables:
        parts.append(f"# Table {t['table_name']}")
        if t.get("partition_columns"):
            parts.append(f"  Partitions: {', '.join(t['partition_columns'])}")
        for col in t.get("columns") or []:
            parts.append("  " + _column_line(col))
        samples = t.get("sample_rows") or []
        if samples:
            parts.append(f"  Sample rows: {json.dumps(samples[:3], ensure_ascii=False, default=str)}")
        jk = t.get("join_keys") or {}
        if jk:
            parts.append(f"  Join hints: {json.dumps(jk, ensure_ascii=False)}")
    if join_edges:
        edge_txt = "; ".join(
            f"{e['from']}.{e.get('from_column') or e.get('label', '?')} = {e['to']}.{e.get('to_column') or e.get('label', '?')}"
            for e in join_edges[:8]
        )
        parts.append(f"Suggested joins: {edge_txt}")
    return "\n".join(parts)


def _column_line(col: Any) -> str:
    if not isinstance(col, dict):
        return str(col)
    name = str(col.get("name") or "")
    dtype = str(col.get("type") or "")
    line = f"{name} {dtype}".rstrip()
    comment = str(col.get("comment") or col.get("description") or "").strip()
    if comment:
        line += f" -- {comment}"
    examples = [str(v) for v in (col.get("examples") or [])[:6]]
    if examples:
        line += " 示例: " + ", ".join(examples)
    return line


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
        "When a metric name appears in the question, copy its expression unchanged.\n"
        "When a value hint names a column value, filter with that exact value.\n"
        f"{_RATIO_RULE}"
        f"{_DATE_RULE}"
        "Return JSON: {\"sql\": \"...\", \"explanation\": \"...\"}\n"
    )
    user = _sql_user_prompt(
        question=question,
        driver=driver,
        tables=tables,
        semantic_model=semantic_model,
        permission_hint=permission_hint,
        memory_examples=memory_examples,
        join_edges=join_edges,
    )
    return await _invoke_sql_llm(
        db, system=system, user=user, llm_provider=llm_provider, llm_model=llm_model, user_id=user_id
    )


async def generate_sql_candidates(
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
) -> list[tuple[str, str]]:
    """One model call returning up to two different SELECT statements."""
    system = (
        "You are a senior data analyst. The question may match more than one table.\n"
        "Return two different read-only SELECT queries. Use different tables or filters.\n"
        "Rules: SELECT or WITH only; no DDL/DML; use correct dialect; prefer explicit column names.\n"
        "When a metric name appears in the question, copy its expression unchanged.\n"
        "When a value hint names a column value, filter with that exact value.\n"
        f"{_RATIO_RULE}"
        f"{_DATE_RULE}"
        "Return JSON: {\"candidates\": [{\"sql\": \"...\", \"explanation\": \"...\"}, {\"sql\": \"...\", \"explanation\": \"...\"}]}\n"
    )
    user = _sql_user_prompt(
        question=question,
        driver=driver,
        tables=tables,
        semantic_model=semantic_model,
        permission_hint=permission_hint,
        memory_examples=memory_examples,
        join_edges=join_edges,
    )
    text = await _invoke_text(
        db, system=system, user=user, llm_provider=llm_provider, llm_model=llm_model, user_id=user_id
    )
    pairs = parse_sql_response(text)[:2]
    if pairs:
        return pairs
    one = await generate_sql(
        db,
        question=question,
        driver=driver,
        tables=tables,
        semantic_model=semantic_model,
        llm_provider=llm_provider,
        llm_model=llm_model,
        permission_hint=permission_hint,
        memory_examples=memory_examples,
        join_edges=join_edges,
        user_id=user_id,
    )
    return [one]


def _sql_user_prompt(
    *,
    question: str,
    driver: str,
    tables: list[dict[str, Any]],
    semantic_model: dict[str, Any] | None,
    permission_hint: str,
    memory_examples: list[dict[str, Any]] | None,
    join_edges: list[dict[str, str]] | None,
) -> str:
    return (
        f"{format_semantic_context(semantic_model)}"
        f"{expand_metrics_in_prompt(semantic_model)}"
        f"{format_terms_context(semantic_model)}"
        f"{format_memory_prompt(memory_examples or [])}"
        f"{format_value_hints(question, tables)}"
        f"{_schema_prompt(tables, driver, join_edges)}\n"
        f"{permission_hint}\n"
        f"Question: {question}"
    )


def parse_sql_response(text: str) -> list[tuple[str, str]]:
    data = None
    try:
        match = re.search(r"\{[\s\S]*\}", text or "")
        if match:
            data = json.loads(match.group())
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict) and isinstance(data.get("candidates"), list):
        pairs: list[tuple[str, str]] = []
        for item in data["candidates"]:
            if isinstance(item, dict) and str(item.get("sql") or "").strip():
                pairs.append((str(item["sql"]).strip(), str(item.get("explanation") or "")))
        if pairs:
            return pairs
    if isinstance(data, dict) and str(data.get("sql") or "").strip():
        return [(str(data["sql"]).strip(), str(data.get("explanation") or ""))]
    sql_match = re.search(r"```sql?\s*([\s\S]*?)```", text or "", re.IGNORECASE)
    if sql_match:
        return [(sql_match.group(1).strip(), text or "")]
    stripped = (text or "").strip()
    if stripped.upper().startswith("SELECT") or stripped.upper().startswith("WITH"):
        return [(stripped, "")]
    return []


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
    semantic_model: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> tuple[str, str]:
    system = (
        "You fix broken SQL queries. Return JSON: {\"sql\": \"...\", \"explanation\": \"...\"}\n"
        "Only SELECT/WITH; fix syntax/dialect/table/column errors based on the error message.\n"
        "Keep metric expressions from the semantic definitions when they still match the question."
    )
    user = (
        f"{format_semantic_context(semantic_model)}"
        f"{expand_metrics_in_prompt(semantic_model)}"
        f"{format_terms_context(semantic_model)}"
        f"{format_value_hints(question, tables)}"
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
        response_style="precise",
    )
    resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    pairs = parse_sql_response(text)
    if pairs:
        return pairs[0]
    return text.strip(), ""


async def _invoke_text(
    db: AsyncSession,
    *,
    system: str,
    user: str,
    llm_provider: str | None,
    llm_model: str | None,
    user_id: str | None = None,
) -> str:
    llm = await ModelRouter.get_llm(
        db=db,
        provider=llm_provider,
        model=llm_model,
        user_id=user_id,
        response_style="precise",
    )
    resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    return resp.content if isinstance(resp.content, str) else str(resp.content)


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
    chart: dict[str, Any] | None = None,
    agent_goal: str | None = None,
    agent_backstory: str | None = None,
) -> str:
    preview_rows = rows[:30]
    data_text = json.dumps(
        {"columns": columns, "rows": preview_rows, "total_rows": len(rows)},
        ensure_ascii=False,
        default=str,
    )
    facts = chart_facts(chart)
    system = """你是一位资深零售数据分析师，为业务同事撰写问数结论。只解释已经查出来、并且画在图里的实际数据。

排版要求（Markdown，务必简洁）：
1. 首句用一句完整的话直接回答问题并给出关键数值，关键数字用 **加粗**（不要只输出一个加粗数字）。用户只要一个数时，一句话说清即可，不要建表格。
2. 有分组结果时，用一个 Markdown 表格呈现：列名简短并带单位。按数值从大到小排列；结果多于 10 行时只列前 10 行，并在表格上方注明「共 N 行，展示前 10 行」。
3. 随后用无序列表写 2-4 条要点，每条都要落到结果里的某个具体数值或对比（最高/最低、差距、集中的分组等）。
4. 结果里存在数值指标（销售额、毛利、数量等）且确实支持改进行动时，才补一节「建议」，最多 2 条，每条都要落到结果里的具体数值；结果只有文本列或只有一个数时，不写建议。

硬性约束：
- 只能引用「可用数字」里出现过的数值，并且必须原样引用：禁止四舍五入，禁止换算成万元/亿元（例如写 285987.4487 元，不要写成 28.60 万元），禁止自行计算占比、环比、同比、合计、均值等派生量。
- 结果只有文本列（商品名、SKU 等）而没有数值指标列时，只客观陈述结果（例如「共 N 个商品符合条件」并用表格罗列），不要从文本里的数字（如 500ml、150g、4粒装）推断规格含义或下结论。
- 结果只给出了部分行（total_rows 大于展示行数）时，不要下「最高/最低/全部/合计」这类全局结论，只描述实际给出的行。
- 禁止编造结果里没有的维度。
- 不要写「结果中未提供 X，无法分析」这类凑数句子；没有内容的小节直接省略，不要留空标题。"""
    if agent_goal:
        system = (
            "【分析职责与要求】\n" + agent_goal + "\n\n"
            + system
        )
    if agent_backstory:
        system = system + "\n\n【数据背景与先验知识】\n" + agent_backstory + "\n（以上背景供参考，分析时以实际查询结果为准）"
    user = (
        f"问题: {question}\nSQL: {sql}\n结果: {data_text}\n"
        f"{format_allowed_numbers(preview_rows)}"
        f"图中实际数据: {facts or '这次没有图，只根据结果表解释。'}\n"
    )
    llm = await ModelRouter.get_llm(
        db=db,
        provider=llm_provider,
        model=llm_model,
        user_id=user_id,
        response_style="precise",
    )
    resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    text = tidy_numbers(ground_analysis(text, preview_rows))
    if text == EMPTY_FALLBACK:
        text = _fallback_answer(columns, rows)
    if facts:
        text = f"**图中数据**\n{facts}\n\n{text}"
    return text


def _cell_text(value: Any) -> str:
    return "" if value is None else str(value)


def _fallback_answer(columns: list[str], rows: list[list[Any]]) -> str:
    """护栏把结论整段清空时，直接用结果表拼一份确定性文案，绝不留空。"""
    cols = [str(col) for col in (columns or [])]
    data = rows or []
    if not data:
        return "查询没有返回数据行。"
    if len(data) == 1 and len(cols) <= 1:
        name = cols[0] if cols else "结果"
        return f"{name}为 **{_cell_text(data[0][0])}**。"
    if len(data) == 1:
        items = "；".join(
            f"{cols[idx] if idx < len(cols) else f'列{idx + 1}'}：{_cell_text(value)}"
            for idx, value in enumerate(data[0])
        )
        return items + "。"
    head = cols or [f"列{idx + 1}" for idx in range(len(data[0]))]
    lines = [
        "| " + " | ".join(head) + " |",
        "| " + " | ".join(["---"] * len(head)) + " |",
    ]
    for row in data[:10]:
        lines.append("| " + " | ".join(_cell_text(value) for value in row) + " |")
    note = f"共 {len(data)} 行，展示前 10 行。" if len(data) > 10 else f"共 {len(data)} 行。"
    return note + "\n\n" + "\n".join(lines)
