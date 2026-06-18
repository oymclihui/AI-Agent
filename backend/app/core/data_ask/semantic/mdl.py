"""Semantic layer MDL (Wren/SuperSonic inspired)."""
from __future__ import annotations

from typing import Any


def format_semantic_context(model: dict[str, Any] | None) -> str:
    if not model:
        return ""
    lines = ["## 业务语义定义（必须遵循）"]
    for m in model.get("metrics") or []:
        if isinstance(m, dict):
            expr = m.get("expr") or m.get("definition") or ""
            lines.append(f"- 指标 {m.get('name')}: {expr}")
    for d in model.get("dimensions") or []:
        if isinstance(d, dict):
            sens = f" [敏感:{d.get('sensitivity')}]" if d.get("sensitivity") else ""
            lines.append(
                f"- 维度 {d.get('name')}: 列 {d.get('column')} ({d.get('description') or ''}){sens}"
            )
    for rel in model.get("relationships") or []:
        if isinstance(rel, dict):
            lines.append(
                f"- 关联 {rel.get('from')} -> {rel.get('to')} ON {rel.get('on')}"
            )
    for note in model.get("notes") or []:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def expand_metrics_in_prompt(model: dict[str, Any] | None) -> str:
    if not model:
        return ""
    metrics = [m for m in (model.get("metrics") or []) if isinstance(m, dict) and m.get("expr")]
    if not metrics:
        return ""
    lines = ["## 指标表达式（生成 SQL 时优先使用 expr）"]
    for m in metrics:
        lines.append(f"- {m.get('name')}: {m.get('expr')}")
    return "\n".join(lines) + "\n"


def default_semantic_model() -> dict[str, Any]:
    return {
        "metrics": [
            {"name": "销量", "expr": "SUM(sales_amount)", "definition": "SUM(quantity) 或 SUM(sales_amount)"},
            {"name": "环比", "expr": "(SUM(this_week)-SUM(last_week))/NULLIF(SUM(last_week),0)*100"},
        ],
        "dimensions": [],
        "relationships": [],
        "columns": [],
        "notes": ["只统计用户权限范围内的事业部/国家"],
    }


def validate_semantic_model(model: dict[str, Any]) -> dict[str, Any]:
    """Normalize MDL Lite structure."""
    out = default_semantic_model()
    if not model:
        return out
    for key in ("metrics", "dimensions", "relationships", "columns", "notes"):
        if key in model and model[key] is not None:
            out[key] = model[key]
    return out
