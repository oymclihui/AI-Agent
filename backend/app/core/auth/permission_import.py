"""Excel template generation and bulk permission import."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.delegation import (
    DEPT_DELEGATABLE,
    EXEC_DELEGATABLE,
    DelegationContext,
    apply_user_roles,
    assert_can_manage_target,
    assert_department_in_scope,
    validate_role_assignments,
    write_audit_log,
)
from app.core.auth.permissions import ALL_ROLES, ROLE_LABELS
from app.db.base import generate_uuid
from app.db.models import Department, User, UserDepartment, UserRole
from app.schemas.organization import UserRoleAssign

ImportLane = Literal["full", "dept", "executive"]

# User-facing column headers (Chinese primary; English aliases accepted on read)
COL_EMPLOYEE_NO = "工号"
COL_DISPLAY_NAME = "姓名"
COL_DEPT = "主部门编码"
COL_USER_TIER = "人员层级"
COL_ROLES = "角色"
COL_SCOPE_DEPT = "角色管辖部门编码"
COL_ACTIVE = "账号启用"

TEMPLATE_COLUMNS = [
    COL_EMPLOYEE_NO,
    COL_DISPLAY_NAME,
    COL_DEPT,
    COL_USER_TIER,
    COL_ROLES,
    COL_SCOPE_DEPT,
    COL_ACTIVE,
]

USER_TIER_LABELS: dict[str, str] = {
    "staff": "普通员工",
    "director": "总监级",
    "executive": "公司高管",
}
USER_TIER_ALIASES: dict[str, str] = {
    **{k: k for k in USER_TIER_LABELS},
    **{v: k for k, v in USER_TIER_LABELS.items()},
    "普通": "staff",
    "总监": "director",
    "高管": "executive",
}

ROLE_ALIASES: dict[str, str] = {code: code for code in ALL_ROLES}
for code in ALL_ROLES:
    labels = ROLE_LABELS.get(code, {})
    if labels.get("zh"):
        ROLE_ALIASES[labels["zh"]] = code
    if labels.get("en"):
        ROLE_ALIASES[labels["en"].lower()] = code
        ROLE_ALIASES[labels["en"]] = code

SCOPED_ROLES = frozenset({"dept_leader", "executive", "auditor", "dept_liaison"})

ROLE_PRESETS: dict[str, dict[str, Any]] = {
    "operator": {"roles": ["operator"], "user_tier": "staff"},
    "dept_leader": {"roles": ["dept_leader"], "user_tier": "staff"},
    "dept_liaison": {"roles": ["dept_liaison"], "user_tier": "staff"},
    "executive": {"roles": ["executive"], "user_tier": "executive"},
    "auditor": {"roles": ["auditor"], "user_tier": "staff"},
}


def _normalize_header(name: str) -> str:
    text = str(name or "").strip()
    aliases = {
        "employee_no": COL_EMPLOYEE_NO,
        "employee no": COL_EMPLOYEE_NO,
        "工号*": COL_EMPLOYEE_NO,
        "display_name": COL_DISPLAY_NAME,
        "name": COL_DISPLAY_NAME,
        "dept_code": COL_DEPT,
        "department_code": COL_DEPT,
        "primary_department": COL_DEPT,
        "user_tier": COL_USER_TIER,
        "roles": COL_ROLES,
        "role": COL_ROLES,
        "scope_dept": COL_SCOPE_DEPT,
        "scope_department": COL_SCOPE_DEPT,
        "is_active": COL_ACTIVE,
        "active": COL_ACTIVE,
    }
    lower = text.lower()
    return aliases.get(lower, text)


def _cell_str(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _parse_bool(value: Any, default: bool = True) -> bool:
    text = _cell_str(value).lower()
    if not text:
        return default
    if text in ("是", "yes", "y", "true", "1", "启用", "active"):
        return True
    if text in ("否", "no", "n", "false", "0", "停用", "inactive", "禁用"):
        return False
    return default


def _parse_roles(text: str) -> list[str]:
    if not text:
        return ["operator"]
    parts = re.split(r"[,，;；|/、\s]+", text)
    roles: list[str] = []
    for part in parts:
        token = part.strip()
        if not token:
            continue
        code = ROLE_ALIASES.get(token) or ROLE_ALIASES.get(token.lower())
        if not code:
            raise ValueError(f"未知角色: {token}")
        if code not in roles:
            roles.append(code)
    return roles or ["operator"]


def _parse_user_tier(text: str) -> str:
    if not text:
        return "staff"
    code = USER_TIER_ALIASES.get(text) or USER_TIER_ALIASES.get(text.lower())
    if not code:
        raise ValueError(f"未知人员层级: {text}")
    return code


@dataclass
class ImportRowResult:
    row_number: int
    employee_no: str
    display_name: str
    primary_department_code: str = ""
    primary_department_name: str = ""
    user_tier: str = "staff"
    roles: list[str] = field(default_factory=list)
    scope_department_code: str = ""
    is_active: bool = True
    status: str = "pending"  # ok | warning | error
    message: str = ""
    user_id: str | None = None
    changes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "employee_no": self.employee_no,
            "display_name": self.display_name,
            "primary_department_code": self.primary_department_code,
            "primary_department_name": self.primary_department_name,
            "user_tier": self.user_tier,
            "roles": self.roles,
            "scope_department_code": self.scope_department_code,
            "is_active": self.is_active,
            "status": self.status,
            "message": self.message,
            "user_id": self.user_id,
            "changes": self.changes,
        }


def _roles_snapshot(rows: list[UserRole] | list[UserRoleAssign]) -> list[tuple[str, str]]:
    snap: list[tuple[str, str]] = []
    for row in rows:
        if isinstance(row, UserRole):
            snap.append((row.role_code, row.scope_department_id or ""))
        else:
            snap.append((row.role_code, row.scope_department_id or ""))
    return sorted(snap)


def _merge_role_assignments(
    ctx: DelegationContext | None,
    role_assignments: list[UserRoleAssign],
    before_roles: list[UserRole],
) -> list[UserRoleAssign]:
    if ctx:
        return validate_role_assignments(ctx, role_assignments, before_roles)
    return role_assignments


def _assignable_for_lane(lane: ImportLane) -> frozenset[str]:
    if lane == "full":
        return frozenset(ALL_ROLES)
    if lane == "dept":
        return DEPT_DELEGATABLE
    return EXEC_DELEGATABLE

    if lane == "full":
        return frozenset(ALL_ROLES)
    if lane == "dept":
        return DEPT_DELEGATABLE
    return EXEC_DELEGATABLE


async def _dept_lookup(db: AsyncSession) -> tuple[dict[str, Department], dict[str, Department]]:
    """code -> dept, name -> dept (first match)."""
    rows = (await db.execute(select(Department).where(Department.is_active == True))).scalars().all()
    by_code: dict[str, Department] = {}
    by_name: dict[str, Department] = {}
    for dept in rows:
        if dept.code:
            by_code[str(dept.code).strip().lower()] = dept
        by_name[dept.name.strip().lower()] = dept
    return by_code, by_name


def _resolve_dept(
    token: str,
    by_code: dict[str, Department],
    by_name: dict[str, Department],
) -> Department | None:
    if not token:
        return None
    key = token.strip().lower()
    return by_code.get(key) or by_name.get(key)


def _read_dataframe(file_bytes: bytes) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0, dtype=str)
    df.columns = [_normalize_header(c) for c in df.columns]
    missing = [c for c in (COL_EMPLOYEE_NO,) if c not in df.columns]
    if missing:
        raise ValueError(f"缺少必填列: {', '.join(missing)}")
    return df


async def build_import_template(
    db: AsyncSession,
    *,
    lane: ImportLane = "full",
    include_current: bool = False,
) -> bytes:
    by_code, by_name = await _dept_lookup(db)
    depts = sorted({d.id: d for d in (list(by_code.values()) + list(by_name.values()))}.values(), key=lambda d: d.path)

    if include_current and lane == "full":
        users = (await db.execute(select(User).order_by(User.employee_no))).scalars().all()
        user_ids = [u.id for u in users]
        roles_by_user: dict[str, list[UserRole]] = {uid: [] for uid in user_ids}
        if user_ids:
            role_rows = (await db.execute(select(UserRole).where(UserRole.user_id.in_(user_ids)))).scalars().all()
            for row in role_rows:
                roles_by_user.setdefault(row.user_id, []).append(row)

        data_rows: list[dict[str, str]] = []
        for u in users:
            if not u.employee_no:
                continue
            dept_code = ""
            if u.primary_department_id:
                dept = await db.get(Department, u.primary_department_id)
                dept_code = (dept.code or dept.name) if dept else ""
            role_codes = [r.role_code for r in roles_by_user.get(u.id, [])]
            if not role_codes and u.is_admin:
                role_codes = ["super_admin"]
            if not role_codes:
                role_codes = ["operator"]
            role_labels = [ROLE_LABELS.get(c, {}).get("zh", c) for c in role_codes]
            scope_code = ""
            for r in roles_by_user.get(u.id, []):
                if r.scope_department_id:
                    scope_dept = await db.get(Department, r.scope_department_id)
                    if scope_dept:
                        scope_code = scope_dept.code or scope_dept.name
                        break
            data_rows.append({
                COL_EMPLOYEE_NO: u.employee_no,
                COL_DISPLAY_NAME: u.display_name,
                COL_DEPT: dept_code,
                COL_USER_TIER: USER_TIER_LABELS.get(u.user_tier or "staff", u.user_tier or "staff"),
                COL_ROLES: "、".join(role_labels),
                COL_SCOPE_DEPT: scope_code,
                COL_ACTIVE: "是" if u.is_active else "否",
            })
    else:
        assignable = _assignable_for_lane(lane)
        sample_roles = "、".join(ROLE_LABELS.get(c, {}).get("zh", c) for c in sorted(assignable)[:2])
        sample_dept = depts[1].code or depts[1].name if len(depts) > 1 else (depts[0].code or depts[0].name if depts else "")
        data_rows = [{
            COL_EMPLOYEE_NO: "100001",
            COL_DISPLAY_NAME: "张三（示例）",
            COL_DEPT: sample_dept,
            COL_USER_TIER: "普通员工",
            COL_ROLES: sample_roles or "业务操作员",
            COL_SCOPE_DEPT: sample_dept if lane != "executive" else "",
            COL_ACTIVE: "是",
        }]

    guide_rows = [
        {"说明项": "工号", "内容": "必填。用于匹配系统已有用户，不会自动创建新账号。"},
        {"说明项": "主部门编码", "内容": "填部门编码或部门名称，见「部门对照」 sheet。"},
        {"说明项": "人员层级", "内容": "普通员工 / 总监级 / 公司高管"},
        {"说明项": "角色", "内容": "多个角色用逗号或顿号分隔，可填中文名或英文代码，见「角色对照」。"},
        {"说明项": "角色管辖部门编码", "内容": "部门负责人/审计等需指定管辖范围时填写；留空表示默认。"},
        {"说明项": "账号启用", "内容": "是 / 否"},
    ]
    if lane == "dept":
        guide_rows.append({"说明项": "导入范围", "内容": "仅可修改本部门及下级用户，且只能赋：业务操作员、部门负责人、审计只读。"})
    elif lane == "executive":
        guide_rows.append({"说明项": "导入范围", "内容": "仅可修改高管名单池用户，且只能赋：高管、审计只读。"})

    role_rows = [
        {"角色代码": code, "中文名": ROLE_LABELS.get(code, {}).get("zh", ""), "英文名": ROLE_LABELS.get(code, {}).get("en", "")}
        for code in ALL_ROLES
    ]
    dept_rows = [
        {"部门编码": d.code or "", "部门名称": d.name, "上级路径": d.path}
        for d in depts
    ]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(data_rows, columns=TEMPLATE_COLUMNS).to_excel(writer, sheet_name="权限导入", index=False)
        pd.DataFrame(guide_rows).to_excel(writer, sheet_name="填写说明", index=False)
        pd.DataFrame(role_rows).to_excel(writer, sheet_name="角色对照", index=False)
        pd.DataFrame(dept_rows).to_excel(writer, sheet_name="部门对照", index=False)
    return buf.getvalue()


async def preview_import(
    db: AsyncSession,
    file_bytes: bytes,
    *,
    ctx: DelegationContext | None = None,
    lane: ImportLane = "full",
) -> list[ImportRowResult]:
    df = _read_dataframe(file_bytes)
    by_code, by_name = await _dept_lookup(db)

    users_by_emp: dict[str, User] = {}
    all_users = (await db.execute(select(User))).scalars().all()
    for u in all_users:
        if u.employee_no:
            users_by_emp[u.employee_no.strip().lower()] = u

    assignable = ctx.assignable_roles if ctx else _assignable_for_lane(lane)
    results: list[ImportRowResult] = []

    for idx, row in df.iterrows():
        row_num = int(idx) + 2
        emp_no = _cell_str(row.get(COL_EMPLOYEE_NO))
        result = ImportRowResult(
            row_number=row_num,
            employee_no=emp_no,
            display_name=_cell_str(row.get(COL_DISPLAY_NAME)),
        )
        if not emp_no:
            result.status = "error"
            result.message = "工号不能为空"
            results.append(result)
            continue

        target = users_by_emp.get(emp_no.lower())
        if not target:
            result.status = "error"
            result.message = f"未找到工号 {emp_no} 对应的用户"
            results.append(result)
            continue
        result.user_id = target.id
        if ctx:
            try:
                assert_can_manage_target(ctx, target)
            except Exception:
                result.status = "error"
                result.message = "该用户不在您的管理范围内"
                results.append(result)
                continue

        try:
            dept_token = _cell_str(row.get(COL_DEPT))
            dept = _resolve_dept(dept_token, by_code, by_name) if dept_token else None
            if dept_token and not dept:
                raise ValueError(f"未找到部门: {dept_token}")
            if dept:
                result.primary_department_code = dept.code or dept.name
                result.primary_department_name = dept.name
                if ctx and ctx.lane != "full":
                    assert_department_in_scope(ctx, dept.id)

            result.user_tier = _parse_user_tier(_cell_str(row.get(COL_USER_TIER)))
            result.roles = _parse_roles(_cell_str(row.get(COL_ROLES)))
            for code in result.roles:
                if code not in assignable:
                    raise ValueError(f"您无权分配角色: {ROLE_LABELS.get(code, {}).get('zh', code)}")

            scope_token = _cell_str(row.get(COL_SCOPE_DEPT))
            scope_dept = _resolve_dept(scope_token, by_code, by_name) if scope_token else None
            if scope_token and not scope_dept:
                raise ValueError(f"未找到管辖部门: {scope_token}")
            if scope_dept:
                result.scope_department_code = scope_dept.code or scope_dept.name
                if ctx and ctx.lane == "dept":
                    assert_department_in_scope(ctx, scope_dept.id)

            result.is_active = _parse_bool(row.get(COL_ACTIVE), default=target.is_active)

            # Build role assignments with scope
            scope_id = scope_dept.id if scope_dept else None
            role_assignments = []
            for code in result.roles:
                scope_for_role = scope_id if code in SCOPED_ROLES else None
                role_assignments.append(UserRoleAssign(role_code=code, scope_department_id=scope_for_role))

            before_roles = (await db.execute(select(UserRole).where(UserRole.user_id == target.id))).scalars().all()
            try:
                merged = _merge_role_assignments(ctx, role_assignments, list(before_roles))
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                raise ValueError(detail) from exc
            result.roles = [r.role_code for r in merged]

            changes: dict[str, Any] = {}
            if dept and target.primary_department_id != dept.id:
                changes["primary_department"] = {"from": target.primary_department_id, "to": dept.id}
            if target.user_tier != result.user_tier and lane in ("full", "executive"):
                changes["user_tier"] = {"from": target.user_tier, "to": result.user_tier}
            if target.is_active != result.is_active and lane == "full":
                changes["is_active"] = {"from": target.is_active, "to": result.is_active}
            if _roles_snapshot(before_roles) != _roles_snapshot(merged):
                changes["roles"] = {
                    "from": _roles_snapshot(before_roles),
                    "to": _roles_snapshot(merged),
                }

            result.changes = changes
            if changes:
                result.status = "ok"
                result.message = "将更新 " + "、".join(changes.keys())
            else:
                result.status = "warning"
                result.message = "与当前权限一致，无需变更"
        except ValueError as exc:
            result.status = "error"
            result.message = str(exc)
        except Exception as exc:
            result.status = "error"
            result.message = str(exc) or "解析失败"

        results.append(result)
    return results


async def apply_import(
    db: AsyncSession,
    rows: list[ImportRowResult],
    *,
    actor_id: str,
    ctx: DelegationContext | None = None,
    lane: ImportLane = "full",
    dry_run: bool = False,
) -> dict[str, int]:
    stats = {"applied": 0, "skipped": 0, "failed": 0}
    by_code, by_name = await _dept_lookup(db)

    for item in rows:
        if item.status != "ok" or not item.user_id or not item.changes:
            stats["skipped"] += 1
            continue
        target = await db.get(User, item.user_id)
        if not target:
            stats["failed"] += 1
            continue
        if ctx:
            try:
                assert_can_manage_target(ctx, target)
            except Exception:
                stats["failed"] += 1
                continue

        try:
            dept = _resolve_dept(item.primary_department_code, by_code, by_name)
            scope_dept = _resolve_dept(item.scope_department_code, by_code, by_name) if item.scope_department_code else None
            scope_id = scope_dept.id if scope_dept else None

            role_assignments = [
                UserRoleAssign(
                    role_code=code,
                    scope_department_id=scope_id if code in SCOPED_ROLES else None,
                )
                for code in item.roles
            ]

            before_roles = (await db.execute(select(UserRole).where(UserRole.user_id == target.id))).scalars().all()

            if dept and "primary_department" in item.changes:
                if ctx:
                    assert_department_in_scope(ctx, dept.id)
                target.primary_department_id = dept.id
                existing = await db.execute(
                    select(UserDepartment).where(
                        UserDepartment.user_id == target.id,
                        UserDepartment.is_primary == True,
                    ).limit(1)
                )
                membership = existing.scalar_one_or_none()
                if membership:
                    membership.department_id = dept.id
                else:
                    db.add(UserDepartment(
                        id=generate_uuid(),
                        user_id=target.id,
                        department_id=dept.id,
                        is_primary=True,
                    ))

            if lane == "full":
                if "user_tier" in item.changes:
                    target.user_tier = item.user_tier
                if "is_active" in item.changes:
                    target.is_active = item.is_active
            elif lane == "executive" and "user_tier" in item.changes:
                target.user_tier = item.user_tier

            if "roles" in item.changes:
                try:
                    merged = _merge_role_assignments(ctx, role_assignments, list(before_roles))
                except HTTPException:
                    stats["failed"] += 1
                    continue
                if not dry_run:
                    await apply_user_roles(db, target, merged)

            if not dry_run:
                await write_audit_log(
                    db,
                    actor_id=actor_id,
                    target_id=target.id,
                    action="permission_import",
                    details={
                        "lane": lane,
                        "employee_no": item.employee_no,
                        "changes": item.changes,
                    },
                )
            stats["applied"] += 1
        except Exception:
            stats["failed"] += 1

    if not dry_run:
        await db.flush()
    return stats
