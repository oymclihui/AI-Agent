"""Excel template access helpers."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExcelParseTemplate, User


def can_use_template(template: ExcelParseTemplate, user: User) -> bool:
    if user.is_admin:
        return True
    if template.is_global:
        return True
    if template.owner_id is None:
        return True
    return template.owner_id == user.id


def can_edit_template(template: ExcelParseTemplate, user: User) -> bool:
    if user.is_admin:
        return True
    return template.owner_id == user.id or template.owner_id is None


async def assert_template_use(template: ExcelParseTemplate | None, user: User) -> ExcelParseTemplate:
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if not can_use_template(template, user):
        raise HTTPException(status_code=403, detail="Template access denied")
    return template


async def assert_template_edit(template: ExcelParseTemplate | None, user: User) -> ExcelParseTemplate:
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if not can_edit_template(template, user):
        raise HTTPException(status_code=403, detail="Template access denied")
    return template
