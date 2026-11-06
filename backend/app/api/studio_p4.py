"""P4 API：行级权限管理（管理员配置，SQL 出口统一生效）。"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_admin_user, get_current_user
from app.core.analysis.spec import IDENT
from app.db.models import DataSource, RowPermission, User
from app.db.session import get_db

router = APIRouter(prefix="/studio", tags=["DashboardStudioP4"])

_FORBIDDEN_VALUE = re.compile(r"(;|--|/\*|\*/)", re.I)


def _perm_out(p: RowPermission, user: User | None = None) -> dict[str, Any]:
    return {
        "id": p.id,
        "data_source_id": p.data_source_id,
        "user_id": p.user_id,
        "user_name": (user.display_name if user else "") or "",
        "employee_no": (user.employee_no if user else "") or "",
        "dimension_field": p.dimension_field,
        "allowed_values": list(p.allowed_values or []),
        "note": p.note,
        "active": p.active,
    }


@router.get("/row-permissions")
async def list_row_permissions(
    data_source_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    rows = (
        await db.execute(
            select(RowPermission)
            .where(RowPermission.data_source_id == data_source_id)
            .order_by(RowPermission.created_at.desc())
            .limit(200)
        )
    ).scalars().all()
    users: dict[str, User] = {}
    if rows:
        urows = (
            await db.execute(select(User).where(User.id.in_([r.user_id for r in rows])))
        ).scalars().all()
        users = {str(u.id): u for u in urows}
    return {"items": [_perm_out(r, users.get(str(r.user_id))) for r in rows]}


@router.get("/row-permission-users")
async def list_permission_users(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    """可选用户清单（限管理员）。"""
    rows = (
        await db.execute(
            select(User).where(User.is_active.is_(True)).order_by(User.display_name.asc()).limit(200)
        )
    ).scalars().all()
    return {
        "items": [
            {"id": str(u.id), "display_name": u.display_name, "employee_no": u.employee_no or "", "is_admin": bool(u.is_admin)}
            for u in rows
        ]
    }


@router.post("/row-permissions")
async def create_row_permission(
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    sid = str(payload.get("data_source_id") or "").strip()
    uid = str(payload.get("user_id") or "").strip()
    field = str(payload.get("dimension_field") or "").strip()
    if not IDENT.match(field):
        raise HTTPException(status_code=422, detail="dimension_field 必须是合法字段名")
    source = await db.get(DataSource, sid)
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    target = await db.get(User, uid)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    values = payload.get("allowed_values")
    if not isinstance(values, list) or any(not isinstance(v, str) or _FORBIDDEN_VALUE.search(v) for v in values):
        raise HTTPException(status_code=422, detail="allowed_values 必须是字符串数组")
    exists = (
        await db.execute(
            select(RowPermission).where(
                RowPermission.data_source_id == sid,
                RowPermission.user_id == uid,
                RowPermission.dimension_field == field,
            )
        )
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="该用户在该数据源上已有此字段权限，请直接编辑")
    perm = RowPermission(
        data_source_id=sid,
        user_id=uid,
        dimension_field=field,
        allowed_values=[v for v in values],
        note=str(payload.get("note") or "")[:255],
        active=True,
    )
    db.add(perm)
    await db.commit()
    await db.refresh(perm)
    return _perm_out(perm, target)


@router.patch("/row-permissions/{pid}")
async def patch_row_permission(
    pid: str,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    perm = await db.get(RowPermission, str(pid))
    if not perm:
        raise HTTPException(status_code=404, detail="权限不存在")
    if "allowed_values" in payload:
        values = payload["allowed_values"]
        if not isinstance(values, list) or any(not isinstance(v, str) or _FORBIDDEN_VALUE.search(v) for v in values):
            raise HTTPException(status_code=422, detail="allowed_values 必须是字符串数组")
        perm.allowed_values = values
    if "active" in payload:
        perm.active = bool(payload["active"])
    if "note" in payload:
        perm.note = str(payload["note"] or "")[:255]
    await db.commit()
    target = await db.get(User, str(perm.user_id))
    return _perm_out(perm, target)


@router.delete("/row-permissions/{pid}")
async def delete_row_permission(
    pid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    perm = await db.get(RowPermission, str(pid))
    if not perm:
        raise HTTPException(status_code=404, detail="权限不存在")
    await db.delete(perm)
    await db.commit()
    return {"deleted": True}
