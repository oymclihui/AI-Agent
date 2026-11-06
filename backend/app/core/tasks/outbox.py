"""事务性发件箱（蓝图阶段二）：外发消息先落库、有序发送、失败退避、重启补发。

用法：
- send_now(...)：写穿式——先落库（pending）再立即尝试发送；失败留待派遣循环重试。
- start_outbox_dispatcher() / stop_outbox_dispatcher()：应用起停时调用。
- 派遣循环每 5s 扫描到期 pending 行，按创建顺序发送（同任务天然保序）。
"""
from __future__ import annotations

import asyncio
import datetime
from typing import Any

import structlog
from sqlalchemy import or_, select

from app.db.models import OutboxMessage
from app.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)

PENDING = "pending"
SENT = "sent"
FAILED = "failed"
DROPPED = "dropped"

# 指数退避：第 1/2/3 次失败后的等待秒数；三次连败置 failed 并告警
_BACKOFF = (5, 30, 300)
_MAX_ATTEMPTS = 3
_SWEEP_INTERVAL = 5.0
_SWEEP_BATCH = 20
_CONTENT_CLIP = 3800  # 企微消息长度兜底截断

_dispatcher: asyncio.Task | None = None
_wake: asyncio.Event | None = None


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


async def enqueue(
    *,
    target: list[str],
    content: str,
    task_id: str | None = None,
    channel: str = "wecom",
    kind: str = "markdown",
) -> str:
    """落库一条外发消息（pending），返回 outbox id；落库失败返回空串。"""
    try:
        async with AsyncSessionLocal() as db:
            row = OutboxMessage(
                task_id=task_id or None,
                channel=channel,
                target=list(target or []),
                kind=kind,
                payload={"content": (content or "")[:_CONTENT_CLIP]},
                status=PENDING,
            )
            db.add(row)
            await db.commit()
            outbox_id = str(row.id)
        if _wake is not None:
            _wake.set()
        return outbox_id
    except Exception as exc:
        logger.warning("outbox_enqueue_failed", error=str(exc)[:200])
        return ""


async def _deliver(channel: str, target: list[str], content: str) -> None:
    """按渠道路由发送；失败抛异常由上层记退避。

    target：wecom 时是 [chatid/userid]（wecom_link 内部路由）；
            dingtalk 时是 [session_webhook 或 None]，实际发 DINGTALK_ROBOT_WEBHOOK。
    """
    if channel == "wecom":
        from app.core.wecom.listener import wecom_link

        if getattr(wecom_link, "status", "") != "connected":
            raise RuntimeError("企业微信长连接未建立")
        result = await wecom_link.send_markdown(target, content)
        if not result.get("ok"):
            errors = ";".join(e.get("error", "") for e in (result.get("errors") or []))
            raise RuntimeError(errors[:200] or "发送失败")
        return

    if channel == "dingtalk":
        # 钉钉没有长连接，统一用群机器人 webhook 异步推（sessionWebhook 一次性）
        from app.integrations.dingtalk import send_dingtalk_text

        await send_dingtalk_text(None, content)  # None = settings.DINGTALK_ROBOT_WEBHOOK
        return

    raise RuntimeError(f"unsupported channel: {channel}")


async def _send_row(row: OutboxMessage) -> None:
    """发送一行并就地更新状态（调用方持会话负责 commit）。"""
    content = str((row.payload or {}).get("content") or "")
    try:
        await _deliver(row.channel, list(row.target or []), content)
    except Exception as exc:
        row.attempts = int(row.attempts or 0) + 1
        row.error = str(exc)[:500]
        if row.attempts >= _MAX_ATTEMPTS:
            row.status = FAILED
            logger.warning(
                "outbox_message_failed",
                outbox_id=row.id,
                task_id=row.task_id,
                attempts=row.attempts,
                error=row.error,
            )
        else:
            delay = _BACKOFF[min(row.attempts - 1, len(_BACKOFF) - 1)]
            row.next_retry_at = _utcnow() + datetime.timedelta(seconds=delay)
        return
    row.status = SENT
    row.sent_at = _utcnow()
    row.error = None
    logger.info("outbox_message_sent", outbox_id=row.id, task_id=row.task_id)


async def send_now(
    *,
    target: list[str],
    content: str,
    task_id: str | None = None,
    channel: str = "wecom",
    kind: str = "markdown",
) -> bool:
    """写穿式发送：先落库再立即尝试；成功 True，失败 False（行留 pending 由派遣循环补发）。"""
    outbox_id = await enqueue(
        target=target, content=content, task_id=task_id, channel=channel, kind=kind
    )
    if not outbox_id:
        return False
    try:
        async with AsyncSessionLocal() as db:
            row = await db.get(OutboxMessage, outbox_id)
            if row is None:
                return False
            await _send_row(row)
            await db.commit()
            return row.status == SENT
    except Exception as exc:
        logger.warning("outbox_send_now_failed", outbox_id=outbox_id, error=str(exc)[:200])
        return False


async def sweep_pending(limit: int = _SWEEP_BATCH) -> int:
    """发送一批到期的 pending 行（启动恢复与循环共用），返回处理条数。"""
    now = _utcnow()
    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(OutboxMessage)
                    .where(OutboxMessage.status == PENDING)
                    .where(
                        or_(
                            OutboxMessage.next_retry_at.is_(None),
                            OutboxMessage.next_retry_at <= now,
                        )
                    )
                    .order_by(OutboxMessage.created_at)
                    .limit(limit)
                )
            ).scalars().all()
            for row in rows:
                await _send_row(row)
            await db.commit()
            return len(rows)
    except Exception as exc:
        logger.warning("outbox_sweep_failed", error=str(exc)[:200])
        return 0


async def _loop() -> None:
    global _wake
    _wake = asyncio.Event()
    while True:
        try:
            await sweep_pending()
        except Exception:
            pass
        try:
            await asyncio.wait_for(_wake.wait(), timeout=_SWEEP_INTERVAL)
            _wake.clear()
        except asyncio.TimeoutError:
            pass


def start_outbox_dispatcher() -> None:
    """启动派遣循环（幂等）。重启后第一批 pending 会在循环首个节拍补发。"""
    global _dispatcher
    if _dispatcher and not _dispatcher.done():
        return
    _dispatcher = asyncio.create_task(_loop(), name="outbox-dispatcher")
    logger.info("outbox_dispatcher_started")


async def stop_outbox_dispatcher() -> None:
    global _dispatcher
    if _dispatcher:
        _dispatcher.cancel()
        try:
            await _dispatcher
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        _dispatcher = None


async def failed_count(channel: str = "wecom") -> int:
    """三连败未投递条数（待人工面板/告警用）。"""
    from sqlalchemy import func

    try:
        async with AsyncSessionLocal() as db:
            return int(
                (
                    await db.execute(
                        select(func.count())
                        .select_from(OutboxMessage)
                        .where(OutboxMessage.status == FAILED, OutboxMessage.channel == channel)
                    )
                ).scalar()
                or 0
            )
    except Exception:
        return 0
