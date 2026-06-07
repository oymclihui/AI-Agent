"""Background polling scheduler for digital employee tasks."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, and_

from app.db.session import AsyncSessionLocal
from app.db.models import (
    DigitalEmployee,
    EmployeeScheduledTask,
    EmployeeStatus,
)

logger = structlog.get_logger(__name__)

POLL_INTERVAL_SECONDS = 30


class EmployeeScheduler:
    _instance: "EmployeeScheduler | None" = None
    _task: asyncio.Task | None = None
    _running = False
    _last_tick: datetime | None = None
    _last_error: str | None = None

    @classmethod
    def get_instance(cls) -> "EmployeeScheduler":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("employee_scheduler_started", interval=POLL_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("employee_scheduler_stopped")

    def status(self) -> dict:
        return {
            "running": self._running,
            "poll_interval_seconds": POLL_INTERVAL_SECONDS,
            "last_tick": self._last_tick.isoformat() if self._last_tick else None,
            "last_error": self._last_error,
        }

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._last_error = str(exc)
                logger.error("employee_scheduler_tick_error", error=str(exc))
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def tick(self) -> int:
        from app.core.employees.runner import run_scheduled_task

        self._last_tick = datetime.now(timezone.utc)
        self._last_error = None
        now = self._last_tick
        executed = 0

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EmployeeScheduledTask, DigitalEmployee)
                .join(DigitalEmployee, EmployeeScheduledTask.employee_id == DigitalEmployee.id)
                .where(
                    and_(
                        EmployeeScheduledTask.enabled == True,  # noqa: E712
                        DigitalEmployee.status == EmployeeStatus.active,
                        EmployeeScheduledTask.next_run_at.isnot(None),
                        EmployeeScheduledTask.next_run_at <= now,
                    )
                )
                .limit(10)
            )
            rows = result.all()

            for task, employee in rows:
                try:
                    await run_scheduled_task(session, task, employee, triggered_by="schedule")
                    executed += 1
                except Exception as exc:
                    logger.error(
                        "scheduled_task_run_failed",
                        task_id=task.id,
                        employee_id=employee.id,
                        error=str(exc),
                    )
            await session.commit()

        if executed:
            logger.info("employee_scheduler_executed", count=executed)
        return executed
