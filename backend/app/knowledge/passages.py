"""Persist parent, child, and FAQ passages for keyword search."""
from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import generate_uuid
from app.db.models import KnowledgePassage


async def replace_passages(
    db: AsyncSession,
    kb_id: str,
    document_id: str,
    title: str,
    passages: list[dict],
) -> None:
    await db.execute(delete(KnowledgePassage).where(KnowledgePassage.document_id == document_id))
    for item in passages:
        db.add(KnowledgePassage(
            id=generate_uuid(),
            knowledge_base_id=kb_id,
            document_id=document_id,
            chunk_index=int(item.get("chunk_index") or 0),
            parent_index=item.get("parent_index"),
            role=item.get("role") or "child",
            content=item.get("content") or "",
            title=title,
        ))
    await db.flush()


async def delete_passages(db: AsyncSession, document_id: str) -> None:
    await db.execute(delete(KnowledgePassage).where(KnowledgePassage.document_id == document_id))
