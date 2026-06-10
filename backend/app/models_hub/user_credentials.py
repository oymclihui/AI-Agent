"""Resolve per-user LLM API credentials."""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserModelCredential
from app.db.session import AsyncSessionLocal


async def resolve_user_credentials(
    user_id: Optional[str],
    provider: str,
    model: str,
    db: Optional[AsyncSession] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Return (api_key, base_url) override for the user, if configured."""
    if not user_id:
        return None, None

    async def _lookup(session: AsyncSession) -> tuple[Optional[str], Optional[str]]:
        result = await session.execute(
            select(UserModelCredential).where(
                UserModelCredential.user_id == user_id,
                UserModelCredential.provider == provider.lower(),
                UserModelCredential.is_active == True,
            )
        )
        rows = result.scalars().all()
        if not rows:
            return None, None
        exact = next((r for r in rows if r.model_id == model), None)
        generic = next((r for r in rows if not r.model_id), None)
        chosen = exact or generic
        if not chosen:
            return None, None
        return chosen.api_key, chosen.base_url

    if db is not None:
        return await _lookup(db)
    async with AsyncSessionLocal() as session:
        return await _lookup(session)
