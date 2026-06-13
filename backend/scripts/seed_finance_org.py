"""Seed finance department tree and placeholder users (idempotent).

Run after platform init (root department must exist):

    cd backend
    python scripts/seed_finance_org.py

Default password for all seeded users: ChangeMe@2026
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.auth.permissions import compute_department_path
from app.core.auth.security import hash_password
from app.db.models import Department, User, UserDepartment, UserRole
from app.db.session import AsyncSessionLocal

DEFAULT_PASSWORD = "ChangeMe@2026"

# Fixed UUIDs — keep in sync with scripts/sql/seed_finance_org_vastbase.sql
DEPT_IDS = {
    "fin-dept-l1": "a1111111-1111-4111-8111-111111111101",
    "fin-support-center": "a1111111-1111-4111-8111-111111111102",
    "fin-jr-dept": "a1111111-1111-4111-8111-111111111103",
    "fin-overseas-ops": "a1111111-1111-4111-8111-111111111104",
    "fin-regional": "a1111111-1111-4111-8111-111111111105",
    "fin-overseas-finance": "a1111111-1111-4111-8111-111111111106",
    "fin-overseas-tax": "a1111111-1111-4111-8111-111111111107",
    "fin-europe": "a1111111-1111-4111-8111-111111111108",
}

USER_IDS = {
    "100001": "b1000001-0001-4001-8001-000000000001",
    "100002": "b1000002-0002-4002-8002-000000000002",
    "100003": "b1000003-0003-4003-8003-000000000003",
    "110001": "c1100001-0001-4001-8001-010000000001",
    "110002": "c1100002-0002-4002-8002-010000000002",
    "110003": "c1100003-0003-4003-8003-010000000003",
    "120001": "c1200001-0001-4001-8001-020000000001",
    "120002": "c1200002-0002-4002-8002-020000000002",
    "120003": "c1200003-0003-4003-8003-020000000003",
    "130001": "c1300001-0001-4001-8001-030000000001",
    "130002": "c1300002-0002-4002-8002-030000000002",
    "130003": "c1300003-0003-4003-8003-030000000003",
    "140001": "c1400001-0001-4001-8001-040000000001",
    "140002": "c1400002-0002-4002-8002-040000000002",
    "140003": "c1400003-0003-4003-8003-040000000003",
    "150001": "c1500001-0001-4001-8001-050000000001",
    "150002": "c1500002-0002-4002-8002-050000000002",
    "150003": "c1500003-0003-4003-8003-050000000003",
    "160001": "c1600001-0001-4001-8001-060000000001",
    "160002": "c1600002-0002-4002-8002-060000000002",
    "160003": "c1600003-0003-4003-8003-060000000003",
}


@dataclass(frozen=True)
class DeptSpec:
    code: str
    name: str
    sort_order: int


@dataclass(frozen=True)
class UserSpec:
    employee_no: str
    display_name: str
    department_code: str
    role_code: str = "operator"
    user_id: str | None = None


DEPT_TREE: list[tuple[str, DeptSpec | list[DeptSpec]]] = [
    (
        "fin-dept-l1",
        DeptSpec("fin-dept-l1", "财务处", 1),
    ),
    (
        "fin-support-center",
        DeptSpec("fin-support-center", "财务支持中心", 1),
    ),
    (
        "fin-support-center",
        [
            DeptSpec("fin-jr-dept", "金融财务部", 1),
            DeptSpec("fin-overseas-ops", "海外经营管理部", 2),
            DeptSpec("fin-regional", "区域财经管理部", 3),
            DeptSpec("fin-overseas-finance", "海外财务管理部", 4),
            DeptSpec("fin-overseas-tax", "海外税务管理部", 5),
            DeptSpec("fin-europe", "欧洲财务部", 6),
        ],
    ),
]

SUPPORT_USERS: list[UserSpec] = [
    UserSpec("100001", "陈瑶", "fin-support-center", "dept_leader", USER_IDS["100001"]),
    UserSpec("100002", "刘彩红", "fin-support-center", "operator", USER_IDS["100002"]),
    UserSpec("100003", "余雅妮", "fin-support-center", "operator", USER_IDS["100003"]),
]

L3_DEPT_CODES = [
    "fin-jr-dept",
    "fin-overseas-ops",
    "fin-regional",
    "fin-overseas-finance",
    "fin-overseas-tax",
    "fin-europe",
]


def _l3_users() -> list[UserSpec]:
    users: list[UserSpec] = []
    for dept_idx, dept_code in enumerate(L3_DEPT_CODES, start=1):
        base = (10 + dept_idx) * 10000
        for seq in range(1, 4):
            emp_no = str(base + seq)
            role = "dept_leader" if seq == 1 else "operator"
            users.append(
                UserSpec(emp_no, emp_no, dept_code, role, USER_IDS[emp_no])
            )
    return users


ALL_USERS = SUPPORT_USERS + _l3_users()


async def _get_root(session) -> Department:
    root = (
        await session.execute(select(Department).where(Department.code == "root").limit(1))
    ).scalar_one_or_none()
    if not root:
        raise RuntimeError("Root department (code=root) not found — run platform init first.")
    return root


async def _upsert_department(
    session,
    *,
    spec: DeptSpec,
    parent: Department,
    dept_id: str,
) -> Department:
    dept = (
        await session.execute(select(Department).where(Department.code == spec.code).limit(1))
    ).scalar_one_or_none()
    path, level = compute_department_path(parent.path, dept_id)
    if dept:
        dept.name = spec.name
        dept.parent_id = parent.id
        dept.path = path
        dept.level = level
        dept.sort_order = spec.sort_order
        dept.is_active = True
        return dept

    dept = Department(
        id=dept_id,
        name=spec.name,
        code=spec.code,
        parent_id=parent.id,
        path=path,
        level=level,
        sort_order=spec.sort_order,
        is_active=True,
    )
    session.add(dept)
    await session.flush()
    return dept


async def _ensure_membership(session, user: User, department_id: str) -> None:
    row = (
        await session.execute(
            select(UserDepartment).where(
                UserDepartment.user_id == user.id,
                UserDepartment.department_id == department_id,
            ).limit(1)
        )
    ).scalar_one_or_none()
    if not row:
        from app.db.base import generate_uuid

        session.add(
            UserDepartment(
                id=generate_uuid(),
                user_id=user.id,
                department_id=department_id,
                is_primary=True,
            )
        )
    else:
        row.is_primary = True


async def _ensure_role(
    session,
    user: User,
    role_code: str,
    scope_department_id: str,
) -> None:
    row = (
        await session.execute(
            select(UserRole).where(
                UserRole.user_id == user.id,
                UserRole.role_code == role_code,
                UserRole.scope_department_id == scope_department_id,
            ).limit(1)
        )
    ).scalar_one_or_none()
    if not row:
        from app.db.base import generate_uuid

        session.add(
            UserRole(
                id=generate_uuid(),
                user_id=user.id,
                role_code=role_code,
                scope_department_id=scope_department_id,
            )
        )


async def _upsert_user(
    session,
    *,
    spec: UserSpec,
    password_hash: str,
    departments: dict[str, Department],
) -> User:
    dept = departments[spec.department_code]
    user_id = spec.user_id or USER_IDS.get(spec.employee_no) or spec.employee_no

    user = (
        await session.execute(select(User).where(User.employee_no == spec.employee_no).limit(1))
    ).scalar_one_or_none()
    if user:
        user.display_name = spec.display_name
        user.password_hash = password_hash
        user.is_active = True
        user.primary_department_id = dept.id
    else:
        user = User(
            id=user_id,
            employee_no=spec.employee_no,
            display_name=spec.display_name,
            password_hash=password_hash,
            is_active=True,
            is_admin=False,
            primary_department_id=dept.id,
            user_tier="staff",
        )
        session.add(user)
        await session.flush()

    await _ensure_membership(session, user, dept.id)
    await _ensure_role(session, user, spec.role_code, dept.id)
    return user


async def seed_finance_org(session) -> dict[str, int]:
    root = await _get_root(session)
    departments: dict[str, Department] = {"root": root}

    l1 = await _upsert_department(
        session,
        spec=DeptSpec("fin-dept-l1", "财务处", 1),
        parent=root,
        dept_id=DEPT_IDS["fin-dept-l1"],
    )
    departments["fin-dept-l1"] = l1

    l2 = await _upsert_department(
        session,
        spec=DeptSpec("fin-support-center", "财务支持中心", 1),
        parent=l1,
        dept_id=DEPT_IDS["fin-support-center"],
    )
    departments["fin-support-center"] = l2

    for spec in L3_DEPT_CODES:
        dept_spec = next(d for _, group in DEPT_TREE if isinstance(group, list) for d in group if d.code == spec)
        dept = await _upsert_department(
            session,
            spec=dept_spec,
            parent=l2,
            dept_id=DEPT_IDS[spec],
        )
        departments[spec] = dept

    password_hash = hash_password(DEFAULT_PASSWORD)
    users_by_no: dict[str, User] = {}
    for spec in ALL_USERS:
        users_by_no[spec.employee_no] = await _upsert_user(
            session,
            spec=spec,
            password_hash=password_hash,
            departments=departments,
        )

    support = departments["fin-support-center"]
    support.leader_user_id = users_by_no["100001"].id
    for spec in ALL_USERS:
        if spec.role_code == "dept_leader" and spec.employee_no != "100001":
            departments[spec.department_code].leader_user_id = users_by_no[spec.employee_no].id

    return {
        "departments": len(DEPT_IDS),
        "users": len(ALL_USERS),
    }


async def main() -> None:
    async with AsyncSessionLocal() as session:
        stats = await seed_finance_org(session)
        await session.commit()
    print(
        f"Finance org seeded: {stats['departments']} departments, "
        f"{stats['users']} users. Default password: {DEFAULT_PASSWORD}"
    )


if __name__ == "__main__":
    asyncio.run(main())
