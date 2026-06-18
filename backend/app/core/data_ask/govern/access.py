"""Data source access control integrated with platform RBAC."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.permissions import DataScope, resolve_data_scope
from app.db.models import DataSource, User


def bypass_row_permission(user: User | None, scope: DataScope | None = None) -> bool:
    """Admin / org managers skip row-level permission filter."""
    if not user:
        return False
    if user.is_admin:
        return True
    if scope and scope.has_permission("org:manage"):
        return True
    return False


def can_manage_all_data_sources(user: User, scope: DataScope) -> bool:
    return user.is_admin or scope.has_permission("org:manage")


async def assert_data_source_access(
    db: AsyncSession,
    source: DataSource,
    user: User,
    *,
    require_chat: bool = False,
    require_report: bool = False,
) -> None:
    scope = await resolve_data_scope(db, user)
    if not can_manage_all_data_sources(user, scope) and source.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if require_chat and not source.chat_enabled:
        raise HTTPException(status_code=403, detail="Chat Q&A disabled for this data source")
    if require_report and not source.report_enabled:
        raise HTTPException(status_code=403, detail="Scheduled reports disabled for this data source")
