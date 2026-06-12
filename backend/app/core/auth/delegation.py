"""Delegated permission assignment: dept liaison & executive assistant."""
from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import generate_uuid
from app.db.models import Department, PermissionAuditLog, User, UserDepartment, UserRole
from app.schemas.organization import UserRoleAssign

# Roles each delegation lane may assign (not necessarily all they can see)
FULL_ASSIGNABLE = frozenset({
    "super_admin", "org_admin", "executive", "dept_leader",
    "operator", "auditor", "dept_liaison", "executive_assistant",
})
DEPT_DELEGATABLE = frozenset({"operator", "dept_leader", "auditor"})
EXEC_DELEGATABLE = frozenset({"executive", "auditor"})
PROTECTED_ROLES = frozenset({"super_admin", "org_admin", "dept_liaison", "executive_assistant"})

EXECUTIVE_USER_TIERS = frozenset({"director", "executive"})


@dataclass
class DelegationContext:
    lane: str  # full | dept | executive | none
    actor_id: str
    department_ids: set[str] = field(default_factory=set)
    department_paths: list[str] = field(default_factory=list)
    manageable_user_ids: set[str] = field(default_factory=set)
    assignable_roles: frozenset[str] = field(default_factory=frozenset)


async def _expand_subtree_departments(db: AsyncSession, root_ids: set[str]) -> tuple[set[str], list[str]]:
    if not root_ids:
        return set(), []
    all_depts = await db.execute(
        select(Department.id, Department.path).where(Department.is_active == True)
    )
    dept_map = {row[0]: row[1] for row in all_depts.all()}
    subtree_ids: set[str] = set()
    paths: list[str] = []
    for root_id in root_ids:
        root_path = dept_map.get(root_id)
        if not root_path:
            continue
        paths.append(root_path)
        for dept_id, path in dept_map.items():
            if path == root_path or path.startswith(root_path):
                subtree_ids.add(dept_id)
    return subtree_ids, paths


async def _users_in_departments(db: AsyncSession, dept_ids: set[str]) -> set[str]:
    if not dept_ids:
        return set()
    member_result = await db.execute(
        select(UserDepartment.user_id).where(UserDepartment.department_id.in_(dept_ids))
    )
    user_ids = {row[0] for row in member_result.all()}
    primary_result = await db.execute(
        select(User.id).where(User.primary_department_id.in_(dept_ids))
    )
    user_ids.update(row[0] for row in primary_result.all())
    return user_ids


async def resolve_delegation_context(db: AsyncSession, actor: User, permissions: set[str]) -> DelegationContext:
    liaison_roots = await db.execute(
        select(Department.id).where(
            Department.liaison_user_id == actor.id,
            Department.is_active == True,
        )
    )
    liaison_dept_ids = {row[0] for row in liaison_roots.all()}
    has_dept_lane = "users:delegate:dept" in permissions or bool(liaison_dept_ids)

    if "users:manage" in permissions or actor.is_admin:
        all_users = await db.execute(select(User.id))
        return DelegationContext(
            lane="full",
            actor_id=actor.id,
            manageable_user_ids={row[0] for row in all_users.all()},
            assignable_roles=FULL_ASSIGNABLE,
        )

    if "users:delegate:exec" in permissions:
        exec_dept_ids: set[str] = set()
        exec_depts = await db.execute(
            select(Department.id).where(Department.dept_tier == "executive", Department.is_active == True)
        )
        exec_dept_ids.update(row[0] for row in exec_depts.all())

        tier_users = await db.execute(
            select(User.id).where(User.user_tier.in_(EXECUTIVE_USER_TIERS))
        )
        exec_role_users = await db.execute(
            select(UserRole.user_id).where(UserRole.role_code == "executive")
        )
        manageable: set[str] = set()
        manageable.update(row[0] for row in tier_users.all())
        manageable.update(row[0] for row in exec_role_users.all())
        if exec_dept_ids:
            manageable.update(await _users_in_departments(db, exec_dept_ids))

        return DelegationContext(
            lane="executive",
            actor_id=actor.id,
            department_ids=exec_dept_ids,
            manageable_user_ids=manageable,
            assignable_roles=EXEC_DELEGATABLE,
        )

    if has_dept_lane:
        root_ids: set[str] = set(liaison_dept_ids)
        role_rows = await db.execute(
            select(UserRole.scope_department_id).where(
                UserRole.user_id == actor.id,
                UserRole.role_code == "dept_liaison",
                UserRole.scope_department_id.isnot(None),
            )
        )
        root_ids.update(row[0] for row in role_rows.all() if row[0])

        subtree_ids, paths = await _expand_subtree_departments(db, root_ids)
        manageable = await _users_in_departments(db, subtree_ids)

        return DelegationContext(
            lane="dept",
            actor_id=actor.id,
            department_ids=subtree_ids,
            department_paths=paths,
            manageable_user_ids=manageable,
            assignable_roles=DEPT_DELEGATABLE,
        )

    return DelegationContext(lane="none", actor_id=actor.id)


def assert_can_manage_target(ctx: DelegationContext, target: User) -> None:
    if ctx.lane == "none":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No delegation permission")
    if target.id == ctx.actor_id and ctx.lane != "full":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot modify your own permissions")
    if ctx.lane == "full":
        return
    if target.id not in ctx.manageable_user_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Target user outside your scope")


def assert_department_in_scope(ctx: DelegationContext, department_id: str | None) -> None:
    if ctx.lane == "full":
        return
    if ctx.lane == "executive":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot change department in executive lane")
    if not department_id or department_id not in ctx.department_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Department outside your scope")


def validate_role_assignments(
    ctx: DelegationContext,
    new_assignments: list[UserRoleAssign],
    existing_roles: list[UserRole],
) -> list[UserRoleAssign]:
    for assign in new_assignments:
        if assign.role_code not in ctx.assignable_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role not assignable in your lane: {assign.role_code}",
            )

    if ctx.lane == "dept":
        for assign in new_assignments:
            if assign.scope_department_id and assign.scope_department_id not in ctx.department_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Role scope department outside your subtree",
                )

    if ctx.lane == "full":
        return new_assignments

    preserved: list[UserRoleAssign] = []
    for row in existing_roles:
        if row.role_code in ctx.assignable_roles:
            continue
        preserved.append(UserRoleAssign(
            role_code=row.role_code,
            scope_department_id=row.scope_department_id,
        ))

    merged = preserved + list(new_assignments)
    seen: set[str] = set()
    deduped: list[UserRoleAssign] = []
    for r in merged:
        if r.role_code in seen:
            continue
        seen.add(r.role_code)
        deduped.append(r)
    return deduped


async def actor_can_delegate_dept(db: AsyncSession, user: User, permissions: set[str]) -> bool:
    if "users:delegate:dept" in permissions or "users:manage" in permissions:
        return True
    row = await db.execute(
        select(Department.id).where(
            Department.liaison_user_id == user.id,
            Department.is_active == True,
        ).limit(1)
    )
    return row.scalar_one_or_none() is not None


async def write_audit_log(
    db: AsyncSession,
    *,
    actor_id: str,
    target_id: str,
    action: str,
    details: dict,
) -> None:
    db.add(PermissionAuditLog(
        id=generate_uuid(),
        actor_user_id=actor_id,
        target_user_id=target_id,
        action=action,
        details=details,
    ))


async def apply_user_roles(
    db: AsyncSession,
    target: User,
    roles: list[UserRoleAssign],
) -> None:
    existing = await db.execute(select(UserRole).where(UserRole.user_id == target.id))
    for row in existing.scalars().all():
        await db.delete(row)
    for assign in roles:
        db.add(UserRole(
            id=generate_uuid(),
            user_id=target.id,
            role_code=assign.role_code,
            scope_department_id=assign.scope_department_id,
        ))
    target.is_admin = any(r.role_code == "super_admin" for r in roles)
