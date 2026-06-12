"""Execute digital employee scheduled tasks."""
from __future__ import annotations

import time
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agents.base import Task
from app.core.artifacts import (
    collect_artifacts_from_output,
    collect_artifacts_from_steps,
    merge_artifacts,
    save_text_artifact,
)
from app.core.employees.export import run_report_filename
from app.core.skills.factory import build_agent_executor
from app.core.employees.schedule import compute_next_run
from app.models_hub.connectivity import check_llm_reachable, format_llm_task_error
from app.db.base import generate_uuid
from app.db.models import (
    Agent as AgentModel,
    AgentExecution,
    DigitalEmployee,
    EmployeeScheduledTask,
    EmployeeTaskRun,
    EmployeeStatus,
    EmployeeTaskType,
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


async def _run_desktop_automation_task(
    db: AsyncSession,
    task: EmployeeScheduledTask,
    employee: DigitalEmployee,
    run: EmployeeTaskRun,
    task_config: dict[str, Any],
    start: float,
) -> None:
    from app.core.desktop.service import replay_demo_for_user

    user_id = employee.owner_id
    if not user_id:
        raise ValueError("Employee owner_id is required for desktop automation tasks")

    demo_id = task_config.get("demo_id")
    demo_name = task_config.get("demo_name")
    if not demo_id and not demo_name:
        raise ValueError("task_config.demo_name or demo_id is required for desktop_automation")

    timeout_s = float(task_config.get("timeout_s") or 120)
    result = await replay_demo_for_user(
        user_id,
        demo_id=str(demo_id) if demo_id else None,
        demo_name=str(demo_name).strip() if demo_name else None,
        instructions=str(task_config.get("instructions") or "").strip() or None,
        timeout_s=timeout_s,
        confirmed=bool(task_config.get("auto_confirm") or task_config.get("confirmed")),
        require_confirmation=False if task_config.get("auto_confirm") else None,
    )

    duration_ms = int((time.monotonic() - start) * 1000)
    if not result.get("ok"):
        run.status = ExecutionStatus.failed
        run.error_message = str(result.get("error") or "desktop replay failed")
        run.duration_ms = duration_ms
        run.output_data = {"desktop_result": result}
        task.last_status = "failed"
        return

    output_text = str(result.get("message") or "Desktop replay completed.")
    report_name = run_report_filename(run, task)
    report_md = (
        f"# {employee.name} · {task.name}\n\n"
        f"## Desktop Demo\n\n{demo_name or demo_id}\n\n"
        f"## Result\n\n{output_text}\n"
    )
    artifacts = merge_artifacts([], [save_text_artifact(report_md, report_name)])
    run.status = ExecutionStatus.completed
    run.output_data = {
        "output": output_text,
        "desktop_result": result,
        "artifacts": artifacts,
        "report_filename": report_name,
    }
    run.duration_ms = duration_ms
    task.last_status = "completed"


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
    task_type = task.task_type
    if hasattr(task_type, "value"):
        task_type = task_type.value

    prompt = str(task_config.get("prompt") or task_config.get("task") or "").strip()
    if task_type == EmployeeTaskType.agent.value and not prompt:
        raise ValueError("task_config.prompt is required")

    run = EmployeeTaskRun(
        id=generate_uuid(),
        task_id=task.id,
        employee_id=employee.id,
        status=ExecutionStatus.running,
        triggered_by=TaskTrigger(triggered_by),
        input_data={
            "task_type": task_type,
            "prompt": prompt,
            "task_config": task_config,
        },
    )
    db.add(run)
    await db.flush()

    start = time.monotonic()
    ctx_token = None
    from app.core.auth.context import set_current_user_id, reset_current_user_id
    if employee.owner_id:
        ctx_token = set_current_user_id(employee.owner_id)

    try:
        if task_type == EmployeeTaskType.desktop_automation.value:
            await _run_desktop_automation_task(db, task, employee, run, task_config, start)
            _finalize_task_schedule(task)
            await db.flush()
            return run

        agent_model = await _resolve_agent(db, employee)
        if not agent_model:
            run.status = ExecutionStatus.failed
            run.error_message = f"Agent not found: {employee.agent_id}"
            _finalize_task_schedule(task)
            await db.flush()
            return run

        ok, detail = await check_llm_reachable(
            agent_model.llm_provider,
            agent_model.llm_model,
            db,
        )
        if not ok:
            raise ConnectionError(detail)

        from app.core.auth.context import set_current_user_id, reset_current_user_id
        from app.core.harness.context import HarnessContext, reset_harness_context, set_harness_context

        owner_id = employee.owner_id
        harness_token = None
        auth_token = None
        if owner_id:
            auth_token = set_current_user_id(owner_id)
            harness_token = set_harness_context(
                HarnessContext(
                    user_id=owner_id,
                    source="employee",
                    source_id=run.id,
                    auto_confirm=True,
                )
            )

        try:
            executor = await build_agent_executor(db, agent_model)
            result = await executor.run(
                Task(description=prompt),
                context=task_config.get("context") if isinstance(task_config.get("context"), dict) else None,
                db=db,
            )
        finally:
            if harness_token is not None:
                reset_harness_context(harness_token)
            if auth_token is not None:
                reset_current_user_id(auth_token)
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

        artifacts = merge_artifacts(
            collect_artifacts_from_steps(result.get("steps")),
            collect_artifacts_from_output(result.get("output")),
        )
        output_text = str(result.get("output") or "").strip()
        report_name: str | None = None
        if output_text:
            report_name = run_report_filename(run, task)
            report_md = (
                f"# {employee.name} · {task.name}\n\n"
                f"## Task\n\n{prompt}\n\n"
                f"## Output\n\n{output_text}\n"
            )
            artifacts = merge_artifacts(artifacts, [save_text_artifact(report_md, report_name)])
        run.status = ExecutionStatus.completed
        run.output_data = {
            "output": result.get("output"),
            "steps_count": len(result.get("steps") or []),
            "artifacts": artifacts,
            "report_filename": report_name if output_text else None,
        }
        run.token_usage = result.get("token_usage", {})
        run.duration_ms = duration_ms
        run.agent_execution_id = agent_exec.id
        task.last_status = "completed"
    except Exception as exc:
        run.status = ExecutionStatus.failed
        agent_model = await _resolve_agent(db, employee)
        run.error_message = format_llm_task_error(exc, agent_model) if agent_model else str(exc)
        run.duration_ms = int((time.monotonic() - start) * 1000)
        task.last_status = "failed"
        logger.error("employee_task_failed", task_id=task.id, error=str(exc))
    finally:
        if ctx_token is not None:
            reset_current_user_id(ctx_token)

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
