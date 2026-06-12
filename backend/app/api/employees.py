from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.session import get_db
from app.db.models import (
    Agent as AgentModel,
    DigitalEmployee,
    EmployeeScheduledTask,
    EmployeeTaskRun,
    EmployeeStatus,
    User,
)
from app.core.auth.deps import get_current_user
from app.core.auth.permissions import (
    assert_permission,
    require_employee_read,
    require_employee_write,
    resolve_data_scope,
    scope_employees_query,
)
from app.db.base import generate_uuid
from app.schemas.employee import (
    EmployeeCreate,
    EmployeeUpdate,
    EmployeeResponse,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
    ScheduledTaskResponse,
    TaskRunResponse,
    EmployeeTemplateSummary,
    EmployeeTemplateImportRequest,
    EmployeeTemplateImportResponse,
    SaveRunToKnowledgeRequest,
)
from app.core.employees.export import _run_markdown, export_run_to_knowledge
from app.core.employees.schedule import compute_next_run, validate_schedule
from app.core.employees.runner import run_scheduled_task
from app.core.employees.scheduler import EmployeeScheduler

router = APIRouter(prefix="/employees", tags=["Digital Employees"])


def _employee_response(emp: DigitalEmployee, task_count: int = 0) -> EmployeeResponse:
    return EmployeeResponse(
        id=emp.id,
        name=emp.name,
        title=emp.title,
        description=emp.description,
        status=emp.status,
        agent_id=emp.agent_id,
        skills_config=emp.skills_config or [],
        knowledge_base_ids=emp.knowledge_base_ids or [],
        timezone=emp.timezone,
        task_count=task_count,
        metadata=emp.metadata_ or {},
        created_at=emp.created_at,
        updated_at=emp.updated_at,
    )


def _apply_task_schedule(task: EmployeeScheduledTask) -> None:
    st = task.schedule_type.value if hasattr(task.schedule_type, "value") else str(task.schedule_type)
    validate_schedule(st, task.cron_expression, task.interval_seconds)
    if task.enabled:
        task.next_run_at = compute_next_run(
            st,
            cron_expression=task.cron_expression,
            interval_seconds=task.interval_seconds,
            timezone_name=task.timezone,
        )
    else:
        task.next_run_at = None


def _task_run_response(run: EmployeeTaskRun, task_name: str | None = None) -> TaskRunResponse:
    return TaskRunResponse(
        id=run.id,
        task_id=run.task_id,
        employee_id=run.employee_id,
        task_name=task_name,
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
        triggered_by=run.triggered_by.value if hasattr(run.triggered_by, "value") else str(run.triggered_by),
        input_data=run.input_data or {},
        output_data=run.output_data,
        error_message=run.error_message,
        token_usage=run.token_usage or {},
        duration_ms=run.duration_ms,
        created_at=run.created_at,
    )


@router.get("/scheduler/status")
async def scheduler_status(user: User = Depends(get_current_user)):
    return EmployeeScheduler.get_instance().status()


@router.get("/", response_model=list[EmployeeResponse])
async def list_employees(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    scope = await resolve_data_scope(db, user)
    assert_permission(scope, "employees:read")
    result = await db.execute(
        select(DigitalEmployee)
        .where(scope_employees_query(DigitalEmployee, scope))
        .order_by(DigitalEmployee.updated_at.desc())
    )
    employees = result.scalars().all()
    counts: dict[str, int] = {}
    if employees:
        ids = [e.id for e in employees]
        count_result = await db.execute(
            select(EmployeeScheduledTask.employee_id, func.count())
            .where(EmployeeScheduledTask.employee_id.in_(ids))
            .group_by(EmployeeScheduledTask.employee_id)
        )
        counts = {row[0]: row[1] for row in count_result.all()}
    return [_employee_response(e, counts.get(e.id, 0)) for e in employees]


@router.get("/templates", response_model=list[EmployeeTemplateSummary])
async def list_employee_templates(user: User = Depends(get_current_user)):
    from app.core.employees.importer import list_templates
    return list_templates(user)


@router.post("/import-template", response_model=EmployeeTemplateImportResponse, status_code=status.HTTP_201_CREATED)
async def import_employee_template(
    payload: EmployeeTemplateImportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.core.employees.importer import import_template

    scope = await resolve_data_scope(db, user)
    assert_permission(scope, "employees:write")

    try:
        emp, task_count = await import_template(
            db,
            payload.template_id,
            employee_name_override=payload.employee_name,
            user=user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return EmployeeTemplateImportResponse(
        employee=_employee_response(emp, task_count),
        tasks_created=task_count,
        template_id=payload.template_id,
    )


@router.post("/", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
async def create_employee(
    payload: EmployeeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    scope = await resolve_data_scope(db, user)
    assert_permission(scope, "employees:write")

    agent = await db.get(AgentModel, payload.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    emp = DigitalEmployee(
        id=generate_uuid(),
        owner_id=user.id,
        department_id=user.primary_department_id,
        name=payload.name,
        title=payload.title,
        description=payload.description,
        status=payload.status,
        agent_id=payload.agent_id,
        skills_config=[s.model_dump() for s in payload.skills_config],
        knowledge_base_ids=payload.knowledge_base_ids,
        timezone=payload.timezone,
    )
    db.add(emp)
    await db.flush()
    await db.refresh(emp)
    return _employee_response(emp, 0)


@router.get("/{employee_id}", response_model=EmployeeResponse)
async def get_employee(
    employee_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    emp = await require_employee_read(db, user, employee_id)
    count_result = await db.execute(
        select(func.count()).where(EmployeeScheduledTask.employee_id == employee_id)
    )
    return _employee_response(emp, count_result.scalar() or 0)


@router.patch("/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: str,
    payload: EmployeeUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    emp, _scope = await require_employee_write(db, user, employee_id)

    data = payload.model_dump(exclude_none=True)
    if "agent_id" in data:
        agent = await db.get(AgentModel, data["agent_id"])
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
    if "skills_config" in data:
        data["skills_config"] = [
            s.model_dump() if hasattr(s, "model_dump") else s for s in data["skills_config"]
        ]

    for field, value in data.items():
        setattr(emp, field, value)

    await db.flush()
    count_result = await db.execute(
        select(func.count()).where(EmployeeScheduledTask.employee_id == employee_id)
    )
    return _employee_response(emp, count_result.scalar() or 0)


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_employee(
    employee_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    emp, _scope = await require_employee_write(db, user, employee_id)
    await db.delete(emp)


@router.get("/{employee_id}/tasks", response_model=list[ScheduledTaskResponse])
async def list_tasks(
    employee_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await require_employee_read(db, user, employee_id)
    result = await db.execute(
        select(EmployeeScheduledTask)
        .where(EmployeeScheduledTask.employee_id == employee_id)
        .order_by(EmployeeScheduledTask.created_at.desc())
    )
    return result.scalars().all()


@router.post("/{employee_id}/tasks", response_model=ScheduledTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    employee_id: str,
    payload: ScheduledTaskCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    emp, _scope = await require_employee_write(db, user, employee_id)

    tz = payload.timezone or emp.timezone
    try:
        validate_schedule(payload.schedule_type.value, payload.cron_expression, payload.interval_seconds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    task = EmployeeScheduledTask(
        id=generate_uuid(),
        employee_id=employee_id,
        name=payload.name,
        description=payload.description,
        enabled=payload.enabled,
        schedule_type=payload.schedule_type,
        cron_expression=payload.cron_expression,
        interval_seconds=payload.interval_seconds,
        timezone=tz,
        task_type=payload.task_type,
        task_config=payload.task_config,
        retry_max=payload.retry_max,
        timeout_seconds=payload.timeout_seconds,
    )
    _apply_task_schedule(task)
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


@router.patch("/{employee_id}/tasks/{task_id}", response_model=ScheduledTaskResponse)
async def update_task(
    employee_id: str,
    task_id: str,
    payload: ScheduledTaskUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await require_employee_write(db, user, employee_id)
    task = await _get_task(db, employee_id, task_id)
    data = payload.model_dump(exclude_none=True)
    for field, value in data.items():
        setattr(task, field, value)

    try:
        st = task.schedule_type.value if hasattr(task.schedule_type, "value") else str(task.schedule_type)
        validate_schedule(st, task.cron_expression, task.interval_seconds)
        _apply_task_schedule(task)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await db.flush()
    await db.refresh(task)
    return task


@router.delete("/{employee_id}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    employee_id: str,
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await require_employee_write(db, user, employee_id)
    task = await _get_task(db, employee_id, task_id)
    await db.delete(task)


@router.post("/{employee_id}/tasks/{task_id}/run", response_model=TaskRunResponse)
async def run_task_manually(
    employee_id: str,
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    emp, scope = await require_employee_write(db, user, employee_id)
    task = await _get_task(db, employee_id, task_id)
    try:
        run = await run_scheduled_task(db, task, emp, triggered_by="manual")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    await db.commit()
    return _task_run_response(run, task.name)


@router.get("/{employee_id}/runs", response_model=list[TaskRunResponse])
async def list_employee_runs(
    employee_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await require_employee_read(db, user, employee_id)
    result = await db.execute(
        select(EmployeeTaskRun, EmployeeScheduledTask.name)
        .join(EmployeeScheduledTask, EmployeeTaskRun.task_id == EmployeeScheduledTask.id)
        .where(EmployeeTaskRun.employee_id == employee_id)
        .order_by(EmployeeTaskRun.created_at.desc())
        .limit(min(limit, 200))
    )
    return [_task_run_response(run, task_name) for run, task_name in result.all()]


@router.get("/{employee_id}/runs/{run_id}", response_model=TaskRunResponse)
async def get_employee_run(
    employee_id: str,
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await require_employee_read(db, user, employee_id)
    run, task = await _get_run_with_task(db, employee_id, run_id)
    return _task_run_response(run, task.name if task else None)


@router.get("/{employee_id}/runs/{run_id}/download")
async def download_employee_run(
    employee_id: str,
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    emp = await require_employee_read(db, user, employee_id)
    run, task = await _get_run_with_task(db, employee_id, run_id)
    markdown = _run_markdown(run, task, emp.name)
    filename = (run.output_data or {}).get("report_filename") or f"run_{run.id[:8]}.md"
    return PlainTextResponse(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{employee_id}/runs/{run_id}/save-to-knowledge")
async def save_employee_run_to_knowledge(
    employee_id: str,
    run_id: str,
    payload: SaveRunToKnowledgeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    emp = await require_employee_read(db, user, employee_id)
    scope = await resolve_data_scope(db, user)
    if not scope.can_write_employee(emp):
        raise HTTPException(status_code=403, detail="Forbidden")
    run, task = await _get_run_with_task(db, employee_id, run_id)
    try:
        kb, doc = await export_run_to_knowledge(
            db,
            run,
            task,
            emp.name,
            user.id,
            kb_id=payload.kb_id,
            kb_name=payload.kb_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    await db.commit()
    return {
        "knowledge_base_id": kb.id,
        "knowledge_base_name": kb.name,
        "document_id": doc.id,
        "filename": doc.filename,
    }


async def _get_run_with_task(
    db: AsyncSession,
    employee_id: str,
    run_id: str,
) -> tuple[EmployeeTaskRun, EmployeeScheduledTask | None]:
    run = await db.get(EmployeeTaskRun, run_id)
    if not run or run.employee_id != employee_id:
        raise HTTPException(status_code=404, detail="Run not found")
    task = await db.get(EmployeeScheduledTask, run.task_id)
    return run, task


async def _get_task(db: AsyncSession, employee_id: str, task_id: str) -> EmployeeScheduledTask:
    task = await db.get(EmployeeScheduledTask, task_id)
    if not task or task.employee_id != employee_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
