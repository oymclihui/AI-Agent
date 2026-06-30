"""Data source access control integrated with platform RBAC and per-user grants."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.permissions import DataScope, resolve_data_scope
from app.db.models import DataSource, DataSourceGrant, User


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


async def get_grant(db: AsyncSession, source_id: str, user_id: str) -> DataSourceGrant | None:
    result = await db.execute(
        select(DataSourceGrant).where(
            DataSourceGrant.data_source_id == source_id,
            DataSourceGrant.user_id == user_id,
        ).limit(1)
    )
    return result.scalar_one_or_none()


async def list_granted_source_ids(db: AsyncSession, user_id: str) -> set[str]:
    result = await db.execute(
        select(DataSourceGrant.data_source_id).where(DataSourceGrant.user_id == user_id)
    )
    return {row[0] for row in result.all()}


def _owner_in_org_scope(source: DataSource, scope: DataScope) -> bool:
    if not source.owner_id:
        return scope.mode in ("all", "subtree")
    if scope.mode == "all":
        return True
    if scope.mode == "subtree":
        return source.owner_id in scope.visible_user_ids
    return source.owner_id == scope.user_id


async def can_access_data_source(
    db: AsyncSession,
    source: DataSource,
    user: User,
    *,
    require_ask: bool = False,
    require_manage: bool = False,
    scope: DataScope | None = None,
) -> bool:
    scope = scope or await resolve_data_scope(db, user)
    if can_manage_all_data_sources(user, scope):
        return True
    if source.owner_id == user.id:
        return True
    grant = await get_grant(db, source.id, user.id)
    if grant:
        if require_manage:
            return bool(grant.can_manage)
        if require_ask:
            return bool(grant.can_ask or grant.can_manage)
        return True
    if require_manage:
        return scope.can_write_others and _owner_in_org_scope(source, scope)
    if _owner_in_org_scope(source, scope):
        return True
    return False


async def assert_data_source_access(
    db: AsyncSession,
    source: DataSource,
    user: User,
    *,
    require_chat: bool = False,
    require_report: bool = False,
    require_manage: bool = False,
) -> None:
    require_ask = require_chat or require_report or not require_manage
    if require_manage:
        require_ask = False
    if not await can_access_data_source(
        db, source, user, require_ask=require_ask, require_manage=require_manage
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    if require_chat and not source.chat_enabled:
        raise HTTPException(status_code=403, detail="Chat Q&A disabled for this data source")
    if require_report and not source.report_enabled:
        raise HTTPException(status_code=403, detail="Scheduled reports disabled for this data source")


async def data_source_list_filter(db: AsyncSession, user: User, scope: DataScope | None = None):
    """SQLAlchemy filter for data sources visible to user."""
    scope = scope or await resolve_data_scope(db, user)
    if can_manage_all_data_sources(user, scope):
        return None
    granted = await list_granted_source_ids(db, user.id)
    clauses = [DataSource.owner_id == user.id]
    if granted:
        clauses.append(DataSource.id.in_(list(granted)))
    if scope.mode == "all":
        return or_(*clauses)
    if scope.mode == "subtree" and scope.visible_user_ids:
        visible = list(scope.visible_user_ids - {user.id})
        if visible:
            clauses.append(DataSource.owner_id.in_(visible))
    return or_(*clauses)


async def user_can_manage_data_source(db: AsyncSession, source: DataSource, user: User) -> bool:
    return await can_access_data_source(db, source, user, require_manage=True)
