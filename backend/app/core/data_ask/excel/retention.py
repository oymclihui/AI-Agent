"""Ephemeral Excel workspace — release files after analysis (方案 B)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.excel.storage import clear_excel_folder
from app.db.models import DataSource, DataSourceTable

RETENTION_EPHEMERAL = "ephemeral"
RETENTION_WORKSPACE = "workspace"


def excel_retention_mode(source: DataSource) -> str:
    if str(source.driver) not in ("excel_folder", "excel_template"):
        return RETENTION_WORKSPACE
    meta = source.metadata_ or {}
    return str(meta.get("excel_retention") or RETENTION_EPHEMERAL)


def is_ephemeral_excel(source: DataSource) -> bool:
    return excel_retention_mode(source) == RETENTION_EPHEMERAL


async def release_ephemeral_excel_workspace(db: AsyncSession, source: DataSource) -> bool:
    """Remove on-disk Excel files and registered table metadata after analysis."""
    if not is_ephemeral_excel(source):
        return False

    clear_excel_folder(source.id)

    result = await db.execute(
        select(DataSourceTable).where(DataSourceTable.data_source_id == source.id)
    )
    for row in result.scalars().all():
        await db.delete(row)

    meta = dict(source.metadata_ or {})
    meta["registered_tables"] = []
    meta["last_released_at"] = datetime.now(timezone.utc).isoformat()
    source.metadata_ = meta
    await db.flush()
    return True
