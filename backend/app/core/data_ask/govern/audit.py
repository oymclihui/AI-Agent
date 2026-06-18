"""Audit log for data ask queries."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import generate_uuid
from app.db.models import DataAskAuditLog


async def log_query(
    db: AsyncSession,
    *,
    user_id: str | None,
    data_source_id: str,
    sql_text: str,
    row_count: int,
    success: bool,
    error_message: str | None = None,
    question: str | None = None,
) -> None:
    db.add(
        DataAskAuditLog(
            id=generate_uuid(),
            user_id=user_id,
            data_source_id=data_source_id,
            question=(question or "")[:4000] or None,
            sql_text=sql_text[:8000],
            row_count=row_count,
            success=success,
            error_message=(error_message or "")[:2000] or None,
        )
    )
    await db.flush()
