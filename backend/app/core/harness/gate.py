from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from langchain_core.tools import BaseTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.harness.context import HarnessContext
from app.core.harness.hooks import get_default_hooks
from app.core.harness.policy import ToolPolicy
from app.db.base import generate_uuid
from app.db.models import ExecutionStatus, HarnessPendingAction

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_pending_action(
    db: AsyncSession,
    ctx: HarnessContext,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
) -> HarnessPendingAction:
    action = HarnessPendingAction(
        id=generate_uuid(),
        owner_id=ctx.user_id,
        tool_name=tool_name,
        tool_args=tool_args,
        risk_level=ToolPolicy.risk_for(tool_name).value,
        status=ExecutionStatus.awaiting_confirmation,
        source=ctx.source,
        source_id=ctx.source_id,
    )
    db.add(action)
    await db.flush()
    logger.info("harness_pending_created", action_id=action.id, tool=tool_name)
    return action


def pending_message(action: HarnessPendingAction) -> str:
    return (
        f"Tool '{action.tool_name}' requires user approval before execution. "
        f"Pending action id={action.id}. "
        "Ask the user to approve in Chat harness panel or POST /harness/actions/{id}/confirm."
    )


async def execute_tool(
    tool: BaseTool,
    tool_args: dict[str, Any],
    *,
    db: AsyncSession | None = None,
    ctx: HarnessContext | None = None,
    skip_gate: bool = False,
) -> str:
    hooks = get_default_hooks()
    await hooks.run_before(tool.name, tool_args)

    if (
        not skip_gate
        and ctx
        and db
        and ToolPolicy.requires_harness_confirmation(tool.name, auto_confirm=ctx.auto_confirm)
    ):
        action = await create_pending_action(db, ctx, tool_name=tool.name, tool_args=tool_args)
        result = pending_message(action)
        await hooks.run_after(tool.name, tool_args, result)
        return result

    try:
        result = await tool.arun(tool_args)
        out = str(result)
    except Exception as exc:
        out = f"Tool error: {exc}"

    await hooks.run_after(tool.name, tool_args, out)
    return out


async def confirm_pending_action(
    db: AsyncSession,
    user_id: str,
    action_id: str,
) -> HarnessPendingAction | None:
    from app.core.tools.registry import ToolRegistry

    action = await db.get(HarnessPendingAction, action_id)
    if not action or action.owner_id != user_id:
        return None
    if action.status != ExecutionStatus.awaiting_confirmation:
        return action

    tool = ToolRegistry.get_instance().get(action.tool_name)
    if not tool:
        action.status = ExecutionStatus.failed
        action.error_message = f"Tool '{action.tool_name}' not found"
        action.completed_at = _utcnow()
        await db.flush()
        return action

    from app.core.auth.context import set_current_user_id, reset_current_user_id

    token = set_current_user_id(user_id)
    try:
        result = await execute_tool(
            tool,
            action.tool_args or {},
            db=db,
            ctx=None,
            skip_gate=True,
        )
        action.result = result[:8000]
        action.status = ExecutionStatus.completed
        action.completed_at = _utcnow()
    except Exception as exc:
        action.status = ExecutionStatus.failed
        action.error_message = str(exc)
        action.completed_at = _utcnow()
    finally:
        reset_current_user_id(token)

    await db.flush()
    return action


async def reject_pending_action(
    db: AsyncSession,
    user_id: str,
    action_id: str,
) -> HarnessPendingAction | None:
    action = await db.get(HarnessPendingAction, action_id)
    if not action or action.owner_id != user_id:
        return None
    if action.status == ExecutionStatus.awaiting_confirmation:
        action.status = ExecutionStatus.cancelled
        action.error_message = "Rejected by user"
        action.completed_at = _utcnow()
        await db.flush()
    return action
