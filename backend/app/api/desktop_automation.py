from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_user
from app.core.auth.scoping import assert_mutable_by_user
from app.core.desktop import service as desktop_svc
from app.db.models import (
    DesktopDemo,
    DesktopDemoStatus,
    DesktopTask,
    DesktopTaskAction,
    ExecutionStatus,
    User,
)
from app.db.session import get_db
from app.schemas.desktop_automation import (
    DesktopCaptureRequest,
    DesktopDemoCreate,
    DesktopDemoResponse,
    DesktopDemoUpdate,
    DesktopReplayRequest,
    DesktopTaskResponse,
    SidecarPollResponse,
    SidecarRegisterRequest,
    SidecarRegisterResponse,
    SidecarStatusResponse,
    SidecarTaskCompleteRequest,
    DemoDepositRequest,
    DemoDepositResponse,
)

router = APIRouter(prefix="/desktop-automation", tags=["Desktop Automation"])


def _demo_response(demo: DesktopDemo) -> DesktopDemoResponse:
    return DesktopDemoResponse(
        id=demo.id,
        name=demo.name,
        description=demo.description,
        app_name=demo.app_name,
        tags=demo.tags or [],
        status=demo.status,
        step_count=demo.step_count or 0,
        metadata_=demo.metadata_ or {},
        created_at=demo.created_at,
        updated_at=demo.updated_at,
    )


def _task_response(task: DesktopTask, demo_name: str | None = None) -> DesktopTaskResponse:
    return DesktopTaskResponse(
        id=task.id,
        demo_id=task.demo_id,
        demo_name=demo_name,
        action=task.action,
        status=task.status,
        instructions=task.instructions,
        input_data=task.input_data or {},
        output_data=task.output_data,
        error_message=task.error_message,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
    )


@router.get("/demos", response_model=list[DesktopDemoResponse])
async def list_demos(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    demos = await desktop_svc.list_demos(db, user.id)
    return [_demo_response(d) for d in demos]


@router.post("/demos", response_model=DesktopDemoResponse, status_code=status.HTTP_201_CREATED)
async def create_demo(
    payload: DesktopDemoCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    demo = await desktop_svc.create_demo(
        db,
        user.id,
        name=payload.name,
        description=payload.description,
        app_name=payload.app_name,
        tags=payload.tags,
        status=DesktopDemoStatus.ready,
    )
    await db.commit()
    await db.refresh(demo)
    return _demo_response(demo)


@router.patch("/demos/{demo_id}", response_model=DesktopDemoResponse)
async def update_demo(
    demo_id: str,
    payload: DesktopDemoUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    demo = await desktop_svc.get_demo(db, demo_id, user.id)
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found")
    assert_mutable_by_user(demo, user.id)

    if payload.name is not None:
        demo.name = payload.name.strip()
    if payload.description is not None:
        demo.description = payload.description
    if payload.app_name is not None:
        demo.app_name = payload.app_name
    if payload.tags is not None:
        demo.tags = payload.tags
    if payload.status is not None:
        demo.status = payload.status

    await db.commit()
    await db.refresh(demo)
    return _demo_response(demo)


@router.delete("/demos/{demo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_demo(
    demo_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    demo = await desktop_svc.get_demo(db, demo_id, user.id)
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found")
    assert_mutable_by_user(demo, user.id)
    await db.delete(demo)
    await db.commit()


@router.get("/tasks", response_model=list[DesktopTaskResponse])
async def list_tasks(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = await desktop_svc.list_tasks(db, user.id)
    return [_task_response(task, demo_name) for task, demo_name in rows]


@router.post("/tasks/replay", response_model=DesktopTaskResponse)
async def replay_demo(
    payload: DesktopReplayRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    demo = None
    if payload.demo_id:
        demo = await desktop_svc.get_demo(db, payload.demo_id, user.id)
    elif payload.demo_name:
        demo = await desktop_svc.find_demo_by_name(db, payload.demo_name, user.id)
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found")

    sidecar = await desktop_svc.get_primary_sidecar(db, user.id)
    if not desktop_svc.sidecar_is_online(sidecar):
        raise HTTPException(
            status_code=503,
            detail="Desktop sidecar offline. Start scripts/desktop_sidecar.py on this PC.",
        )

    task = await desktop_svc.enqueue_task(
        db,
        user.id,
        action=DesktopTaskAction.replay,
        demo_id=demo.id,
        instructions=payload.instructions,
        input_data={"demo_name": demo.name},
        sidecar_id=sidecar.id if sidecar else None,
        confirmed=payload.confirmed,
    )
    await db.commit()
    await db.refresh(task)
    return _task_response(task, demo.name)


@router.post("/tasks/capture/start", response_model=DesktopTaskResponse)
async def start_capture(
    payload: DesktopCaptureRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sidecar = await desktop_svc.get_primary_sidecar(db, user.id)
    if not desktop_svc.sidecar_is_online(sidecar):
        raise HTTPException(status_code=503, detail="Desktop sidecar offline")

    task = await desktop_svc.enqueue_task(
        db,
        user.id,
        action=DesktopTaskAction.capture_start,
        input_data={
            "demo_name": payload.demo_name,
            "app_name": payload.app_name,
            "description": payload.description,
        },
        sidecar_id=sidecar.id if sidecar else None,
    )
    await db.commit()
    await db.refresh(task)
    return _task_response(task)


@router.post("/tasks/capture/stop", response_model=DesktopTaskResponse)
async def stop_capture(
    payload: DesktopCaptureRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.demo_name or not payload.demo_name.strip():
        raise HTTPException(status_code=400, detail="demo_name is required")

    sidecar = await desktop_svc.get_primary_sidecar(db, user.id)
    if not desktop_svc.sidecar_is_online(sidecar):
        raise HTTPException(status_code=503, detail="Desktop sidecar offline")

    task = await desktop_svc.enqueue_task(
        db,
        user.id,
        action=DesktopTaskAction.capture_stop,
        input_data={
            "demo_name": payload.demo_name.strip(),
            "app_name": payload.app_name,
            "description": payload.description,
        },
        sidecar_id=sidecar.id if sidecar else None,
    )
    await db.commit()
    await db.refresh(task)
    return _task_response(task)


@router.get("/sidecar/status", response_model=SidecarStatusResponse)
async def sidecar_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sidecar = await desktop_svc.get_primary_sidecar(db, user.id)
    if not sidecar:
        return SidecarStatusResponse(online=False)
    return SidecarStatusResponse(
        online=desktop_svc.sidecar_is_online(sidecar),
        device_id=sidecar.device_id,
        device_name=sidecar.device_name,
        hostname=sidecar.hostname,
        platform=sidecar.platform,
        last_seen_at=sidecar.last_seen_at,
    )


@router.post("/sidecar/register", response_model=SidecarRegisterResponse)
async def register_sidecar(
    payload: SidecarRegisterRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sidecar = await desktop_svc.register_sidecar(
        db,
        user.id,
        device_id=payload.device_id,
        device_name=payload.device_name,
        hostname=payload.hostname,
        platform=payload.platform,
    )
    await db.commit()
    await db.refresh(sidecar)
    return SidecarRegisterResponse(
        id=sidecar.id,
        device_id=sidecar.device_id,
        device_name=sidecar.device_name,
        hostname=sidecar.hostname,
        platform=sidecar.platform,
        online=True,
    )


@router.get("/sidecar/poll", response_model=SidecarPollResponse)
async def sidecar_poll(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    tasks = await desktop_svc.poll_pending_tasks(db, user.id, device_id)
    await db.commit()
    demo_names: dict[str, str | None] = {}
    for task in tasks:
        if task.demo_id and task.demo_id not in demo_names:
            demo = await db.get(DesktopDemo, task.demo_id)
            demo_names[task.demo_id] = demo.name if demo else None
    return SidecarPollResponse(
        tasks=[_task_response(t, demo_names.get(t.demo_id or "")) for t in tasks]
    )


@router.post("/sidecar/tasks/{task_id}/complete", response_model=DesktopTaskResponse)
async def sidecar_complete_task(
    task_id: str,
    payload: SidecarTaskCompleteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.status not in (ExecutionStatus.completed, ExecutionStatus.failed, ExecutionStatus.cancelled):
        raise HTTPException(status_code=400, detail="Invalid completion status")

    task = await desktop_svc.complete_task(
        db,
        user.id,
        task_id,
        status=payload.status,
        output_data=payload.output_data,
        error_message=payload.error_message,
        demo_name=payload.demo_name,
        app_name=payload.app_name,
        description=payload.description,
        step_count=payload.step_count,
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    demo_name = None
    if task.demo_id:
        demo = await db.get(DesktopDemo, task.demo_id)
        demo_name = demo.name if demo else None

    await db.commit()
    await db.refresh(task)
    return _task_response(task, demo_name)


@router.post("/demos/{demo_id}/deposit", response_model=DemoDepositResponse)
async def deposit_demo(
    demo_id: str,
    payload: DemoDepositRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    demo = await desktop_svc.get_demo(db, demo_id, user.id)
    if not demo:
        raise HTTPException(status_code=404, detail="Demo not found")
    assert_mutable_by_user(demo, user.id)

    from app.core.desktop.export import export_demo_to_skill, export_demo_to_knowledge

    if payload.target == "skill":
        skill = await export_demo_to_skill(db, demo, user.id, use_llm=payload.use_llm)
        await db.commit()
        return DemoDepositResponse(target="skill", skill_id=skill.id, skill_slug=skill.slug)

    kb, doc = await export_demo_to_knowledge(
        db,
        demo,
        user.id,
        kb_id=payload.kb_id,
        kb_name=payload.kb_name,
        use_llm=payload.use_llm,
    )
    await db.commit()
    return DemoDepositResponse(
        target="knowledge",
        kb_id=kb.id,
        document_id=doc.id,
    )


@router.get("/tasks/awaiting-confirmation", response_model=list[DesktopTaskResponse])
async def list_awaiting_confirmation(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = await desktop_svc.list_awaiting_confirmation(db, user.id)
    return [_task_response(task, demo_name) for task, demo_name in rows]


@router.post("/tasks/{task_id}/confirm", response_model=DesktopTaskResponse)
async def confirm_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = await desktop_svc.confirm_task(db, user.id, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    demo_name = None
    if task.demo_id:
        demo = await db.get(DesktopDemo, task.demo_id)
        demo_name = demo.name if demo else None
    await db.commit()
    await db.refresh(task)
    return _task_response(task, demo_name)


@router.post("/tasks/{task_id}/reject", response_model=DesktopTaskResponse)
async def reject_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = await desktop_svc.reject_task(db, user.id, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    demo_name = None
    if task.demo_id:
        demo = await db.get(DesktopDemo, task.demo_id)
        demo_name = demo.name if demo else None
    await db.commit()
    await db.refresh(task)
    return _task_response(task, demo_name)
