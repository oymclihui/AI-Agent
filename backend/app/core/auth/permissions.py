"""Organization RBAC: roles, data scope, and permission checks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeMeta

from app.db.models import Department, DigitalEmployee, User, UserDepartment, UserRole

RoleCode = Literal[
    "super_admin",
    "org_admin",
    "executive",
    "dept_leader",
    "operator",
    "auditor",
    "dept_liaison",
    "executive_assistant",
]

ALL_ROLES: tuple[str, ...] = (
    "super_admin",
    "org_admin",
    "executive",
    "dept_leader",
    "operator",
    "auditor",
    "dept_liaison",
    "executive_assistant",
)

ROLE_LABELS: dict[str, dict[str, str]] = {
    "super_admin": {"zh": "系统管理员", "en": "System Admin"},
    "org_admin": {"zh": "组织管理员", "en": "Org Admin"},
    "executive": {"zh": "高管", "en": "Executive"},
    "dept_leader": {"zh": "部门负责人", "en": "Dept Leader"},
    "operator": {"zh": "业务操作员", "en": "Operator"},
    "auditor": {"zh": "审计只读", "en": "Auditor"},
    "dept_liaison": {"zh": "部门接口人", "en": "Dept Liaison"},
    "executive_assistant": {"zh": "高管秘书", "en": "Executive Assistant"},
}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "super_admin": frozenset({
        "employees:read", "employees:write", "dashboard:view",
        "org:manage", "users:manage",
    }),
    "org_admin": frozenset({
        "employees:read", "org:manage", "users:manage",
    }),
    "executive": frozenset({
        "employees:read", "dashboard:view",
    }),
    "dept_leader": frozenset({
        "employees:read", "employees:write", "dashboard:view",
    }),
    "operator": frozenset({
        "employees:read", "employees:write",
    }),
    "auditor": frozenset({
        "employees:read", "dashboard:view",
    }),
    "dept_liaison": frozenset({
        "employees:read", "users:delegate:dept",
    }),
    "executive_assistant": frozenset({
        "employees:read", "dashboard:view", "users:delegate:exec",
    }),
}

ScopeMode = Literal["all", "subtree", "self"]


@dataclass
class DataScope:
    mode: ScopeMode = "self"
    user_id: str = ""
    visible_user_ids: set[str] = field(default_factory=set)
    department_ids: set[str] = field(default_factory=set)
    department_paths: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)
    can_write_others: bool = False

    def has_permission(self, perm: str) -> bool:
        return perm in self.permissions

    def can_read_employee(self, employee: DigitalEmployee) -> bool:
        if not self.has_permission("employees:read"):
            return False
        if self.mode == "all":
            return True
        owner_id = employee.owner_id
        if owner_id == self.user_id:
            return True
        if owner_id is None:
            return self.mode in ("all", "subtree")
        if self.mode == "subtree" and owner_id in self.visible_user_ids:
            return True
        return False

    def can_write_employee(self, employee: DigitalEmployee) -> bool:
        if not self.has_permission("employees:write"):
            return False
        if self.mode == "all":
            return True
        owner_id = employee.owner_id
        if owner_id is None:
            return False
        if owner_id == self.user_id:
            return True
        if self.can_write_others and self.mode == "subtree" and owner_id in self.visible_user_ids:
            return True
        return False


def _merge_permissions(role_codes: list[str], is_admin: bool) -> set[str]:
    perms: set[str] = set()
    if is_admin and "super_admin" not in role_codes:
        role_codes = list(role_codes) + ["super_admin"]
    for code in role_codes:
        perms.update(ROLE_PERMISSIONS.get(code, frozenset()))
    if not role_codes:
        perms.update(ROLE_PERMISSIONS["operator"])
    return perms


def permissions_for_roles(role_codes: list[str], is_admin: bool) -> list[str]:
    """Lightweight permission list from role codes (no DB scope walk)."""
    return sorted(_merge_permissions(role_codes, is_admin))


def _determine_scope_mode(role_codes: list[str], is_admin: bool) -> ScopeMode:
    if is_admin or "super_admin" in role_codes:
        return "all"
    if "executive" in role_codes:
        return "all"
    if any(c in role_codes for c in ("dept_leader", "org_admin", "auditor", "dept_liaison")):
        return "subtree"
    return "self"


async def load_user_roles(db: AsyncSession, user: User) -> list[UserRole]:
    result = await db.execute(select(UserRole).where(UserRole.user_id == user.id))
    return list(result.scalars().all())


async def resolve_data_scope(db: AsyncSession, user: User) -> DataScope:
    role_rows = await load_user_roles(db, user)
    role_codes = [r.role_code for r in role_rows]
    if not role_codes:
        role_codes = ["super_admin"] if user.is_admin else ["operator"]

    permissions = _merge_permissions(role_codes, user.is_admin)
    mode = _determine_scope_mode(role_codes, user.is_admin)
    can_write_others = (
        "dept_leader" in role_codes
        or user.is_admin
        or "super_admin" in role_codes
    )

    scope = DataScope(
        mode=mode,
        user_id=user.id,
        roles=role_codes,
        permissions=permissions,
        can_write_others=can_write_others,
        visible_user_ids={user.id},
    )

    if mode == "self":
        return scope

    if mode == "all":
        result = await db.execute(select(User.id))
        scope.visible_user_ids = {row[0] for row in result.all()}
        dept_result = await db.execute(select(Department.id, Department.path))
        for dept_id, path in dept_result.all():
            scope.department_ids.add(dept_id)
            scope.department_paths.append(path)
        return scope

    root_dept_ids: set[str] = set()
    for row in role_rows:
        if row.role_code in ("dept_leader", "auditor", "org_admin", "dept_liaison"):
            if row.scope_department_id:
                root_dept_ids.add(row.scope_department_id)

    led = await db.execute(
        select(Department.id).where(Department.leader_user_id == user.id, Department.is_active == True)
    )
    root_dept_ids.update(row[0] for row in led.all())

    liaison = await db.execute(
        select(Department.id).where(Department.liaison_user_id == user.id, Department.is_active == True)
    )
    root_dept_ids.update(row[0] for row in liaison.all())

    if user.primary_department_id and "dept_leader" in role_codes and not root_dept_ids:
        root_dept_ids.add(user.primary_department_id)

    if not root_dept_ids:
        return scope

    all_depts = await db.execute(
        select(Department.id, Department.path).where(Department.is_active == True)
    )
    dept_map = {row[0]: row[1] for row in all_depts.all()}
    subtree_dept_ids: set[str] = set()
    for root_id in root_dept_ids:
        root_path = dept_map.get(root_id)
        if not root_path:
            continue
        scope.department_paths.append(root_path)
        for dept_id, path in dept_map.items():
            if path == root_path or path.startswith(root_path):
                subtree_dept_ids.add(dept_id)
    scope.department_ids = subtree_dept_ids

    if subtree_dept_ids:
        member_result = await db.execute(
            select(UserDepartment.user_id).where(UserDepartment.department_id.in_(subtree_dept_ids))
        )
        scope.visible_user_ids.update(row[0] for row in member_result.all())

        primary_result = await db.execute(
            select(User.id).where(User.primary_department_id.in_(subtree_dept_ids))
        )
        scope.visible_user_ids.update(row[0] for row in primary_result.all())

    return scope


def scope_employees_query(model: DeclarativeMeta, scope: DataScope):
    if scope.mode == "all":
        return true()
    if scope.mode == "self":
        return model.owner_id == scope.user_id
    visible = list(scope.visible_user_ids)
    if not visible:
        return model.owner_id == scope.user_id
    return or_(
        model.owner_id.in_(visible),
        model.owner_id == scope.user_id,
        model.owner_id.is_(None),
    )


def assert_permission(scope: DataScope, perm: str) -> None:
    if not scope.has_permission(perm):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Permission denied: {perm}")


def has_any_delegation(scope: DataScope) -> bool:
    return any(
        scope.has_permission(p)
        for p in ("users:manage", "users:delegate:dept", "users:delegate:exec")
    )


async def get_employee_or_404(db: AsyncSession, employee_id: str) -> DigitalEmployee:
    emp = await db.get(DigitalEmployee, employee_id)
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return emp


async def require_employee_read(db: AsyncSession, user: User, employee_id: str) -> DigitalEmployee:
    scope = await resolve_data_scope(db, user)
    emp = await get_employee_or_404(db, employee_id)
    if not scope.can_read_employee(emp):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return emp


async def require_employee_write(db: AsyncSession, user: User, employee_id: str) -> tuple[DigitalEmployee, DataScope]:
    scope = await resolve_data_scope(db, user)
    emp = await get_employee_or_404(db, employee_id)
    if not scope.can_write_employee(emp):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return emp, scope


def compute_department_path(parent_path: str | None, dept_id: str) -> tuple[str, int]:
    if not parent_path:
        path = f"/{dept_id}/"
        return path, 0
    level = parent_path.strip("/").count("/") + 1 if parent_path.strip("/") else 0
    return f"{parent_path.rstrip('/')}/{dept_id}/", level
