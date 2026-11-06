"""配置版本化 API（蓝图阶段四）：版本列表 / 回滚 / 准入策略与预警规则存档写入。

蓝图验收「任意配置改动可回滚可归因」：当前只覆盖阶段三引入的两份配置
（wecom_bot.policy、proactive.rules），其余配置后续按需纳入同一机制。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_admin_user
from app.core.versions import current_version, list_versions, rollback, snapshot_config
from app.core.wecom.policy import POLICY_KEY, _normalize
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/config", tags=["Config"])

# 纳入版本化的配置键白名单（阶段四先覆盖阶段三的两份）
_VERSIONED_KEYS = (POLICY_KEY, "proactive.rules")


def _check_key(key: str) -> None:
    if key not in _VERSIONED_KEYS:
        raise HTTPException(status_code=400, detail=f"未纳入版本化的配置：{key}")


@router.get("/versions")
async def get_versions(
    key: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """版本列表（新→旧）+ 当前版本号。"""
    _check_key(key)
    rows = await list_versions(db, key)
    return {
        "key": key,
        "current": await current_version(db, key),
        "versions": [
            {
                "version": r.version,
                "actor": r.actor,
                "note": r.note,
                "value": r.value,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


class RollbackBody(BaseModel):
    key: str
    version: int


@router.post("/rollback")
async def post_rollback(
    body: RollbackBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """回滚到指定版本（产生新版本号留痕）。"""
    _check_key(body.key)
    new_version = await rollback(db, body.key, body.version, actor=str(user.login))
    if new_version is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    return {"key": body.key, "version": new_version, "rolled_back_to": body.version}


@router.put("/wecom-policy")
async def put_wecom_policy(
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """存档式更新企微准入策略：校验归一化 → 版本号递增 → 快照留档。

    之后的入站消息即按新版本判定；在途任务不受影响，
    其 mandate.policy_version 仍指向产生它时的版本（可归因）。
    """
    policy = _normalize(body)
    version = await snapshot_config(db, POLICY_KEY, policy, actor=str(user.login))
    return {"key": POLICY_KEY, "version": version, "policy": policy}


@router.put("/proactive-rules")
async def put_proactive_rules(
    body: list[dict[str, Any]],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """存档式更新预警规则列表（observe/auto、推送目标、阈值等）。"""
    if not isinstance(body, list) or not all(isinstance(r, dict) for r in body):
        raise HTTPException(status_code=400, detail="规则必须是对象数组")
    version = await snapshot_config(db, "proactive.rules", body, actor=str(user.login))
    return {"key": "proactive.rules", "version": version}
