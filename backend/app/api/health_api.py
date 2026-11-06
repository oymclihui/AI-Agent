"""健康板 API（蓝图阶段四）：管理台读取的组件健康视图，与企微 /状态 同源。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_admin_user
from app.core.health import collect_health
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/board")
async def health_board(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """组件健康条目：db / redis / wecom / outbox / proactive。"""
    return await collect_health(db)
