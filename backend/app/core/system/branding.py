"""Platform branding (system name & icon) stored in system_settings."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import SystemSetting

BRANDING_KEY = "platform_branding"
DEFAULT_SYSTEM_NAME = "AI-AGENT"
MAX_ICON_BYTES = 512 * 1024


def default_branding() -> dict:
    return {
        "system_name": settings.APP_NAME or DEFAULT_SYSTEM_NAME,
        "system_icon": None,
    }


async def get_branding(db: AsyncSession) -> dict:
    row = await db.get(SystemSetting, BRANDING_KEY)
    if not row or not isinstance(row.value, dict):
        return default_branding()
    name = (row.value.get("system_name") or "").strip() or default_branding()["system_name"]
    icon = row.value.get("system_icon")
    if icon is not None and not isinstance(icon, str):
        icon = None
    if icon == "":
        icon = None
    return {"system_name": name, "system_icon": icon}


async def set_branding(db: AsyncSession, *, system_name: str, system_icon: str | None) -> dict:
    name = (system_name or "").strip() or DEFAULT_SYSTEM_NAME
    icon = (system_icon or "").strip() or None
    if icon and len(icon.encode("utf-8")) > MAX_ICON_BYTES:
        raise ValueError(f"Icon too large (max {MAX_ICON_BYTES // 1024}KB)")
    payload = {"system_name": name, "system_icon": icon}
    row = await db.get(SystemSetting, BRANDING_KEY)
    if row:
        row.value = payload
    else:
        db.add(SystemSetting(key=BRANDING_KEY, value=payload))
    await db.commit()
    return payload
