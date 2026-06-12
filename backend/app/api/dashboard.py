import asyncio
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db, AsyncSessionLocal
from app.schemas.dashboard import DashboardOverview
from app.core.dashboard.overview import build_dashboard_overview
from app.core.auth.deps import get_current_user
from app.core.auth.permissions import assert_permission, resolve_data_scope
from app.db.models import User


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/overview", response_model=DashboardOverview)
async def dashboard_overview(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    scope = await resolve_data_scope(db, user)
    assert_permission(scope, "dashboard:view")
    data = await build_dashboard_overview(db, scope)
    return data


@router.get("/stream")
async def dashboard_stream(
    interval: int = Query(default=30, ge=5, le=120),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scope = await resolve_data_scope(db, user)
    assert_permission(scope, "dashboard:view")

    async def event_generator():
        while True:
            async with AsyncSessionLocal() as session:
                user_scope = await resolve_data_scope(session, user)
                payload = await build_dashboard_overview(session, user_scope)
            yield f"data: {json.dumps(payload, default=str)}\n\n"
            await asyncio.sleep(interval)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
