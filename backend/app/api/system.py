from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_admin_user
from app.core.system.branding import get_branding, set_branding
from app.db.models import User
from app.db.session import get_db
from app.schemas.system import SystemBrandingOut, SystemBrandingUpdateIn

router = APIRouter(prefix="/system", tags=["System"])


@router.get("/branding", response_model=SystemBrandingOut)
async def read_system_branding(db: AsyncSession = Depends(get_db)):
    data = await get_branding(db)
    return SystemBrandingOut(**data)


@router.put("/branding", response_model=SystemBrandingOut)
async def update_system_branding(
    payload: SystemBrandingUpdateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    del user
    try:
        data = await set_branding(
            db,
            system_name=payload.system_name,
            system_icon=payload.system_icon,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SystemBrandingOut(**data)
