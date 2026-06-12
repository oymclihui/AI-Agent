"""Aggregate dashboard metrics for the operations big screen."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.employees.scheduler import EmployeeScheduler
from app.core.auth.permissions import DataScope, scope_employees_query
from app.db.models import (
    Agent,
    DigitalEmployee,
    EmployeeScheduledTask,
    EmployeeStatus,
    EmployeeTaskRun,
    ExecutionStatus,
    KnowledgeBase,
    Skill,
    Workflow,
)

DASHBOARD_TZ = ZoneInfo("Asia/Shanghai")
SUMMARY_MAX_LEN = 120


def _truncate(text: str | None, max_len: int = SUMMARY_MAX_LEN) -> str | None:
    if not text:
        return None
    text = " ".join(str(text).split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _run_output_summary(output_data: dict | None) -> str | None:
    if not output_data:
        return None
    raw = output_data.get("output")
    if isinstance(raw, str):
        return _truncate(raw)
    if isinstance(raw, dict):
        for key in ("text", "content", "message", "summary"):
            if raw.get(key):
                return _truncate(str(raw[key]))
    return _truncate(str(raw)) if raw else None


def _sum_tokens(runs: list[EmployeeTaskRun]) -> dict[str, int]:
    total = prompt = completion = 0
    for run in runs:
        usage = run.token_usage or {}
        if not isinstance(usage, dict):
            continue
        total += int(usage.get("total_tokens") or usage.get("total") or 0)
        prompt += int(usage.get("prompt_tokens") or 0)
        completion += int(usage.get("completion_tokens") or 0)
    return {
        "total_tokens": total,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
    }


def _shanghai_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime, datetime]:
    now_local = (now or datetime.now(timezone.utc)).astimezone(DASHBOARD_TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local, start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _derive_operational_status(
    employee: DigitalEmployee,
    today_runs: list[EmployeeTaskRun],
    has_running: bool,
) -> str:
    if employee.status != EmployeeStatus.active:
        return "paused"
    if has_running:
        return "running"
    if today_runs:
        latest = max(today_runs, key=lambda r: r.created_at)
        st = latest.status.value if hasattr(latest.status, "value") else str(latest.status)
        if st == ExecutionStatus.failed.value:
            return "failed"
        if st == ExecutionStatus.completed.value:
            return "completed"
    enabled_tasks = [t for t in (employee.scheduled_tasks or []) if t.enabled]
    if enabled_tasks:
        return "idle"
    return "idle"


async def build_dashboard_overview(db: AsyncSession, scope: DataScope | None = None) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    day_start_local, day_start_utc, day_end_utc = _shanghai_day_bounds(now_utc)

    emp_query = (
        select(DigitalEmployee)
        .options(
            selectinload(DigitalEmployee.scheduled_tasks),
            selectinload(DigitalEmployee.agent),
        )
        .order_by(DigitalEmployee.updated_at.desc())
    )
    if scope is not None:
        emp_query = emp_query.where(scope_employees_query(DigitalEmployee, scope))

    emp_result = await db.execute(emp_query)
    employees = emp_result.scalars().all()
    visible_employee_ids = {e.id for e in employees}

    runs_result = await db.execute(
        select(EmployeeTaskRun)
        .where(
            EmployeeTaskRun.created_at >= day_start_utc,
            EmployeeTaskRun.created_at < day_end_utc,
        )
        .order_by(EmployeeTaskRun.created_at.desc())
    )
    today_runs = [r for r in runs_result.scalars().all() if r.employee_id in visible_employee_ids]

    task_ids = {r.task_id for r in today_runs}
    task_names: dict[str, str] = {}
    if task_ids:
        tasks_result = await db.execute(
            select(EmployeeScheduledTask.id, EmployeeScheduledTask.name).where(
                EmployeeScheduledTask.id.in_(task_ids)
            )
        )
        task_names = {row[0]: row[1] for row in tasks_result.all()}

    runs_by_employee: dict[str, list[EmployeeTaskRun]] = {}
    for run in today_runs:
        runs_by_employee.setdefault(run.employee_id, []).append(run)

    hourly = {h: {"count": 0, "completed": 0, "failed": 0} for h in range(24)}
    completed = failed = running = 0
    durations: list[int] = []
    active_employee_ids: set[str] = set()

    for run in today_runs:
        active_employee_ids.add(run.employee_id)
        st = run.status.value if hasattr(run.status, "value") else str(run.status)
        if st == ExecutionStatus.completed.value:
            completed += 1
        elif st == ExecutionStatus.failed.value:
            failed += 1
        elif st == ExecutionStatus.running.value:
            running += 1
        if run.duration_ms:
            durations.append(run.duration_ms)
        hour = run.created_at.astimezone(DASHBOARD_TZ).hour
        hourly[hour]["count"] += 1
        if st == ExecutionStatus.completed.value:
            hourly[hour]["completed"] += 1
        elif st == ExecutionStatus.failed.value:
            hourly[hour]["failed"] += 1

    running_employee_ids = {
        r.employee_id
        for r in today_runs
        if (r.status.value if hasattr(r.status, "value") else str(r.status))
        == ExecutionStatus.running.value
    }

    employee_cards: list[dict[str, Any]] = []
    for emp in employees:
        emp_runs = runs_by_employee.get(emp.id, [])
        emp_today_success = sum(
            1
            for r in emp_runs
            if (r.status.value if hasattr(r.status, "value") else str(r.status))
            == ExecutionStatus.completed.value
        )
        emp_today_failed = sum(
            1
            for r in emp_runs
            if (r.status.value if hasattr(r.status, "value") else str(r.status))
            == ExecutionStatus.failed.value
        )
        enabled = [t for t in (emp.scheduled_tasks or []) if t.enabled]
        next_times = [t.next_run_at for t in enabled if t.next_run_at]
        next_run = min(next_times) if next_times else None

        last_run_data = None
        if emp_runs:
            latest = max(emp_runs, key=lambda r: r.created_at)
            last_run_data = {
                "id": latest.id,
                "status": latest.status.value if hasattr(latest.status, "value") else str(latest.status),
                "at": latest.created_at,
                "task_name": task_names.get(latest.task_id),
                "task_id": latest.task_id,
                "summary": _run_output_summary(latest.output_data)
                or _truncate((latest.input_data or {}).get("prompt")),
                "triggered_by": latest.triggered_by.value
                if hasattr(latest.triggered_by, "value")
                else str(latest.triggered_by),
                "duration_ms": latest.duration_ms,
            }

        employee_cards.append({
            "id": emp.id,
            "name": emp.name,
            "title": emp.title,
            "agent_name": emp.agent.name if emp.agent else None,
            "employee_status": emp.status.value if hasattr(emp.status, "value") else str(emp.status),
            "operational_status": _derive_operational_status(
                emp, emp_runs, emp.id in running_employee_ids
            ),
            "task_count": len(emp.scheduled_tasks or []),
            "enabled_tasks": len(enabled),
            "next_run_at": next_run,
            "today_runs": len(emp_runs),
            "today_success": emp_today_success,
            "today_failed": emp_today_failed,
            "last_run": last_run_data,
        })

    employee_cards.sort(key=lambda e: (-e["today_runs"], e["name"]))

    recent_slice = today_runs[:30]
    if len(recent_slice) < 30:
        extra_query = (
            select(EmployeeTaskRun)
            .where(EmployeeTaskRun.created_at < day_start_utc)
            .order_by(EmployeeTaskRun.created_at.desc())
            .limit(100)
        )
        extra_result = await db.execute(extra_query)
        for run in extra_result.scalars().all():
            if run.employee_id in visible_employee_ids:
                recent_slice.append(run)
            if len(recent_slice) >= 30:
                break

    emp_name_map = {e.id: e.name for e in employees}
    all_task_ids = {r.task_id for r in recent_slice} - set(task_names.keys())
    if all_task_ids:
        extra_tasks = await db.execute(
            select(EmployeeScheduledTask.id, EmployeeScheduledTask.name).where(
                EmployeeScheduledTask.id.in_(all_task_ids)
            )
        )
        task_names.update({row[0]: row[1] for row in extra_tasks.all()})

    recent_runs = []
    for run in sorted(recent_slice, key=lambda r: r.created_at, reverse=True)[:30]:
        recent_runs.append({
            "id": run.id,
            "employee_id": run.employee_id,
            "employee_name": emp_name_map.get(run.employee_id, run.employee_id[:8]),
            "task_id": run.task_id,
            "task_name": task_names.get(run.task_id),
            "status": run.status.value if hasattr(run.status, "value") else str(run.status),
            "triggered_by": run.triggered_by.value
            if hasattr(run.triggered_by, "value")
            else str(run.triggered_by),
            "created_at": run.created_at,
            "duration_ms": run.duration_ms,
            "prompt_summary": _truncate((run.input_data or {}).get("prompt")),
            "output_summary": _run_output_summary(run.output_data),
        })

    async def _count(model) -> int:
        result = await db.execute(select(func.count()).select_from(model))
        return result.scalar() or 0

    platform = {
        "employees": len(employees),
        "agents": await _count(Agent),
        "skills": await _count(Skill),
        "workflows": await _count(Workflow),
        "knowledge_bases": await _count(KnowledgeBase),
        "active_employees": sum(
            1 for e in employees if e.status == EmployeeStatus.active
        ),
        "enabled_tasks": sum(
            len([t for t in (e.scheduled_tasks or []) if t.enabled]) for e in employees
        ),
    }

    sched = EmployeeScheduler.get_instance().status()

    return {
        "generated_at": now_utc,
        "timezone": "Asia/Shanghai",
        "day_start": day_start_local,
        "scheduler": {
            "running": bool(sched.get("running")),
            "last_tick": sched.get("last_tick"),
            "last_error": sched.get("last_error"),
            "interval_seconds": sched.get("poll_interval_seconds", sched.get("interval_seconds", 30)),
        },
        "health": {"status": "healthy"},
        "platform": platform,
        "today": {
            "total_runs": len(today_runs),
            "completed": completed,
            "failed": failed,
            "running": running,
            "active_employees": len(active_employee_ids),
            "avg_duration_ms": int(sum(durations) / len(durations)) if durations else None,
            "token_usage": _sum_tokens(today_runs),
        },
        "hourly_runs": [{"hour": h, **hourly[h]} for h in range(24)],
        "employees": employee_cards,
        "recent_runs": recent_runs,
    }
