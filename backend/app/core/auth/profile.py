"""Build enriched user profile for API responses."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.permissions import ROLE_LABELS, resolve_data_scope
from app.db.models import Department, User, UserRole
from app.schemas.auth import DepartmentBrief, RoleAssignmentResponse, UserResponse


async def build_user_response(db: AsyncSession, user: User) -> UserResponse:
    scope = await resolve_data_scope(db, user)

    dept_brief = None
    if user.primary_department_id:
        dept = await db.get(Department, user.primary_department_id)
        if dept:
            dept_brief = DepartmentBrief(
                id=dept.id,
                name=dept.name,
                code=dept.code,
                path=dept.path,
            )

    role_rows = await db.execute(select(UserRole).where(UserRole.user_id == user.id))
    roles = [
        RoleAssignmentResponse(
            role_code=row.role_code,
            role_label_zh=ROLE_LABELS.get(row.role_code, {}).get("zh", row.role_code),
            role_label_en=ROLE_LABELS.get(row.role_code, {}).get("en", row.role_code),
            scope_department_id=row.scope_department_id,
        )
        for row in role_rows.scalars().all()
    ]
    if not roles and user.is_admin:
        roles.append(
            RoleAssignmentResponse(
                role_code="super_admin",
                role_label_zh=ROLE_LABELS["super_admin"]["zh"],
                role_label_en=ROLE_LABELS["super_admin"]["en"],
                scope_department_id=None,
            )
        )
    if not roles:
        roles.append(
            RoleAssignmentResponse(
                role_code="operator",
                role_label_zh=ROLE_LABELS["operator"]["zh"],
                role_label_en=ROLE_LABELS["operator"]["en"],
                scope_department_id=None,
            )
        )

    permissions = set(scope.permissions)
    liaison = await db.execute(
        select(Department.id).where(
            Department.liaison_user_id == user.id,
            Department.is_active == True,
        ).limit(1)
    )
    if liaison.scalar_one_or_none():
        permissions.add("users:delegate:dept")

    return UserResponse(
        id=user.id,
        employee_no=user.employee_no,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        is_admin=user.is_admin,
        created_at=user.created_at,
        primary_department=dept_brief,
        roles=roles,
        permissions=sorted(permissions),
        data_scope=scope.mode,
    )
