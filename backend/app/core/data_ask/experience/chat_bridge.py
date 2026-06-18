"""Bridge chat conversations to data ask mode."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent as AgentModel, DataSource, User


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


async def format_data_ask_for_chat(result: dict, user: User | None) -> str:
    lines = [result.get("answer") or ""]
    if result.get("sql"):
        lines.append("\n\n<details><summary>SQL</summary>\n\n```sql\n" + result["sql"] + "\n```\n</details>")
    if result.get("row_count") is not None:
        lines.append(f"\n\n*共 {result['row_count']} 行" + ("（已截断）" if result.get("truncated") else "") + "*")
    return "\n".join(lines)
