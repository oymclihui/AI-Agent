"""Resolve and use per-user mailbox credentials."""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.email.imap_client import fetch_recent_messages
from app.db.models import UserMailboxCredential
from app.db.session import AsyncSessionLocal


async def get_user_mailbox(db: AsyncSession | None, user_id: str) -> UserMailboxCredential | None:
    async def _query(session: AsyncSession) -> UserMailboxCredential | None:
        result = await session.execute(
            select(UserMailboxCredential).where(
                UserMailboxCredential.user_id == user_id,
                UserMailboxCredential.is_active == True,
            ).limit(1)
        )
        return result.scalar_one_or_none()

    if db is not None:
        return await _query(db)
    async with AsyncSessionLocal() as session:
        return await _query(session)


def mailbox_imap_settings(row: UserMailboxCredential) -> tuple[str, int, bool]:
    host = row.imap_host or settings.IMAP_HOST
    port = row.imap_port or settings.IMAP_PORT
    use_ssl = row.imap_use_ssl if row.imap_use_ssl is not None else settings.IMAP_USE_SSL
    return host, port, use_ssl


async def fetch_user_mailbox(
    user_id: str,
    *,
    limit: int = 10,
    folder: str = "INBOX",
    db: AsyncSession | None = None,
) -> list[dict[str, Any]]:
    row = await get_user_mailbox(db, user_id)
    if not row:
        raise RuntimeError("Mailbox not configured. Add email and password in Settings.")

    host, port, use_ssl = mailbox_imap_settings(row)

    def _run() -> list[dict[str, Any]]:
        return fetch_recent_messages(
            host=host,
            port=port,
            use_ssl=use_ssl,
            username=row.email,
            password=row.mailbox_password,
            limit=limit,
            folder=folder,
        )

    return await asyncio.to_thread(_run)
