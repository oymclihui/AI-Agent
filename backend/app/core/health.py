"""组件健康板（蓝图阶段四）：每个组件认领一个健康条目，/状态 命令与管理台同源。

条目口径：
- db        主库 SELECT 1
- redis     ping + celery 队列积压深度
- wecom     企微长连接状态（connected 才算 ok）
- outbox    三连败未投递数 + 派遣循环存活
- proactive 主动工作引擎存活（辅助组件，挂了只记 degraded）

整体：全部 ok → ok；有 down → down；否则有 degraded → degraded。
"""
from __future__ import annotations

import datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_CELERY_QUEUE_WARN = 100


def _item(status: str, detail: str = "") -> dict[str, str]:
    return {
        "status": status,
        "detail": detail,
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


async def _check_db(db: AsyncSession) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
        return _item("ok")
    except Exception as exc:
        return _item("down", str(exc)[:120])


async def _check_redis() -> dict[str, str]:
    try:
        from app.core.cache.redis_cache import _get_client

        cli = await _get_client()
        if cli is None:
            return _item("down", "连接不可用（熔断中或初始化失败）")
        await cli.ping()
        try:
            depth = int(await cli.llen("celery") or 0)
        except Exception:
            depth = -1
        if depth > _CELERY_QUEUE_WARN:
            return _item("degraded", f"celery 队列积压 {depth}")
        return _item("ok", f"celery 队列 {depth}" if depth >= 0 else "")
    except Exception as exc:
        return _item("down", str(exc)[:120])


def _check_wecom() -> dict[str, str]:
    try:
        from app.core.wecom.listener import wecom_link

        status = str(getattr(wecom_link, "status", "unknown") or "unknown")
        if status == "connected":
            return _item("ok")
        if status in ("connecting", "reconnecting"):
            return _item("degraded", status)
        return _item("down", status)
    except Exception as exc:
        return _item("down", str(exc)[:120])


async def _check_outbox() -> dict[str, str]:
    try:
        from app.core.tasks import outbox as _ob

        running = bool(_ob._dispatcher and not _ob._dispatcher.done())
        if not running:
            return _item("down", "派遣循环未运行")
        failed = await _ob.failed_count()
        if failed > 0:
            return _item("degraded", f"{failed} 条三连败未投递")
        return _item("ok")
    except Exception as exc:
        return _item("down", str(exc)[:120])


def _check_proactive() -> dict[str, str]:
    try:
        from app.core.proactive import engine as _pe

        running = bool(_pe._engine_task and not _pe._engine_task.done())
        return _item("ok") if running else _item("degraded", "引擎未运行")
    except Exception as exc:
        return _item("degraded", str(exc)[:120])


async def collect_health(db: AsyncSession) -> dict[str, Any]:
    """汇总全部组件健康条目（/状态 命令与管理台都读这一份）。"""
    items = {
        "db": await _check_db(db),
        "redis": await _check_redis(),
        "wecom": _check_wecom(),
        "outbox": await _check_outbox(),
        "proactive": _check_proactive(),
    }
    statuses = [i["status"] for i in items.values()]
    overall = "down" if "down" in statuses else ("degraded" if "degraded" in statuses else "ok")
    return {"overall": overall, "items": items}


_LABELS = {"db": "数据库", "redis": "Redis", "wecom": "企微连接", "outbox": "发件箱", "proactive": "主动引擎"}
_STATUS_CN = {"ok": "正常", "degraded": "降级", "down": "异常"}


def format_health_lines(health: dict[str, Any]) -> list[str]:
    """企微 /状态 用的纯文本行（与管理台读同一份数据）。"""
    lines: list[str] = []
    for key, item in (health.get("items") or {}).items():
        label = _LABELS.get(key, key)
        status = _STATUS_CN.get(item.get("status") or "", item.get("status") or "?")
        detail = str(item.get("detail") or "")
        lines.append(f"· {label}：{status}{('（' + detail + '）') if detail else ''}")
    return lines
