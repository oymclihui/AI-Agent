"""Bridge chat conversations to data ask mode."""
from __future__ import annotations

import json as _json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent as AgentModel, DataSource, Message, User


async def resolve_data_source_for_chat(
    db: AsyncSession,
    *,
    agent_id: str | None,
    conversation_meta: dict | None,
) -> DataSource | None:
    meta = conversation_meta or {}
    ds_id = meta.get("data_source_id")
    if ds_id:
        return await db.get(DataSource, str(ds_id))
    if not agent_id:
        return None
    agent = await db.get(AgentModel, agent_id)
    if agent and agent.metadata_:
        ds_id = agent.metadata_.get("data_source_id")
        if ds_id:
            return await db.get(DataSource, str(ds_id))
    result = await db.execute(select(DataSource).where(DataSource.agent_id == agent_id).limit(1))
    return result.scalar_one_or_none()


async def recent_question_turns(
    db: AsyncSession,
    conversation_id: str,
    *,
    exclude_id: str | None = None,
    limit: int = 6,
) -> list[dict[str, str]]:
    """Prior chat turns for follow-up rewrite. The current user message is excluded."""
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if exclude_id:
        stmt = stmt.where(Message.id != exclude_id)
    stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    rows.reverse()
    turns: list[dict[str, str]] = []
    for row in rows:
        role = row.role.value if hasattr(row.role, "value") else str(row.role)
        text = (row.content or "").strip()
        if not text:
            continue
        turns.append({"role": role, "content": text[:500]})
    return turns


def _chart_code_block(chart: dict | None) -> str:
    """把问数结果里的图表转成前端可渲染的 ```chart 代码块。"""
    if not chart or not chart.get("labels"):
        return ""
    try:
        datasets = chart.get("datasets") or [{
            "label": chart.get("series") or "value",
            "data": chart.get("values") or [],
        }]
        payload: dict = {
            "type": chart.get("type") if chart.get("type") in {"bar", "line", "pie", "area", "scatter"} else "bar",
            "labels": chart.get("labels") or [],
            "datasets": datasets,
        }
        if chart.get("title"):
            payload["title"] = chart["title"]
        if chart.get("horizontal"):
            payload["horizontal"] = True
        return "\n```chart\n" + _json.dumps(payload, ensure_ascii=False, default=str) + "\n```"
    except Exception:
        return ""


async def format_data_ask_for_chat(result: dict, user: User | None) -> str:
    if result.get("clarification"):
        return str(result.get("answer") or result.get("clarification"))
    lines = [result.get("answer") or ""]
    chart_block = _chart_code_block(result.get("chart"))
    if chart_block:
        lines.append(chart_block)
    if result.get("sql"):
        lines.append("\n\n<details><summary>SQL</summary>\n\n```sql\n" + result["sql"] + "\n```\n</details>")
    if result.get("row_count") is not None:
        lines.append(f"\n\n*共 {result['row_count']} 行" + ("（已截断）" if result.get("truncated") else "") + "*")
    provenance = result.get("provenance")
    if provenance:
        lines.append("\n\n---\n**数据来源**\n" + "\n".join(f"- {p}" for p in provenance))
    return "\n".join(lines)
