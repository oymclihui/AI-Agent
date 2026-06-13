"""Resolve per-user corporate KMS (BYD KMS) credentials."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserKmsCredential
from app.db.session import AsyncSessionLocal


@dataclass(frozen=True)
class CallerKmsContext:
    kms_user_id: str
    api_url: Optional[str] = None
    api_key: Optional[str] = None


async def get_user_kms_credential(
    user_id: str,
    db: AsyncSession | None = None,
) -> UserKmsCredential | None:
    async def _lookup(session: AsyncSession) -> UserKmsCredential | None:
        result = await session.execute(
            select(UserKmsCredential).where(
                UserKmsCredential.user_id == user_id,
                UserKmsCredential.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    if db is not None:
        return await _lookup(db)
    async with AsyncSessionLocal() as session:
        return await _lookup(session)


async def resolve_caller_kms_context(
    user: User | None,
    db: AsyncSession | None = None,
) -> CallerKmsContext | None:
    """Build KMS caller identity from user profile + optional per-user KMS credential."""
    if not user:
        return None

    cred = await get_user_kms_credential(user.id, db)
    kms_user_id = (
        (cred.kms_user_id if cred and cred.kms_user_id else None)
        or (user.employee_no or "").strip()
    )
    if not kms_user_id:
        return None

    return CallerKmsContext(
        kms_user_id=kms_user_id,
        api_url=(cred.api_url.strip() if cred and cred.api_url else None),
        api_key=(cred.api_key.strip() if cred and cred.api_key else None),
    )
