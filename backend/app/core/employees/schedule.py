"""Cron / interval next-run helpers for digital employee tasks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import structlog

logger = structlog.get_logger(__name__)


def _resolve_tz(tz_name: str | None) -> ZoneInfo:
    name = (tz_name or "UTC").strip()
    try:
        return ZoneInfo(name)
    except Exception:
        logger.warning("invalid_timezone", tz=name)
        return ZoneInfo("UTC")


def compute_next_run(
    schedule_type: str,
    *,
    cron_expression: str | None = None,
    interval_seconds: int | None = None,
    timezone_name: str = "Asia/Shanghai",
    from_dt: datetime | None = None,
) -> datetime:
    """Return next run time as UTC-aware datetime."""
    tz = _resolve_tz(timezone_name)
    base_local = from_dt or datetime.now(tz)
    if base_local.tzinfo is None:
        base_local = base_local.replace(tzinfo=tz)
    else:
        base_local = base_local.astimezone(tz)

    if schedule_type == "interval":
        seconds = interval_seconds or 3600
        nxt = base_local + timedelta(seconds=seconds)
        return nxt.astimezone(timezone.utc)

    if not cron_expression:
        raise ValueError("cron_expression is required for cron schedule")

    try:
        from croniter import croniter
    except ImportError as exc:
        raise RuntimeError("croniter is required for cron schedules") from exc

    itr = croniter(cron_expression, base_local)
    nxt_local = itr.get_next(datetime)
    if nxt_local.tzinfo is None:
        nxt_local = nxt_local.replace(tzinfo=tz)
    return nxt_local.astimezone(timezone.utc)


def validate_schedule(
    schedule_type: str,
    cron_expression: str | None,
    interval_seconds: int | None,
) -> None:
    if schedule_type == "interval":
        if not interval_seconds or interval_seconds < 60:
            raise ValueError("interval_seconds must be at least 60")
        return
    if schedule_type == "cron":
        if not cron_expression or not cron_expression.strip():
            raise ValueError("cron_expression is required")
        try:
            from croniter import croniter
            croniter(cron_expression)
        except Exception as exc:
            raise ValueError(f"Invalid cron expression: {exc}") from exc
        return
    raise ValueError(f"Unsupported schedule_type: {schedule_type}")
