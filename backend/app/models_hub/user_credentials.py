"""Resolve per-user LLM API credentials."""
from __future__ import annotations  # noqa: I001

import contextvars
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.credentials import decrypt_secret, encrypt_secret
from app.db.models import UserModelCredential
from app.db.session import AsyncSessionLocal

_allow_personal = contextvars.ContextVar("allow_personal_llm_keys", default=True)


def suspend_personal_keys() -> contextvars.Token:
    """Scheduled jobs call this so a personal key is never used for someone else."""
    return _allow_personal.set(False)


def resume_personal_keys(token: contextvars.Token) -> None:
    _allow_personal.reset(token)


def personal_keys_allowed() -> bool:
    return _allow_personal.get()


def seal_secret(plain: str) -> str:
    return "enc:" + encrypt_secret(plain)


def open_secret(stored: Optional[str]) -> str:
    if not stored:
        return ""
    if stored.startswith("enc:"):
        return decrypt_secret(stored[4:])
    return stored


def _current_user_id(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    from app.core.auth.context import get_current_user_id

    return get_current_user_id()


async def resolve_user_default(
    user_id: Optional[str],
    db: Optional[AsyncSession] = None,
) -> Optional[UserModelCredential]:
    """The model this person marked as their own default."""
    if not personal_keys_allowed():
        return None
    uid = _current_user_id(user_id)
    if not uid:
        return None

    async def _lookup(session: AsyncSession) -> Optional[UserModelCredential]:
        result = await session.execute(
            select(UserModelCredential).where(
                UserModelCredential.user_id == uid,
                UserModelCredential.is_active == True,
                UserModelCredential.is_default == True,
            ).limit(1)
        )
        return result.scalar_one_or_none()

    if db is not None:
        return await _lookup(db)
    async with AsyncSessionLocal() as session:
        return await _lookup(session)


async def resolve_user_credentials(
    user_id: Optional[str],
    provider: str,
    model: str,
    db: Optional[AsyncSession] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Return (api_key, base_url) override for the user, if configured."""
    if not personal_keys_allowed():
        return None, None
    uid = _current_user_id(user_id)
    if not uid:
        return None, None

    async def _lookup(session: AsyncSession) -> tuple[Optional[str], Optional[str]]:
        result = await session.execute(
            select(UserModelCredential).where(
                UserModelCredential.user_id == uid,
                UserModelCredential.provider == provider.lower(),
                UserModelCredential.is_active == True,
            )
        )
        rows = result.scalars().all()
        if not rows:
            return None, None
        exact = next((row for row in rows if row.model_id == model), None)
        generic = next((row for row in rows if not row.model_id), None)
        chosen = exact or generic
        if not chosen:
            return None, None
        return open_secret(chosen.api_key), chosen.base_url

    if db is not None:
        return await _lookup(db)
    async with AsyncSessionLocal() as session:
        return await _lookup(session)
