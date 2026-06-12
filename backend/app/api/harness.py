from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_user
from app.core.harness.gate import confirm_pending_action, reject_pending_action
from app.core.harness.policy import ToolPolicy
from app.db.models import ExecutionStatus, HarnessPendingAction, User
from app.db.session import get_db
from app.schemas.harness import HarnessPendingActionResponse, HarnessToolRiskResponse

router = APIRouter(prefix="/harness", tags=["Harness"])


def _action_response(action: HarnessPendingAction) -> HarnessPendingActionResponse:
    return HarnessPendingActionResponse(
        id=action.id,
        tool_name=action.tool_name,
        tool_args=action.tool_args or {},
        risk_level=action.risk_level,
        status=action.status,
        source=action.source,
        source_id=action.source_id,
        result=action.result,
        error_message=action.error_message,
        created_at=action.created_at,
        completed_at=action.completed_at,
    )


@router.get("/tools/risk", response_model=list[HarnessToolRiskResponse])
async def list_tool_risks(_user: User = Depends(get_current_user)):
    return [HarnessToolRiskResponse(**row) for row in ToolPolicy.list_tools_with_risk()]


@router.get("/actions/awaiting-confirmation", response_model=list[HarnessPendingActionResponse])
async def list_awaiting_actions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(HarnessPendingAction)
        .where(
            HarnessPendingAction.owner_id == user.id,
            HarnessPendingAction.status == ExecutionStatus.awaiting_confirmation,
        )
        .order_by(HarnessPendingAction.created_at.desc())
        .limit(50)
    )
    return [_action_response(row) for row in result.scalars().all()]


@router.post("/actions/{action_id}/confirm", response_model=HarnessPendingActionResponse)
async def confirm_action(
    action_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    action = await confirm_pending_action(db, user.id, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    await db.commit()
    await db.refresh(action)
    return _action_response(action)


@router.post("/actions/{action_id}/reject", response_model=HarnessPendingActionResponse)
async def reject_action(
    action_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    action = await reject_pending_action(db, user.id, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    await db.commit()
    await db.refresh(action)
    return _action_response(action)
