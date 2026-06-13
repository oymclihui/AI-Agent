"""Build digital employee org chart from department + parent_employee_id + metadata."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.permissions import DataScope, scope_employees_query, scope_departments_query
from app.core.employees.org_catalog import display_hints
from app.db.models import Department, DigitalEmployee, EmployeeScheduledTask


def _meta(emp: DigitalEmployee) -> dict[str, Any]:
    return emp.metadata_ or {}


def _org_rank(emp: DigitalEmployee) -> int:
    meta = _meta(emp)
    try:
        return int(meta.get("org_rank", emp.sort_order or 0))
    except (TypeError, ValueError):
        return emp.sort_order or 0


async def link_parents_from_metadata(
    db: AsyncSession,
    employees: list[DigitalEmployee],
    *,
    commit: bool = False,
) -> int:
    """Resolve metadata.org_reports_to (template_id) → parent_employee_id."""
    by_template: dict[str, DigitalEmployee] = {}
    for emp in employees:
        tid = str(_meta(emp).get("template_id") or "")
        if tid and tid not in by_template:
            by_template[tid] = emp

    updated = 0
    for emp in employees:
        reports_to_template = _meta(emp).get("org_reports_to")
        if not reports_to_template:
            continue
        parent = by_template.get(str(reports_to_template))
        if not parent or parent.id == emp.id:
            continue
        if emp.parent_employee_id != parent.id:
            emp.parent_employee_id = parent.id
            updated += 1

    if updated and commit:
        await db.flush()
    return updated


async def infer_parents_from_department_leaders(
    db: AsyncSession,
    employees: list[DigitalEmployee],
    departments: dict[str, Department],
) -> int:
    """Fallback: attach employees to dept leader's employee in same department."""
    by_dept: dict[str, list[DigitalEmployee]] = defaultdict(list)
    for emp in employees:
        if emp.department_id:
            by_dept[emp.department_id].append(emp)

    leader_employee: dict[str, str] = {}
    for dept_id, dept in departments.items():
        if not dept.leader_user_id:
            continue
        for emp in by_dept.get(dept_id, []):
            if emp.owner_id == dept.leader_user_id:
                leader_employee[dept_id] = emp.id
                break

    updated = 0
    for emp in employees:
        if emp.parent_employee_id or not emp.department_id:
            continue
        dept = departments.get(emp.department_id)
        if not dept or not dept.parent_id:
            continue
        parent_dept = departments.get(dept.parent_id)
        if not parent_dept:
            continue
        parent_emp_id = leader_employee.get(parent_dept.id)
        if parent_emp_id and parent_emp_id != emp.id:
            emp.parent_employee_id = parent_emp_id
            updated += 1
    return updated


def _build_levels(
    employees: list[DigitalEmployee],
    task_counts: dict[str, int],
    dept_names: dict[str, str],
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
    by_id = {e.id: e for e in employees}
    children_map: dict[str | None, list[DigitalEmployee]] = defaultdict(list)
    for emp in employees:
        parent_id = emp.parent_employee_id if emp.parent_employee_id in by_id else None
        children_map[parent_id].append(emp)

    for key in children_map:
        children_map[key].sort(key=lambda e: (_org_rank(e), e.sort_order or 0, e.name))

    roots = children_map[None]
    if not roots:
        roots = [e for e in employees if not e.parent_employee_id or e.parent_employee_id not in by_id]

    def node_dict(emp: DigitalEmployee, depth: int) -> dict[str, Any]:
        hints = display_hints(_meta(emp), emp.title)
        return {
            "id": emp.id,
            "name": emp.name,
            "title": emp.title,
            "status": emp.status.value if hasattr(emp.status, "value") else str(emp.status),
            "task_count": task_counts.get(emp.id, 0),
            "department_id": emp.department_id,
            "department_name": dept_names.get(emp.department_id or ""),
            "parent_employee_id": emp.parent_employee_id,
            "depth": depth,
            "sort_order": emp.sort_order or 0,
            **hints,
        }

    levels: list[list[dict[str, Any]]] = []
    assigned: set[str] = set()
    queue: list[tuple[DigitalEmployee, int]] = [(r, 0) for r in roots]
    depth_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)

    while queue:
        emp, depth = queue.pop(0)
        if emp.id in assigned:
            continue
        assigned.add(emp.id)
        depth_rows[depth].append(node_dict(emp, depth))
        for child in children_map.get(emp.id, []):
            queue.append((child, depth + 1))

    unassigned = [node_dict(e, 0) for e in employees if e.id not in assigned]
    if depth_rows:
        max_depth = max(depth_rows.keys())
        levels = [depth_rows[d] for d in range(max_depth + 1)]
    return levels, [node_dict(r, 0) for r in roots], unassigned


def _tree_title(
    employees: list[DigitalEmployee],
    departments: dict[str, Department],
) -> tuple[str, str, str, str]:
    groups = {_meta(e).get("org_group") for e in employees if _meta(e).get("org_group")}
    if "nev-finance" in groups:
        return (
            "制造企业 · 财务组织架构",
            "Manufacturing · Finance Organization",
            "层级越高越靠上；连线表示汇报关系；标签为定时任务节奏。",
            "Higher roles on top; lines show reporting; tags show task cadence.",
        )
    root_depts = [d for d in departments.values() if d.level == 0 or not d.parent_id]
    if root_depts:
        name = root_depts[0].name
        return (
            f"{name} · 数字员工架构",
            f"{name} · Digital Employee Org",
            "按组织与权限配置的部门及汇报关系自动生成。",
            "Auto-generated from org settings, departments, and reporting lines.",
        )
    return (
        "数字员工组织架构",
        "Digital Employee Organization",
        "按汇报关系与部门配置自动生成。",
        "Auto-generated from reporting lines and departments.",
    )


async def build_employee_org_tree(
    db: AsyncSession,
    scope: DataScope,
    *,
    sync_links: bool = True,
) -> dict[str, Any]:
    emp_result = await db.execute(
        select(DigitalEmployee)
        .where(scope_employees_query(DigitalEmployee, scope))
        .order_by(DigitalEmployee.sort_order, DigitalEmployee.name)
    )
    employees = list(emp_result.scalars().all())

    dept_result = await db.execute(
        select(Department)
        .where(scope_departments_query(Department, scope))
        .where(Department.is_active == True)
        .order_by(Department.level, Department.sort_order, Department.name)
    )
    departments = {d.id: d for d in dept_result.scalars().all()}
    if not departments and employees:
        extra_ids = {e.department_id for e in employees if e.department_id}
        if extra_ids:
            extra = await db.execute(
                select(Department).where(Department.id.in_(extra_ids), Department.is_active == True)
            )
            departments = {d.id: d for d in extra.scalars().all()}
    dept_names = {d.id: d.name for d in departments.values()}

    if sync_links and employees:
        await link_parents_from_metadata(db, employees)
        await infer_parents_from_department_leaders(db, employees, departments)
        await db.flush()

    task_counts: dict[str, int] = {}
    if employees:
        ids = [e.id for e in employees]
        count_result = await db.execute(
            select(EmployeeScheduledTask.employee_id, func.count())
            .where(EmployeeScheduledTask.employee_id.in_(ids))
            .group_by(EmployeeScheduledTask.employee_id)
        )
        task_counts = {row[0]: row[1] for row in count_result.all()}

    levels, roots, unassigned = _build_levels(employees, task_counts, dept_names)
    title_zh, title_en, sub_zh, sub_en = _tree_title(employees, departments)

    return {
        "title_zh": title_zh,
        "title_en": title_en,
        "subtitle_zh": sub_zh,
        "subtitle_en": sub_en,
        "levels": levels,
        "roots": roots,
        "unassigned": unassigned,
        "department_count": len(departments),
        "employee_count": len(employees),
    }


async def sync_org_links_for_scope(db: AsyncSession, scope: DataScope) -> dict[str, int]:
    emp_result = await db.execute(
        select(DigitalEmployee).where(scope_employees_query(DigitalEmployee, scope))
    )
    employees = list(emp_result.scalars().all())
    dept_result = await db.execute(
        select(Department).where(scope_departments_query(Department, scope)).where(Department.is_active == True)
    )
    departments = {d.id: d for d in dept_result.scalars().all()}
    from_meta = await link_parents_from_metadata(db, employees)
    from_dept = await infer_parents_from_department_leaders(db, employees, departments)
    await db.flush()
    return {"from_metadata": from_meta, "from_department": from_dept, "total": from_meta + from_dept}
