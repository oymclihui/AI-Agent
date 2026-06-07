"""Execute digital employee scheduled tasks."""
from __future__ import annotations

import time
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agents.base import Task
from app.core.skills.factory import build_agent_executor
from app.core.employees.schedule import compute_next_run
from app.db.base import generate_uuid
from app.db.models import (
    Agent as AgentModel,
    AgentExecution,
    DigitalEmployee,
    EmployeeScheduledTask,
    EmployeeTaskRun,
    EmployeeStatus,
    ExecutionStatus,
    TaskTrigger,
)

logger = structlog.get_logger(__name__)


async def _resolve_agent(db: AsyncSession, employee: DigitalEmployee) -> AgentModel | None:
    agent = await db.get(AgentModel, employee.agent_id)
    if not agent:
        return None
    extra = employee.skills_config or []
    if extra:
        merged = list(agent.skills_config or [])
        existing_ids = {s.get("skill_id") for s in merged if isinstance(s, dict)}
        for item in extra:
            if isinstance(item, dict) and item.get("skill_id") and item["skill_id"] not in existing_ids:
                merged.append(item)
        agent.skills_config = merged
    return agent


async def run_scheduled_task(
    db: AsyncSession,
    task: EmployeeScheduledTask,
    employee: DigitalEmployee,
    *,
    triggered_by: str = "manual",
) -> EmployeeTaskRun:
    if employee.status != EmployeeStatus.active:
        raise ValueError("Employee is not active")

    task_config = task.task_config or {}
    prompt = str(task_config.get("prompt") or task_config.get("task") or "").strip()
    if not prompt:
        raise ValueError("task_config.prompt is required")

    run = EmployeeTaskRun(
        id=generate_uuid(),
        task_id=task.id,
        employee_id=employee.id,
        status=ExecutionStatus.running,
        triggered_by=TaskTrigger(triggered_by),
        input_data={"prompt": prompt, "context": task_config.get("context", {})},
    )
    db.add(run)
    await db.flush()

    agent_model = await _resolve_agent(db, employee)
    if not agent_model:
        run.status = ExecutionStatus.failed
        run.error_message = f"Agent not found: {employee.agent_id}"
        _finalize_task_schedule(task)
        await db.flush()
        return run

    start = time.monotonic()
    try:
        executor = await build_agent_executor(db, agent_model)
        result = await executor.run(
            Task(description=prompt),
            context=task_config.get("context") if isinstance(task_config.get("context"), dict) else None,
        )
        duration_ms = int((time.monotonic() - start) * 1000)

        agent_exec = AgentExecution(
            id=generate_uuid(),
            agent_id=agent_model.id,
            task_description=prompt[:2000],
            status=ExecutionStatus.completed,
            output=result.get("output"),
            token_usage=result.get("token_usage", {}),
            steps=result.get("steps", []),
        )
        db.add(agent_exec)

        run.status = ExecutionStatus.completed
        run.output_data = {
            "output": result.get("output"),
            "steps_count": len(result.get("steps") or []),
        }
        run.token_usage = result.get("token_usage", {})
        run.duration_ms = duration_ms
        run.agent_execution_id = agent_exec.id
        task.last_status = "completed"
    except Exception as exc:
        run.status = ExecutionStatus.failed
        run.error_message = str(exc)[:4000]
        run.duration_ms = int((time.monotonic() - start) * 1000)
        task.last_status = "failed"
        logger.error("employee_task_failed", task_id=task.id, error=str(exc))

    _finalize_task_schedule(task)
    await db.flush()
    return run


def _finalize_task_schedule(task: EmployeeScheduledTask) -> None:
    from datetime import datetime, timezone

    task.last_run_at = datetime.now(timezone.utc)
    if task.enabled:
        try:
            task.next_run_at = compute_next_run(
                task.schedule_type.value if hasattr(task.schedule_type, "value") else str(task.schedule_type),
                cron_expression=task.cron_expression,
                interval_seconds=task.interval_seconds,
                timezone_name=task.timezone,
                from_dt=task.last_run_at,
            )
        except Exception as exc:
            logger.warning("next_run_compute_failed", task_id=task.id, error=str(exc))
            task.next_run_at = None
    else:
        task.next_run_at = None
