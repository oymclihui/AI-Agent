"""NL → Python for Excel folder data ask."""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.intelligence.nl2sql import _schema_prompt
from app.core.data_ask.intelligence.query_memory import format_memory_prompt
from app.core.data_ask.semantic.mdl import expand_metrics_in_prompt, format_semantic_context
from app.models_hub.router import ModelRouter


def _python_rules() -> str:
    ml = (
        "You may use pandas, numpy, and scikit-learn (LinearRegression, KMeans, PCA, StandardScaler) "
        "for statistics, forecasting, clustering, and classification when the question requires it."
        if True
        else ""
    )
    return (
        "You are a senior data analyst. Generate Python code to answer the question using pre-loaded DataFrames.\n"
        "Rules:\n"
        "- Variable `frames` is a dict: filename -> pandas DataFrame (e.g. frames['sales.xlsx']).\n"
        "- Do NOT import modules, read files, or access network/OS.\n"
        "- Assign `result` as a dict: {\"columns\": [...], \"rows\": [[...]], \"summary\": \"...\"} "
        "OR assign `result` as a pandas DataFrame.\n"
        f"- {ml}\n"
        "Return JSON: {\"python\": \"...\", \"explanation\": \"...\"}\n"
    )


async def generate_python(
    db: AsyncSession,
    *,
    question: str,
    tables: list[dict[str, Any]],
    semantic_model: dict[str, Any] | None,
    llm_provider: str | None,
    llm_model: str | None,
    memory_examples: list[dict[str, Any]] | None = None,
    user_id: str | None = None,
) -> tuple[str, str]:
    system = _python_rules()
    user = (
        f"{format_semantic_context(semantic_model)}"
        f"{expand_metrics_in_prompt(semantic_model)}"
        f"{format_memory_prompt(memory_examples or [])}"
        f"{_schema_prompt(tables, 'excel_folder')}\n"
        f"Question: {question}"
    )
    return await _invoke_python_llm(
        db, system=system, user=user, llm_provider=llm_provider, llm_model=llm_model, user_id=user_id
    )


async def repair_python(
    db: AsyncSession,
    *,
    question: str,
    tables: list[dict[str, Any]],
    failed_code: str,
    error_message: str,
    llm_provider: str | None,
    llm_model: str | None,
    user_id: str | None = None,
) -> tuple[str, str]:
    system = _python_rules() + "Fix the broken Python based on the error message.\n"
    user = (
        f"{_schema_prompt(tables, 'excel_folder')}\n"
        f"Question: {question}\n"
        f"Failed code:\n{failed_code}\n"
        f"Error: {error_message}\n"
        "Provide corrected Python."
    )
    return await _invoke_python_llm(
        db, system=system, user=user, llm_provider=llm_provider, llm_model=llm_model, user_id=user_id
    )


async def _invoke_python_llm(
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
    try:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            data = json.loads(m.group())
            code = str(data.get("python") or data.get("code") or "").strip()
            return code, str(data.get("explanation") or "")
    except json.JSONDecodeError:
        pass
    py_match = re.search(r"```python\s*([\s\S]*?)```", text, re.IGNORECASE)
    if py_match:
        return py_match.group(1).strip(), text
    return text.strip(), ""


async def analyze_python_results(
    db: AsyncSession,
    *,
    question: str,
    code: str,
    columns: list[str],
    rows: list[list[Any]],
    inline_summary: str,
    llm_provider: str | None,
    llm_model: str | None,
    user_id: str | None = None,
) -> str:
    if inline_summary.strip():
        return inline_summary
    preview_rows = rows[:30]
    data_text = json.dumps({"columns": columns, "rows": preview_rows}, ensure_ascii=False, default=str)
    system = "你是数据分析顾问。根据 Python 分析结果用中文回答用户问题，给出结论与建议。简洁专业。"
    user = f"问题: {question}\nPython:\n{code}\n结果: {data_text}"
    llm = await ModelRouter.get_llm(
        db=db,
        provider=llm_provider,
        model=llm_model,
        user_id=user_id,
        response_style="precise",
    )
    resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    return resp.content if isinstance(resp.content, str) else str(resp.content)
