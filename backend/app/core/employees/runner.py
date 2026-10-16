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


async def _run_workflow_task(
    db: AsyncSession,
    task: EmployeeScheduledTask,
    employee: DigitalEmployee,
    run: EmployeeTaskRun,
    task_config: dict[str, Any],
    start: float,
) -> None:
    from app.core.workflow.runner import execute_workflow_by_id

    workflow_id = str(task_config.get("workflow_id") or "").strip()
    if not workflow_id:
        raise ValueError("task_config.workflow_id is required for workflow tasks")

    input_data = task_config.get("input_data") if isinstance(task_config.get("input_data"), dict) else {}
    if task_config.get("prompt"):
        input_data = {**input_data, "prompt": task_config["prompt"]}

    result = await execute_workflow_by_id(
        db,
        workflow_id,
        input_data,
        owner_user_id=employee.owner_id,
        persist_execution=True,
    )
    output_data = result.get("output_data") or {}
    final_output = str(output_data.get("final_output") or "").strip()
    duration_ms = int((time.monotonic() - start) * 1000)
    report_name: str | None = None
    artifacts = output_data.get("artifacts") or []
    if final_output:
        report_name = run_report_filename(run, task)
        report_md = (
            f"# {employee.name} · {task.name}\n\n"
            f"## Workflow\n\n{workflow_id}\n\n"
            f"## Output\n\n{final_output}\n"
        )
        artifacts = merge_artifacts(artifacts, [save_text_artifact(report_md, report_name)])

    run.status = ExecutionStatus.completed
    run.output_data = {
        "output": final_output,
        "workflow_execution_id": result.get("workflow_execution_id"),
        "artifacts": artifacts,
        "report_filename": report_name if final_output else None,
        **{k: v for k, v in output_data.items() if k not in ("artifacts",)},
    }
    run.token_usage = result.get("token_usage") or {}
    run.duration_ms = duration_ms
    task.last_status = "completed"


async def _run_crew_task(
    db: AsyncSession,
    task: EmployeeScheduledTask,
    employee: DigitalEmployee,
    run: EmployeeTaskRun,
    task_config: dict[str, Any],
    start: float,
) -> None:
    from app.core.orchestrator.runner import execute_crew_from_config

    owner_id = employee.owner_id
    auth_token = None
    harness_token = None
    from app.core.auth.context import reset_current_user_id, set_current_user_id
    from app.core.harness.context import (
        HarnessContext,
        ensure_session_directory,
        reset_harness_context,
        set_harness_context,
    )

    if owner_id:
        auth_token = set_current_user_id(owner_id)
        harness_token = set_harness_context(
            HarnessContext(
                user_id=owner_id,
                source="employee",
                source_id=run.id,
                auto_confirm=True,
                working_directory=ensure_session_directory(run.id),
            )
        )
    try:
        result = await execute_crew_from_config(db, task_config)
    finally:
        if harness_token is not None:
            reset_harness_context(harness_token)
        if auth_token is not None:
            reset_current_user_id(auth_token)

    output_text = str(result.get("output") or "").strip()
    duration_ms = int((time.monotonic() - start) * 1000)
    report_name: str | None = None
    artifacts: list = []
    if output_text:
        report_name = run_report_filename(run, task)
        report_md = (
            f"# {employee.name} · {task.name}\n\n"
            f"## Crew goal\n\n{task_config.get('goal') or task_config.get('prompt')}\n\n"
            f"## Output\n\n{output_text}\n"
        )
        artifacts = [save_text_artifact(report_md, report_name)]

    run.status = ExecutionStatus.completed
    run.output_data = {
        "output": output_text,
        "task_outputs": result.get("task_outputs"),
        "artifacts": artifacts,
        "report_filename": report_name if output_text else None,
    }
    run.token_usage = result.get("token_usage") or {}
    run.duration_ms = duration_ms
    task.last_status = "completed"


async def _run_data_ask_task(
    db: AsyncSession,
    task: EmployeeScheduledTask,
    employee: DigitalEmployee,
    run: EmployeeTaskRun,
    task_config: dict[str, Any],
    prompt: str,
    start: float,
) -> None:
    from app.db.models import DataSource, User as UserModel
    from app.core.data_ask.service import run_data_ask, run_multi_data_ask
    from app.core.data_ask.intelligence.nl2sql import analyze_results

    ds_id = str(task_config.get("data_source_id") or "")
    ds = await db.get(DataSource, ds_id)
    if ds and not ds.report_enabled:
        raise ValueError("Scheduled reports disabled for this data source")

    owner = await db.get(UserModel, employee.owner_id) if employee.owner_id else None
    queries_cfg = task_config.get("queries")
    if isinstance(queries_cfg, list) and queries_cfg:
        multi = await run_multi_data_ask(
            db,
            data_source_id=ds_id,
            queries=[{"name": q.get("name"), "question": q.get("question")} for q in queries_cfg if q.get("question")],
            user=owner,
        )
        snapshot_parts = []
        for block in multi:
            snapshot_parts.append(f"### {block.get('name')}\nSQL: {block.get('sql')}\nRows: {block.get('row_count')}")
            for row in block.get("rows", [])[:20]:
                snapshot_parts.append("\t".join(str(c) for c in row))
        snapshot = "\n".join(snapshot_parts)
        question = str(task_config.get("query") or "汇总多维度业务指标")
        qr = multi[0] if multi else {"sql": "", "columns": [], "rows": [], "row_count": 0}
    else:
        question = str(task_config.get("query") or "汇总今日关键业务指标与异常项").strip()
        qr = await run_data_ask(
            db,
            data_source_id=ds_id,
            question=question,
            user=owner,
            llm_provider=None,
            llm_model=None,
        )
        snapshot_lines = [
            f"Columns: {', '.join(qr['columns'])}",
            f"Rows: {qr['row_count']}",
        ]
        for row in qr.get("rows", [])[:50]:
            snapshot_lines.append("\t".join(str(c) for c in row))
        snapshot = "\n".join(snapshot_lines)
    filled_prompt = prompt.replace("{data_snapshot}", snapshot)
    agent_model = await _resolve_agent(db, employee)
    if not agent_model:
        raise ValueError(f"Agent not found: {employee.agent_id}")
    report_body = await analyze_results(
        db,
        question=filled_prompt,
        sql=qr.get("sql") or "",
        columns=qr.get("columns") or [],
        rows=qr.get("rows") or [],
        llm_provider=agent_model.llm_provider,
        llm_model=agent_model.llm_model,
    )
    duration_ms = int((time.monotonic() - start) * 1000)
    report_name = run_report_filename(run, task)
    report_md = (
        f"# {employee.name} · {task.name}\n\n"
        f"## 数据快照\n\n{snapshot[:4000]}\n\n"
        f"## 分析报告\n\n{report_body}\n"
    )
    artifacts = [save_text_artifact(report_md, report_name)]
    run.status = ExecutionStatus.completed
    run.output_data = {
        "output": report_body,
        "sql": qr.get("sql"),
        "row_count": qr.get("row_count"),
        "multi_query_count": len(queries_cfg) if isinstance(queries_cfg, list) else 1,
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
    from app.models_hub.user_credentials import resume_personal_keys, suspend_personal_keys
    token = suspend_personal_keys()
    try:
        return await _run_scheduled_task_body(db, task, employee, triggered_by=triggered_by)
    finally:
        resume_personal_keys(token)


async def _run_scheduled_task_body(
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
    if task_type == EmployeeTaskType.workflow.value and not task_config.get("workflow_id"):
        raise ValueError("task_config.workflow_id is required")
    if task_type == EmployeeTaskType.crew.value:
        agent_ids = task_config.get("agent_ids") or []
        if not agent_ids and not task_config.get("agent_id"):
            raise ValueError("task_config.agent_ids is required for crew tasks")
        if not (task_config.get("goal") or task_config.get("prompt") or prompt):
            raise ValueError("task_config.goal is required for crew tasks")

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

        if task_type == EmployeeTaskType.workflow.value:
            await _run_workflow_task(db, task, employee, run, task_config, start)
            _finalize_task_schedule(task)
            await db.flush()
            return run

        if task_type == EmployeeTaskType.crew.value:
            await _run_crew_task(db, task, employee, run, task_config, start)
            _finalize_task_schedule(task)
            await db.flush()
            return run

        if task_config.get("data_ask") and task_config.get("data_source_id"):
            await _run_data_ask_task(db, task, employee, run, task_config, prompt, start)
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
        from app.core.harness.context import (
        HarnessContext,
        ensure_session_directory,
        reset_harness_context,
        set_harness_context,
    )

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
                    working_directory=ensure_session_directory(run.id),
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
        if run.status == ExecutionStatus.completed:
            try:
                from app.core.wecom.push import push_employee_report

                wecom_result = await push_employee_report(db, employee=employee, task=task, run=run)
                payload = dict(run.output_data or {})
                payload["wecom"] = wecom_result
                run.output_data = payload
            except Exception:
                logger.exception("wecom_employee_push_failed", run_id=run.id)

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
