"""跨渠道任务：状态机 + 持久化 + 重启恢复（对标 super-agent 蓝图阶段一）。

状态机：queued → working → person/answer（待澄清）
                          → person/review（待确认）→ done；异常 → failed。

消息纪律（企微）：一个任务周期最多三条可见消息——确认一次（ack）、
需决策一个问题（澄清候选卡片）、结果一次（答案 + 反馈卡片），工作过程零打扰。
"""
from __future__ import annotations

import datetime
from typing import Any, Awaitable, Callable

import structlog
from sqlalchemy import select

from app.db.models import TaskRecord
from app.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)

QUEUED = "queued"
WORKING = "working"
WAITING_ANSWER = "person/answer"  # 待澄清：等用户点候选
WAITING_REVIEW = "person/review"  # 待确认：等用户点反馈
DONE = "done"
FAILED = "failed"

_INFLIGHT = (QUEUED, WORKING)

# 任务查询在 LLM/库层可能跑较久；这里只是兜底，不做硬超时（沿用现有链路行为）


async def create_task(
    *,
    user_id: str,
    question: str,
    channel: str = "wecom",
    chattype: str = "",
    target: list[str] | None = None,
    ack_text: str = "",
    mandate: dict[str, Any] | None = None,
) -> str:
    """登记新任务（queued），返回 task_id。失败不阻断主流程，返回空串。

    mandate：准入依据（蓝图阶段三）——{basis, policy_version, scope, decided_at}，
    写入 report.mandate，后续 finish_task 的 report 合并会保留它。
    """
    try:
        async with AsyncSessionLocal() as db:
            row = TaskRecord(
                user_id=str(user_id),
                channel=channel,
                chattype=chattype or None,
                target=list(target or []),
                question=question,
                status=QUEUED,
                ack_text=ack_text,
                report={"mandate": mandate} if mandate else None,
            )
            db.add(row)
            await db.commit()
            task_id = str(row.id)
        logger.info("task_created", task_id=task_id, user_id=user_id, channel=channel)
        return task_id
    except Exception as exc:
        logger.warning("task_create_failed", error=str(exc)[:200])
        return ""


async def _update(task_id: str, **fields: Any) -> None:
    if not task_id:
        return
    try:
        async with AsyncSessionLocal() as db:
            row = await db.get(TaskRecord, task_id)
            if row is None:
                return
            for key, value in fields.items():
                if key == "report" and isinstance(value, dict):
                    # 合并而非覆盖：保留创建时写入的 mandate 等键
                    base = row.report if isinstance(row.report, dict) else {}
                    value = {**base, **value}
                setattr(row, key, value)
            await db.commit()
    except Exception as exc:
        logger.warning("task_update_failed", task_id=task_id, error=str(exc)[:200])


async def mark_working(task_id: str) -> None:
    await _update(task_id, status=WORKING)


async def finish_task(
    task_id: str,
    *,
    status: str,
    report: dict[str, Any] | None = None,
    trace_id: Any = None,
    conversation_id: str = "",
    error: str = "",
) -> None:
    """写挂起态/终态。done/failed 记 ended_at；person/* 挂起态不记。"""
    fields: dict[str, Any] = {"status": status}
    if report is not None:
        fields["report"] = report
    if trace_id:
        try:
            fields["trace_id"] = int(trace_id)
        except (TypeError, ValueError):
            pass
    if conversation_id:
        fields["conversation_id"] = conversation_id
    if error:
        fields["error"] = error[:2000]
    if status in (DONE, FAILED):
        fields["ended_at"] = datetime.datetime.now(datetime.timezone.utc)
    await _update(task_id, **fields)
    logger.info("task_status", task_id=task_id, status=status)


async def complete_review_by_trace(trace_id: int) -> None:
    """结果反馈到达：最近一条 person/review 且 trace 匹配的任务 → done。"""
    try:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    select(TaskRecord)
                    .where(
                        TaskRecord.trace_id == int(trace_id),
                        TaskRecord.status == WAITING_REVIEW,
                    )
                    .order_by(TaskRecord.created_at.desc())
                    .limit(1)
                )
            ).scalars().first()
            if row is None:
                return
            row.status = DONE
            row.ended_at = datetime.datetime.now(datetime.timezone.utc)
            await db.commit()
            logger.info("task_review_done", task_id=row.id, trace_id=trace_id)
    except Exception as exc:
        logger.warning("task_review_done_failed", error=str(exc)[:200])


async def complete_waiting_answer(user_id: str, channel: str = "wecom") -> None:
    """澄清答案到达（候选按钮点击）：该用户最近一条 person/answer → done。"""
    try:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    select(TaskRecord)
                    .where(
                        TaskRecord.user_id == str(user_id),
                        TaskRecord.channel == channel,
                        TaskRecord.status == WAITING_ANSWER,
                    )
                    .order_by(TaskRecord.created_at.desc())
                    .limit(1)
                )
            ).scalars().first()
            if row is None:
                return
            row.status = DONE
            row.ended_at = datetime.datetime.now(datetime.timezone.utc)
            await db.commit()
            logger.info("task_answer_done", task_id=row.id, user_id=user_id)
    except Exception as exc:
        logger.warning("task_answer_done_failed", error=str(exc)[:200])


async def recover_inflight_tasks(
    notify: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> list[dict[str, Any]]:
    """启动恢复：queued/working 一律收尾为 failed（进程重启，流式回复已断）。

    notify：可选异步回调，由渠道方决定如何告知用户（如企微主动推送）。
    返回被收尾的任务摘要列表。
    """
    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(TaskRecord).where(TaskRecord.status.in_(_INFLIGHT))
                )
            ).scalars().all()
            now = datetime.datetime.now(datetime.timezone.utc)
            for row in rows:
                row.status = FAILED
                row.error = "服务重启，任务中断"
                row.ended_at = now
            await db.commit()
            items = [
                {
                    "id": str(r.id),
                    "user_id": r.user_id,
                    "channel": r.channel,
                    "target": list(r.target or []),
                    "question": r.question,
                }
                for r in rows
            ]
    except Exception as exc:
        logger.warning("task_recover_failed", error=str(exc)[:200])
        return []
    if items:
        logger.info("task_recovered", count=len(items))
    if notify:
        for item in items:
            try:
                await notify(item)
            except Exception as exc:
                logger.warning("task_recover_notify_failed", error=str(exc)[:200])
    return items
