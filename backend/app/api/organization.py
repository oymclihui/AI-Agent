from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.delegation import (
    DEPT_DELEGATABLE,
    EXEC_DELEGATABLE,
    actor_can_delegate_dept,
    apply_user_roles,
    assert_can_manage_target,
    assert_department_in_scope,
    resolve_delegation_context,
    validate_role_assignments,
    write_audit_log,
)
from app.core.auth.deps import get_current_user
from app.core.auth.permissions import (
    ALL_ROLES,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    assert_permission,
    compute_department_path,
    has_any_delegation,
    permissions_for_roles,
    resolve_data_scope,
)
from app.core.auth.profile import build_user_response
from app.core.auth.security import hash_password
from app.db.base import generate_uuid
from app.db.models import Department, PermissionAuditLog, User, UserDepartment, UserRole
from app.db.session import get_db
from app.schemas.auth import UserResponse
from app.core.auth.permission_import import (
    ImportRowResult,
    apply_import,
    build_import_template,
    preview_import,
)
from app.schemas.organization import (
    AuditLogResponse,
    DelegationContextResponse,
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
    DeptDelegationUpdate,
    ExecDelegationUpdate,
    OrgUserCreate,
    OrgUserResponse,
    OrgUserUpdate,
    PermissionImportApplyRequest,
    PermissionImportApplyResponse,
    PermissionImportPreviewResponse,
    PermissionImportRowResponse,
    PermissionPreviewResponse,
    RoleDefinitionResponse,
    UserRoleAssign,
)

router = APIRouter(prefix="/organization", tags=["Organization"])


async def _actor_scope(db: AsyncSession, user: User):
    return await resolve_data_scope(db, user)


async def _require_org_manage(db: AsyncSession, user: User):
    scope = await _actor_scope(db, user)
    assert_permission(scope, "org:manage")
    return scope


async def _require_any_delegation(db: AsyncSession, user: User):
    scope = await _actor_scope(db, user)
    if has_any_delegation(scope):
        return scope
    if await actor_can_delegate_dept(db, user, scope.permissions):
        return scope
    raise HTTPException(status_code=403, detail="No delegation permission")


def _user_names_map(rows) -> dict[str, str]:
    return {row[0]: row[1] for row in rows}


async def _fetch_user_names(db: AsyncSession, user_ids: set[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    result = await db.execute(
        select(User.id, User.display_name).where(User.id.in_(user_ids))
    )
    return _user_names_map(result.all())


def _dept_response(
    dept: Department,
    leader_name: str | None = None,
    liaison_name: str | None = None,
    member_count: int = 0,
) -> DepartmentResponse:
    return DepartmentResponse(
        id=dept.id,
        name=dept.name,
        code=dept.code,
        parent_id=dept.parent_id,
        path=dept.path,
        level=dept.level,
        leader_user_id=dept.leader_user_id,
        leader_name=leader_name,
        liaison_user_id=dept.liaison_user_id,
        liaison_name=liaison_name,
        dept_tier=dept.dept_tier or "business",
        sort_order=dept.sort_order or 0,
        is_active=dept.is_active,
        member_count=member_count,
        created_at=dept.created_at,
        updated_at=dept.updated_at,
    )


async def _serialize_org_user(db: AsyncSession, u: User, dept_names: dict[str, str]) -> OrgUserResponse:
    scope = await resolve_data_scope(db, u)
    role_rows = await db.execute(select(UserRole).where(UserRole.user_id == u.id))
    roles = [
        UserRoleAssign(role_code=r.role_code, scope_department_id=r.scope_department_id)
        for r in role_rows.scalars().all()
    ]
    if not roles and u.is_admin:
        roles = [UserRoleAssign(role_code="super_admin")]
    if not roles:
        roles = [UserRoleAssign(role_code="operator")]
    return OrgUserResponse(
        id=u.id,
        employee_no=u.employee_no,
        email=u.email,
        display_name=u.display_name,
        is_active=u.is_active,
        is_admin=u.is_admin,
        user_tier=u.user_tier or "staff",
        primary_department_id=u.primary_department_id,
        primary_department_name=dept_names.get(u.primary_department_id or ""),
        roles=roles,
        permissions=sorted(scope.permissions),
        created_at=u.created_at,
    )


def _roles_for_user(
    role_rows: list[UserRole],
    is_admin: bool,
) -> list[UserRoleAssign]:
    roles = [
        UserRoleAssign(role_code=r.role_code, scope_department_id=r.scope_department_id)
        for r in role_rows
    ]
    if not roles and is_admin:
        roles = [UserRoleAssign(role_code="super_admin")]
    if not roles:
        roles = [UserRoleAssign(role_code="operator")]
    return roles


async def _serialize_org_users_batch(
    db: AsyncSession,
    users: list[User],
    dept_names: dict[str, str],
) -> list[OrgUserResponse]:
    if not users:
        return []
    user_ids = [u.id for u in users]
    role_result = await db.execute(select(UserRole).where(UserRole.user_id.in_(user_ids)))
    roles_by_user: dict[str, list[UserRole]] = {uid: [] for uid in user_ids}
    for row in role_result.scalars().all():
        roles_by_user.setdefault(row.user_id, []).append(row)

    return [
        OrgUserResponse(
            id=u.id,
            employee_no=u.employee_no,
            email=u.email,
            display_name=u.display_name,
            is_active=u.is_active,
            is_admin=u.is_admin,
            user_tier=u.user_tier or "staff",
            primary_department_id=u.primary_department_id,
            primary_department_name=dept_names.get(u.primary_department_id or ""),
            roles=_roles_for_user(roles_by_user.get(u.id, []), u.is_admin),
            permissions=permissions_for_roles(
                [r.role_code for r in roles_by_user.get(u.id, [])],
                u.is_admin,
            ),
            created_at=u.created_at,
        )
        for u in users
    ]


async def _load_departments_enriched(db: AsyncSession, dept_filter=None) -> list[DepartmentResponse]:
    query = select(Department).where(Department.is_active == True).order_by(Department.path, Department.sort_order)
    if dept_filter is not None:
        query = query.where(dept_filter)
    depts = (await db.execute(query)).scalars().all()
    if not depts:
        return []

    name_ids = set()
    for d in depts:
        if d.leader_user_id:
            name_ids.add(d.leader_user_id)
        if d.liaison_user_id:
            name_ids.add(d.liaison_user_id)
    names = await _fetch_user_names(db, name_ids)

    count_result = await db.execute(
        select(UserDepartment.department_id, func.count()).group_by(UserDepartment.department_id)
    )
    counts = {row[0]: row[1] for row in count_result.all()}

    return [
        _dept_response(d, names.get(d.leader_user_id or ""), names.get(d.liaison_user_id or ""), counts.get(d.id, 0))
        for d in depts
    ]


# ── Delegation ────────────────────────────────────────

@router.get("/delegation/context", response_model=DelegationContextResponse)
async def delegation_context(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    scope = await _require_any_delegation(db, user)
    ctx = await resolve_delegation_context(db, user, scope.permissions)
    return DelegationContextResponse(
        lane=ctx.lane,
        assignable_roles=sorted(ctx.assignable_roles),
        department_count=len(ctx.department_ids),
        manageable_user_count=len(ctx.manageable_user_ids),
        department_paths=ctx.department_paths,
    )


@router.get("/delegation/departments", response_model=list[DepartmentResponse])
async def delegation_departments(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    scope = await _require_any_delegation(db, user)
    ctx = await resolve_delegation_context(db, user, scope.permissions)
    if ctx.lane == "full":
        return await _load_departments_enriched(db)
    if ctx.lane == "dept" and ctx.department_ids:
        return await _load_departments_enriched(db, Department.id.in_(ctx.department_ids))
    if ctx.lane == "executive":
        return await _load_departments_enriched(db, Department.dept_tier == "executive")
    return []


@router.get("/delegation/dept-users", response_model=list[OrgUserResponse])
async def delegation_dept_users(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    scope = await _actor_scope(db, user)
    if not await actor_can_delegate_dept(db, user, scope.permissions):
        raise HTTPException(status_code=403, detail="Dept delegation permission required")
    ctx = await resolve_delegation_context(db, user, scope.permissions)
    if ctx.lane not in ("full", "dept"):
        raise HTTPException(status_code=403, detail="Not a department liaison")

    if ctx.lane == "full":
        users = (await db.execute(select(User).order_by(User.display_name))).scalars().all()
    else:
        ids = ctx.manageable_user_ids
        if not ids:
            return []
        users = (await db.execute(select(User).where(User.id.in_(ids)).order_by(User.display_name))).scalars().all()

    dept_ids = {u.primary_department_id for u in users if u.primary_department_id}
    dept_names: dict[str, str] = {}
    if dept_ids:
        depts = await db.execute(select(Department.id, Department.name).where(Department.id.in_(dept_ids)))
        dept_names = {row[0]: row[1] for row in depts.all()}

    return [await _serialize_org_user(db, u, dept_names) for u in users]


@router.get("/delegation/executive-users", response_model=list[OrgUserResponse])
async def delegation_executive_users(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    scope = await _actor_scope(db, user)
    if not scope.has_permission("users:delegate:exec") and not scope.has_permission("users:manage"):
        raise HTTPException(status_code=403, detail="Executive delegation permission required")
    ctx = await resolve_delegation_context(db, user, scope.permissions)
    if ctx.lane not in ("full", "executive"):
        raise HTTPException(status_code=403, detail="Not an executive assistant")

    if ctx.lane == "full":
        users = (await db.execute(
            select(User).where(User.user_tier.in_(("director", "executive", "staff"))).order_by(User.display_name)
        )).scalars().all()
    else:
        ids = ctx.manageable_user_ids
        if not ids:
            return []
        users = (await db.execute(select(User).where(User.id.in_(ids)).order_by(User.display_name))).scalars().all()

    dept_ids = {u.primary_department_id for u in users if u.primary_department_id}
    dept_names: dict[str, str] = {}
    if dept_ids:
        depts = await db.execute(select(Department.id, Department.name).where(Department.id.in_(dept_ids)))
        dept_names = {row[0]: row[1] for row in depts.all()}

    return [await _serialize_org_user(db, u, dept_names) for u in users]


@router.patch("/delegation/dept-users/{target_user_id}", response_model=OrgUserResponse)
async def update_dept_delegation(
    target_user_id: str,
    payload: DeptDelegationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _actor_scope(db, user)
    if not await actor_can_delegate_dept(db, user, scope.permissions):
        raise HTTPException(status_code=403, detail="Forbidden")

    ctx = await resolve_delegation_context(db, user, scope.permissions)
    target = await db.get(User, target_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    assert_can_manage_target(ctx, target)

    before_roles = (await db.execute(select(UserRole).where(UserRole.user_id == target.id))).scalars().all()

    if payload.primary_department_id is not None:
        assert_department_in_scope(ctx, payload.primary_department_id)
        if payload.primary_department_id:
            dept = await db.get(Department, payload.primary_department_id)
            if not dept or not dept.is_active:
                raise HTTPException(status_code=404, detail="Department not found")
        target.primary_department_id = payload.primary_department_id or None
        existing = await db.execute(
            select(UserDepartment).where(UserDepartment.user_id == target.id, UserDepartment.is_primary == True).limit(1)
        )
        membership = existing.scalar_one_or_none()
        if payload.primary_department_id:
            if membership:
                membership.department_id = payload.primary_department_id
            else:
                db.add(UserDepartment(
                    id=generate_uuid(), user_id=target.id,
                    department_id=payload.primary_department_id, is_primary=True,
                ))
        elif membership:
            await db.delete(membership)

    merged = validate_role_assignments(ctx, payload.roles, list(before_roles))
    await apply_user_roles(db, target, merged)

    await write_audit_log(
        db,
        actor_id=user.id,
        target_id=target.id,
        action="dept_delegation",
        details={
            "lane": ctx.lane,
            "before": [{"role_code": r.role_code, "scope": r.scope_department_id} for r in before_roles],
            "after": [{"role_code": r.role_code, "scope": r.scope_department_id} for r in merged],
            "primary_department_id": target.primary_department_id,
        },
    )
    await db.flush()

    dept_name = None
    if target.primary_department_id:
        dept = await db.get(Department, target.primary_department_id)
        dept_name = dept.name if dept else None
    return await _serialize_org_user(db, target, {target.primary_department_id or "": dept_name or ""})


@router.patch("/delegation/executive-users/{target_user_id}", response_model=OrgUserResponse)
async def update_exec_delegation(
    target_user_id: str,
    payload: ExecDelegationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _actor_scope(db, user)
    if not scope.has_permission("users:delegate:exec") and not scope.has_permission("users:manage"):
        raise HTTPException(status_code=403, detail="Forbidden")

    ctx = await resolve_delegation_context(db, user, scope.permissions)
    target = await db.get(User, target_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    assert_can_manage_target(ctx, target)

    if payload.user_tier is not None and ctx.lane == "full":
        target.user_tier = payload.user_tier

    before_roles = (await db.execute(select(UserRole).where(UserRole.user_id == target.id))).scalars().all()
    merged = validate_role_assignments(ctx, payload.roles, list(before_roles))
    await apply_user_roles(db, target, merged)

    await write_audit_log(
        db,
        actor_id=user.id,
        target_id=target.id,
        action="executive_delegation",
        details={
            "lane": ctx.lane,
            "before": [{"role_code": r.role_code} for r in before_roles],
            "after": [{"role_code": r.role_code} for r in merged],
            "user_tier": target.user_tier,
        },
    )
    await db.flush()

    dept_names: dict[str, str] = {}
    if target.primary_department_id:
        dept = await db.get(Department, target.primary_department_id)
        if dept:
            dept_names[target.primary_department_id] = dept.name
    return await _serialize_org_user(db, target, dept_names)


@router.get("/audit-logs", response_model=list[AuditLogResponse])
async def list_audit_logs(
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _actor_scope(db, user)
    if not scope.has_permission("org:manage") and not scope.has_permission("users:manage"):
        if not scope.has_permission("users:delegate:dept") and not scope.has_permission("users:delegate:exec"):
            raise HTTPException(status_code=403, detail="Forbidden")

    result = await db.execute(
        select(PermissionAuditLog).order_by(PermissionAuditLog.created_at.desc()).limit(limit)
    )
    logs = result.scalars().all()
    actor_ids = {log.actor_user_id for log in logs} | {log.target_user_id for log in logs}
    names = await _fetch_user_names(db, actor_ids)

    return [
        AuditLogResponse(
            id=log.id,
            actor_user_id=log.actor_user_id,
            actor_name=names.get(log.actor_user_id),
            target_user_id=log.target_user_id,
            target_name=names.get(log.target_user_id),
            action=log.action,
            details=log.details or {},
            created_at=log.created_at,
        )
        for log in logs
    ]


# ── Full org admin (platform admin) ───────────────────

@router.get("/roles", response_model=list[RoleDefinitionResponse])
async def list_roles(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_org_manage(db, user)
    return [
        RoleDefinitionResponse(
            role_code=code,
            label_zh=ROLE_LABELS[code]["zh"],
            label_en=ROLE_LABELS[code]["en"],
            permissions=sorted(ROLE_PERMISSIONS.get(code, frozenset())),
        )
        for code in ALL_ROLES
    ]


@router.get("/roles/delegatable", response_model=list[RoleDefinitionResponse])
async def list_delegatable_roles(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    scope = await _require_any_delegation(db, user)
    ctx = await resolve_delegation_context(db, user, scope.permissions)
    return [
        RoleDefinitionResponse(
            role_code=code,
            label_zh=ROLE_LABELS[code]["zh"],
            label_en=ROLE_LABELS[code]["en"],
            permissions=sorted(ROLE_PERMISSIONS.get(code, frozenset())),
        )
        for code in ALL_ROLES if code in ctx.assignable_roles
    ]


@router.get("/departments", response_model=list[DepartmentResponse])
async def list_departments(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_org_manage(db, user)
    return await _load_departments_enriched(db)


@router.post("/departments", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
async def create_department(
    payload: DepartmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_manage(db, user)
    parent_path = None
    if payload.parent_id:
        parent = await db.get(Department, payload.parent_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Parent department not found")
        parent_path = parent.path

    dept_id = generate_uuid()
    path, level = compute_department_path(parent_path, dept_id)
    dept = Department(
        id=dept_id,
        name=payload.name.strip(),
        code=payload.code.strip() if payload.code else None,
        parent_id=payload.parent_id,
        path=path,
        level=level,
        leader_user_id=payload.leader_user_id,
        liaison_user_id=payload.liaison_user_id,
        dept_tier=payload.dept_tier or "business",
        sort_order=payload.sort_order,
        is_active=True,
    )
    db.add(dept)
    await db.flush()

    names = await _fetch_user_names(db, {dept.leader_user_id, dept.liaison_user_id} - {None})
    return _dept_response(
        dept,
        names.get(dept.leader_user_id or ""),
        names.get(dept.liaison_user_id or ""),
        0,
    )


async def _rebuild_subtree_paths(sync_db, dept: Department) -> None:
    children = await sync_db.execute(select(Department).where(Department.parent_id == dept.id))
    for child in children.scalars().all():
        child.path, child.level = compute_department_path(dept.path, child.id)
        await _rebuild_subtree_paths(sync_db, child)


@router.patch("/departments/{department_id}", response_model=DepartmentResponse)
async def update_department(
    department_id: str,
    payload: DepartmentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_manage(db, user)
    dept = await db.get(Department, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    data = payload.model_dump(exclude_none=True)
    if "parent_id" in data and data["parent_id"] == department_id:
        raise HTTPException(status_code=400, detail="Department cannot be its own parent")

    parent_path = None
    if "parent_id" in data:
        if data["parent_id"]:
            parent = await db.get(Department, data["parent_id"])
            if not parent:
                raise HTTPException(status_code=404, detail="Parent department not found")
            if parent.path.startswith(dept.path):
                raise HTTPException(status_code=400, detail="Cannot move department under its descendant")
            parent_path = parent.path
        dept.parent_id = data["parent_id"]
        dept.path, dept.level = compute_department_path(parent_path, dept.id)
        await _rebuild_subtree_paths(db, dept)

    for field in ("name", "code", "leader_user_id", "liaison_user_id", "dept_tier", "sort_order", "is_active"):
        if field in data:
            val = data[field]
            setattr(dept, field, val.strip() if field == "name" and val else val)

    await db.flush()
    names = await _fetch_user_names(db, {dept.leader_user_id, dept.liaison_user_id} - {None})
    count_result = await db.execute(select(func.count()).where(UserDepartment.department_id == dept.id))
    return _dept_response(
        dept,
        names.get(dept.leader_user_id or ""),
        names.get(dept.liaison_user_id or ""),
        count_result.scalar() or 0,
    )


@router.delete("/departments/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_department(
    department_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_manage(db, user)
    dept = await db.get(Department, department_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    child = await db.execute(
        select(Department.id).where(Department.parent_id == department_id, Department.is_active == True).limit(1)
    )
    if child.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Department has active children")

    member = await db.execute(
        select(UserDepartment.id).where(UserDepartment.department_id == department_id).limit(1)
    )
    if member.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Department has members")

    dept.is_active = False
    await db.flush()


@router.post("/users", response_model=OrgUserResponse, status_code=status.HTTP_201_CREATED)
async def create_org_user(
    payload: OrgUserCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_manage(db, user)

    dup_q = select(User).where(User.employee_no == payload.employee_no)
    if payload.email:
        dup_q = select(User).where(
            (User.employee_no == payload.employee_no) | (User.email == payload.email)
        )
    existing = await db.execute(dup_q.limit(1))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Employee no or email already exists")

    if payload.primary_department_id:
        dept = await db.get(Department, payload.primary_department_id)
        if not dept or not dept.is_active:
            raise HTTPException(status_code=404, detail="Department not found")

    for code in {r.role_code for r in payload.roles}:
        if code not in ALL_ROLES:
            raise HTTPException(status_code=400, detail=f"Unknown role: {code}")

    target = User(
        id=generate_uuid(),
        employee_no=payload.employee_no,
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        is_active=payload.is_active,
        is_admin=any(r.role_code in ("super_admin", "org_admin") for r in payload.roles),
        user_tier=payload.user_tier,
        primary_department_id=payload.primary_department_id,
    )
    db.add(target)
    await db.flush()

    if payload.primary_department_id:
        db.add(UserDepartment(
            id=generate_uuid(),
            user_id=target.id,
            department_id=payload.primary_department_id,
            is_primary=True,
        ))

    if payload.roles:
        await apply_user_roles(db, target, payload.roles)

    await write_audit_log(
        db,
        actor_id=user.id,
        target_id=target.id,
        action="org_user_create",
        details={"employee_no": payload.employee_no, "roles": [r.role_code for r in payload.roles]},
    )
    await db.flush()

    dept_names: dict[str, str] = {}
    if target.primary_department_id:
        dept = await db.get(Department, target.primary_department_id)
        if dept:
            dept_names[target.primary_department_id] = dept.name
    return await _serialize_org_user(db, target, dept_names)


@router.get("/users", response_model=list[OrgUserResponse])
async def list_org_users(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_org_manage(db, user)
    users = (await db.execute(select(User).order_by(User.display_name))).scalars().all()
    dept_ids = {u.primary_department_id for u in users if u.primary_department_id}
    dept_names: dict[str, str] = {}
    if dept_ids:
        depts = await db.execute(select(Department.id, Department.name).where(Department.id.in_(dept_ids)))
        dept_names = {row[0]: row[1] for row in depts.all()}
    return await _serialize_org_users_batch(db, users, dept_names)


@router.patch("/users/{target_user_id}", response_model=OrgUserResponse)
async def update_org_user(
    target_user_id: str,
    payload: OrgUserUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_manage(db, user)
    target = await db.get(User, target_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    before_roles = (await db.execute(select(UserRole).where(UserRole.user_id == target.id))).scalars().all()

    if payload.primary_department_id is not None:
        if payload.primary_department_id:
            dept = await db.get(Department, payload.primary_department_id)
            if not dept or not dept.is_active:
                raise HTTPException(status_code=404, detail="Department not found")
        target.primary_department_id = payload.primary_department_id or None
        existing = await db.execute(
            select(UserDepartment).where(UserDepartment.user_id == target.id, UserDepartment.is_primary == True).limit(1)
        )
        membership = existing.scalar_one_or_none()
        if payload.primary_department_id:
            if membership:
                membership.department_id = payload.primary_department_id
            else:
                db.add(UserDepartment(
                    id=generate_uuid(), user_id=target.id,
                    department_id=payload.primary_department_id, is_primary=True,
                ))
        elif membership:
            await db.delete(membership)

    if payload.user_tier is not None:
        target.user_tier = payload.user_tier

    if payload.is_active is not None:
        target.is_active = payload.is_active

    if payload.roles is not None:
        for code in {r.role_code for r in payload.roles}:
            if code not in ALL_ROLES:
                raise HTTPException(status_code=400, detail=f"Unknown role: {code}")
        await apply_user_roles(db, target, payload.roles)
        await write_audit_log(
            db,
            actor_id=user.id,
            target_id=target.id,
            action="org_admin_update",
            details={
                "before": [{"role_code": r.role_code} for r in before_roles],
                "after": [{"role_code": r.role_code} for r in payload.roles],
            },
        )

    await db.flush()
    dept_names: dict[str, str] = {}
    if target.primary_department_id:
        dept = await db.get(Department, target.primary_department_id)
        if dept:
            dept_names[target.primary_department_id] = dept.name
    return await _serialize_org_user(db, target, dept_names)


@router.get("/permissions/preview/{target_user_id}", response_model=PermissionPreviewResponse)
async def preview_permissions(
    target_user_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_manage(db, user)
    target = await db.get(User, target_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    scope = await resolve_data_scope(db, target)
    role_rows = await db.execute(select(UserRole).where(UserRole.user_id == target.id))
    roles = [
        UserRoleAssign(role_code=r.role_code, scope_department_id=r.scope_department_id)
        for r in role_rows.scalars().all()
    ]
    return PermissionPreviewResponse(
        user_id=target.id,
        display_name=target.display_name,
        roles=roles or [UserRoleAssign(role_code="operator")],
        permissions=sorted(scope.permissions),
        data_scope=scope.mode,
        visible_user_count=len(scope.visible_user_ids),
        visible_department_count=len(scope.department_ids),
        can_view_dashboard=scope.has_permission("dashboard:view"),
        can_manage_org=scope.has_permission("org:manage"),
        department_paths=scope.department_paths,
    )


def _import_preview_response(rows: list[ImportRowResult]) -> PermissionImportPreviewResponse:
    payload = [PermissionImportRowResponse(**r.to_dict()) for r in rows]
    return PermissionImportPreviewResponse(
        total=len(payload),
        ok=sum(1 for r in payload if r.status == "ok"),
        warning=sum(1 for r in payload if r.status == "warning"),
        error=sum(1 for r in payload if r.status == "error"),
        rows=payload,
    )


@router.get("/permissions/import/template")
async def download_permission_import_template(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    include_current: bool = Query(False, description="Fill sheet with current users"),
):
    await _require_org_manage(db, user)
    content = await build_import_template(db, lane="full", include_current=include_current)
    filename = "permission_import_template.xlsx" if not include_current else "permission_export.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/delegation/permissions/import/template")
async def download_delegation_import_template(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _require_any_delegation(db, user)
    ctx = await resolve_delegation_context(db, user, scope.permissions)
    if ctx.lane not in ("full", "dept", "executive"):
        raise HTTPException(status_code=403, detail="No import permission")
    lane = "dept" if ctx.lane == "dept" else ("executive" if ctx.lane == "executive" else "full")
    content = await build_import_template(db, lane=lane, include_current=False)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="dept_permission_import_template.xlsx"'},
    )


@router.post("/permissions/import/preview", response_model=PermissionImportPreviewResponse)
async def preview_permission_import(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    await _require_org_manage(db, user)
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        rows = await preview_import(db, raw, lane="full")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _import_preview_response(rows)


@router.post("/delegation/permissions/import/preview", response_model=PermissionImportPreviewResponse)
async def preview_delegation_permission_import(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    scope = await _actor_scope(db, user)
    if not await actor_can_delegate_dept(db, user, scope.permissions) and not scope.has_permission("users:delegate:exec"):
        raise HTTPException(status_code=403, detail="Forbidden")
    ctx = await resolve_delegation_context(db, user, scope.permissions)
    if ctx.lane not in ("full", "dept", "executive"):
        raise HTTPException(status_code=403, detail="No import permission")
    lane = "dept" if ctx.lane == "dept" else ("executive" if ctx.lane == "executive" else "full")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        rows = await preview_import(db, raw, ctx=ctx, lane=lane)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _import_preview_response(rows)


@router.post("/permissions/import/apply", response_model=PermissionImportApplyResponse)
async def apply_permission_import(
    payload: PermissionImportApplyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_manage(db, user)
    import_rows = [
        ImportRowResult(
            row_number=r.row_number,
            employee_no=r.employee_no,
            display_name=r.display_name,
            primary_department_code=r.primary_department_code,
            primary_department_name=r.primary_department_name,
            user_tier=r.user_tier,
            roles=r.roles,
            scope_department_code=r.scope_department_code,
            is_active=r.is_active,
            status=r.status,
            message=r.message,
            user_id=r.user_id,
            changes=r.changes,
        )
        for r in payload.rows
    ]
    stats = await apply_import(db, import_rows, actor_id=user.id, lane="full")
    return PermissionImportApplyResponse(**stats)


@router.post("/delegation/permissions/import/apply", response_model=PermissionImportApplyResponse)
async def apply_delegation_permission_import(
    payload: PermissionImportApplyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await _actor_scope(db, user)
    if not await actor_can_delegate_dept(db, user, scope.permissions) and not scope.has_permission("users:delegate:exec"):
        raise HTTPException(status_code=403, detail="Forbidden")
    ctx = await resolve_delegation_context(db, user, scope.permissions)
    if ctx.lane not in ("full", "dept", "executive"):
        raise HTTPException(status_code=403, detail="No import permission")
    lane = "dept" if ctx.lane == "dept" else ("executive" if ctx.lane == "executive" else "full")
    import_rows = [
        ImportRowResult(
            row_number=r.row_number,
            employee_no=r.employee_no,
            display_name=r.display_name,
            primary_department_code=r.primary_department_code,
            primary_department_name=r.primary_department_name,
            user_tier=r.user_tier,
            roles=r.roles,
            scope_department_code=r.scope_department_code,
            is_active=r.is_active,
            status=r.status,
            message=r.message,
            user_id=r.user_id,
            changes=r.changes,
        )
        for r in payload.rows
    ]
    stats = await apply_import(db, import_rows, actor_id=user.id, ctx=ctx, lane=lane)
    return PermissionImportApplyResponse(**stats)


@router.get("/me/profile", response_model=UserResponse)
async def my_profile(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await build_user_response(db, user)
