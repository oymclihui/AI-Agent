"""Desktop automation task queue and demo library."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import generate_uuid
from app.db.models import (
    DesktopDemo,
    DesktopDemoStatus,
    DesktopSidecar,
    DesktopTask,
    DesktopTaskAction,
    ExecutionStatus,
)
from app.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)

SIDECAR_ONLINE_SECONDS = 30
TASK_POLL_INTERVAL = 2.0
DEFAULT_TASK_TIMEOUT = 120.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sidecar_is_online(sidecar: DesktopSidecar | None) -> bool:
    if not sidecar or not sidecar.last_seen_at:
        return False
    seen = sidecar.last_seen_at
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return (_utcnow() - seen).total_seconds() <= SIDECAR_ONLINE_SECONDS


def demo_to_dict(demo: DesktopDemo) -> dict[str, Any]:
    return {
        "id": demo.id,
        "name": demo.name,
        "description": demo.description,
        "app_name": demo.app_name,
        "tags": demo.tags or [],
        "status": demo.status.value if hasattr(demo.status, "value") else demo.status,
        "step_count": demo.step_count or 0,
        "metadata_": demo.metadata_ or {},
        "created_at": demo.created_at,
        "updated_at": demo.updated_at,
    }


def task_to_dict(task: DesktopTask, demo_name: str | None = None) -> dict[str, Any]:
    return {
        "id": task.id,
        "demo_id": task.demo_id,
        "demo_name": demo_name,
        "action": task.action.value if hasattr(task.action, "value") else task.action,
        "status": task.status.value if hasattr(task.status, "value") else task.status,
        "instructions": task.instructions,
        "input_data": task.input_data or {},
        "output_data": task.output_data,
        "error_message": task.error_message,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "completed_at": task.completed_at,
    }


async def list_demos(db: AsyncSession, user_id: str) -> list[DesktopDemo]:
    result = await db.execute(
        select(DesktopDemo)
        .where(or_(DesktopDemo.owner_id == user_id, DesktopDemo.owner_id.is_(None)))
        .order_by(DesktopDemo.created_at.desc())
    )
    return list(result.scalars().all())


async def get_demo(db: AsyncSession, demo_id: str, user_id: str) -> DesktopDemo | None:
    result = await db.execute(
        select(DesktopDemo).where(
            DesktopDemo.id == demo_id,
            or_(DesktopDemo.owner_id == user_id, DesktopDemo.owner_id.is_(None)),
        )
    )
    return result.scalar_one_or_none()


async def find_demo_by_name(db: AsyncSession, name: str, user_id: str) -> DesktopDemo | None:
    result = await db.execute(
        select(DesktopDemo).where(
            DesktopDemo.name == name.strip(),
            or_(DesktopDemo.owner_id == user_id, DesktopDemo.owner_id.is_(None)),
        )
    )
    return result.scalar_one_or_none()


async def create_demo(
    db: AsyncSession,
    user_id: str,
    *,
    name: str,
    description: str | None = None,
    app_name: str | None = None,
    tags: list[str] | None = None,
    status: DesktopDemoStatus = DesktopDemoStatus.draft,
    step_count: int = 0,
    metadata: dict | None = None,
) -> DesktopDemo:
    demo = DesktopDemo(
        id=generate_uuid(),
        owner_id=user_id,
        name=name.strip(),
        description=description,
        app_name=app_name,
        tags=tags or [],
        status=status,
        step_count=step_count,
        metadata_=metadata or {},
    )
    db.add(demo)
    await db.flush()
    return demo


async def get_primary_sidecar(db: AsyncSession, user_id: str) -> DesktopSidecar | None:
    result = await db.execute(
        select(DesktopSidecar)
        .where(DesktopSidecar.owner_id == user_id)
        .order_by(DesktopSidecar.last_seen_at.desc().nullslast())
    )
    sidecars = list(result.scalars().all())
    for sc in sidecars:
        if sidecar_is_online(sc):
            return sc
    return sidecars[0] if sidecars else None


async def register_sidecar(
    db: AsyncSession,
    user_id: str,
    *,
    device_name: str,
    device_id: str | None = None,
    hostname: str | None = None,
    platform: str | None = None,
) -> DesktopSidecar:
    device_id = (device_id or generate_uuid()).strip()
    result = await db.execute(
        select(DesktopSidecar).where(
            DesktopSidecar.owner_id == user_id,
            DesktopSidecar.device_id == device_id,
        )
    )
    sidecar = result.scalar_one_or_none()
    if sidecar:
        sidecar.device_name = device_name
        sidecar.hostname = hostname
        sidecar.platform = platform
        sidecar.last_seen_at = _utcnow()
    else:
        sidecar = DesktopSidecar(
            id=generate_uuid(),
            owner_id=user_id,
            device_id=device_id,
            device_name=device_name,
            hostname=hostname,
            platform=platform,
            last_seen_at=_utcnow(),
        )
        db.add(sidecar)
    await db.flush()
    return sidecar


async def touch_sidecar(db: AsyncSession, sidecar: DesktopSidecar) -> None:
    sidecar.last_seen_at = _utcnow()
    await db.flush()


def _initial_task_status(
    action: DesktopTaskAction,
    *,
    require_confirmation: bool | None = None,
    confirmed: bool = False,
) -> ExecutionStatus:
    from app.config import settings

    if confirmed:
        return ExecutionStatus.pending
    needs = (
        require_confirmation
        if require_confirmation is not None
        else settings.DESKTOP_REQUIRE_CONFIRMATION
    )
    if needs and action == DesktopTaskAction.replay:
        return ExecutionStatus.awaiting_confirmation
    return ExecutionStatus.pending


async def enqueue_task(
    db: AsyncSession,
    user_id: str,
    *,
    action: DesktopTaskAction,
    demo_id: str | None = None,
    instructions: str | None = None,
    input_data: dict | None = None,
    sidecar_id: str | None = None,
    require_confirmation: bool | None = None,
    confirmed: bool = False,
) -> DesktopTask:
    status = _initial_task_status(
        action,
        require_confirmation=require_confirmation,
        confirmed=confirmed,
    )
    task = DesktopTask(
        id=generate_uuid(),
        owner_id=user_id,
        demo_id=demo_id,
        sidecar_id=sidecar_id,
        action=action,
        status=status,
        instructions=instructions,
        input_data=input_data or {},
    )
    db.add(task)
    await db.flush()
    logger.info(
        "desktop_task_enqueued",
        task_id=task.id,
        action=action.value,
        status=status.value,
        user_id=user_id[:8],
    )
    return task


async def list_awaiting_confirmation(
    db: AsyncSession, user_id: str, limit: int = 20
) -> list[tuple[DesktopTask, str | None]]:
    result = await db.execute(
        select(DesktopTask, DesktopDemo.name)
        .outerjoin(DesktopDemo, DesktopTask.demo_id == DesktopDemo.id)
        .where(
            DesktopTask.owner_id == user_id,
            DesktopTask.status == ExecutionStatus.awaiting_confirmation,
        )
        .order_by(DesktopTask.created_at.desc())
        .limit(limit)
    )
    return [(row[0], row[1]) for row in result.all()]


async def confirm_task(db: AsyncSession, user_id: str, task_id: str) -> DesktopTask | None:
    task = await db.get(DesktopTask, task_id)
    if not task or task.owner_id != user_id:
        return None
    if task.status != ExecutionStatus.awaiting_confirmation:
        return task
    task.status = ExecutionStatus.pending
    await db.flush()
    return task


async def reject_task(db: AsyncSession, user_id: str, task_id: str) -> DesktopTask | None:
    task = await db.get(DesktopTask, task_id)
    if not task or task.owner_id != user_id:
        return None
    if task.status != ExecutionStatus.awaiting_confirmation:
        return task
    task.status = ExecutionStatus.cancelled
    task.completed_at = _utcnow()
    task.error_message = "Rejected by user"
    await db.flush()
    return task


async def list_tasks(db: AsyncSession, user_id: str, limit: int = 50) -> list[tuple[DesktopTask, str | None]]:
    result = await db.execute(
        select(DesktopTask, DesktopDemo.name)
        .outerjoin(DesktopDemo, DesktopTask.demo_id == DesktopDemo.id)
        .where(DesktopTask.owner_id == user_id)
        .order_by(DesktopTask.created_at.desc())
        .limit(limit)
    )
    return [(row[0], row[1]) for row in result.all()]


async def poll_pending_tasks(db: AsyncSession, user_id: str, device_id: str) -> list[DesktopTask]:
    sidecar_result = await db.execute(
        select(DesktopSidecar).where(
            DesktopSidecar.owner_id == user_id,
            DesktopSidecar.device_id == device_id,
        )
    )
    sidecar = sidecar_result.scalar_one_or_none()
    if not sidecar:
        return []

    await touch_sidecar(db, sidecar)

    result = await db.execute(
        select(DesktopTask)
        .where(
            DesktopTask.owner_id == user_id,
            DesktopTask.status == ExecutionStatus.pending,
        )
        .order_by(DesktopTask.created_at.asc())
        .limit(5)
    )
    tasks = list(result.scalars().all())
    for task in tasks:
        task.status = ExecutionStatus.running
        task.sidecar_id = sidecar.id
    await db.flush()
    return tasks


async def complete_task(
    db: AsyncSession,
    user_id: str,
    task_id: str,
    *,
    status: ExecutionStatus,
    output_data: dict | None = None,
    error_message: str | None = None,
    demo_name: str | None = None,
    app_name: str | None = None,
    description: str | None = None,
    step_count: int | None = None,
) -> DesktopTask | None:
    task = await db.get(DesktopTask, task_id)
    if not task or task.owner_id != user_id:
        return None

    task.status = status
    task.output_data = output_data or {}
    task.error_message = error_message
    task.completed_at = _utcnow()

    if status == ExecutionStatus.completed and task.action == DesktopTaskAction.capture_stop:
        name = (demo_name or task.input_data.get("demo_name") or "未命名演示").strip()
        demo = await create_demo(
            db,
            user_id,
            name=name,
            description=description or task.input_data.get("description"),
            app_name=app_name or task.input_data.get("app_name"),
            status=DesktopDemoStatus.ready,
            step_count=step_count or 0,
            metadata={
                "source": "capture",
                "task_id": task.id,
                "steps": (output_data or task.output_data or {}).get("steps") or [],
                "mode": (output_data or task.output_data or {}).get("mode"),
            },
        )
        task.demo_id = demo.id
        task.output_data = {**(task.output_data or {}), "demo_id": demo.id, "demo_name": demo.name}

    await db.flush()
    return task


async def wait_for_task(task_id: str, user_id: str, timeout_s: float = DEFAULT_TASK_TIMEOUT) -> DesktopTask | None:
    import time
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        async with AsyncSessionLocal() as db:
            task = await db.get(DesktopTask, task_id)
            if not task or task.owner_id != user_id:
                return task
            if task.status in (
                ExecutionStatus.completed,
                ExecutionStatus.failed,
                ExecutionStatus.cancelled,
            ):
                return task
        await asyncio.sleep(TASK_POLL_INTERVAL)
    return None


async def replay_demo_for_user(
    user_id: str,
    *,
    demo_id: str | None = None,
    demo_name: str | None = None,
    instructions: str | None = None,
    wait: bool = True,
    timeout_s: float = DEFAULT_TASK_TIMEOUT,
    confirmed: bool = False,
    require_confirmation: bool | None = None,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        demo: DesktopDemo | None = None
        if demo_id:
            demo = await get_demo(db, demo_id, user_id)
        elif demo_name:
            demo = await find_demo_by_name(db, demo_name.strip(), user_id)
        if not demo:
            return {"ok": False, "error": "演示未找到，请先在桌面自动化页面创建或录制演示。"}

        sidecar = await get_primary_sidecar(db, user_id)
        if not sidecar_is_online(sidecar):
            return {
                "ok": False,
                "error": "本机 Sidecar 未在线。请运行 scripts/desktop_sidecar.py 并保持登录同一账号。",
            }

        task = await enqueue_task(
            db,
            user_id,
            action=DesktopTaskAction.replay,
            demo_id=demo.id,
            instructions=instructions,
            input_data={"demo_name": demo.name},
            sidecar_id=sidecar.id if sidecar else None,
            confirmed=confirmed,
            require_confirmation=require_confirmation,
        )
        saved_demo_name = demo.name
        task_status = task.status
        await db.commit()
        task_id = task.id

    if task_status == ExecutionStatus.awaiting_confirmation:
        return {
            "ok": True,
            "needs_confirmation": True,
            "task_id": task_id,
            "demo_name": saved_demo_name,
            "message": (
                f"回放任务「{saved_demo_name}」已创建，等待人工确认。"
                "请在「桌面自动化」页面或对话确认栏中批准后再执行。"
            ),
        }

    if not wait:
        return {"ok": True, "task_id": task_id, "message": f"已下发回放任务：{saved_demo_name}"}

    finished = await wait_for_task(task_id, user_id, timeout_s=timeout_s)
    if not finished:
        return {"ok": False, "error": "回放任务超时，请在桌面自动化页面查看任务状态。"}
    if finished.status == ExecutionStatus.completed:
        return {
            "ok": True,
            "task_id": task_id,
            "demo_name": saved_demo_name,
            "message": (finished.output_data or {}).get("message", f"演示「{saved_demo_name}」回放完成。"),
            "output": finished.output_data,
        }
    return {
        "ok": False,
        "task_id": task_id,
        "error": finished.error_message or "回放失败",
    }


async def list_demos_text(user_id: str) -> str:
    async with AsyncSessionLocal() as db:
        demos = await list_demos(db, user_id)
    if not demos:
        return "当前没有可用的桌面演示。请在本机 Sidecar 中录制，或在「桌面自动化」页面手动创建演示。"
    lines = [f"共 {len(demos)} 个桌面演示：", ""]
    for d in demos:
        status = d.status.value if hasattr(d.status, "value") else d.status
        app = f" · {d.app_name}" if d.app_name else ""
        lines.append(f"- {d.name} [{status}]{app}")
        if d.description:
            lines.append(f"  {d.description[:200]}")
    return "\n".join(lines)
