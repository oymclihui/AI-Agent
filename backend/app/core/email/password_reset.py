"""Password reset tokens and notification emails."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.email.smtp_client import send_email, smtp_configured
from app.db.base import generate_uuid
from app.db.models import PasswordResetToken, User

logger = structlog.get_logger(__name__)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _reset_link(raw_token: str) -> str:
    base = settings.APP_PUBLIC_URL.rstrip("/")
    return f"{base}/login/reset-password?token={raw_token}"


async def create_and_send_reset(db: AsyncSession, user: User) -> bool:
    """Create reset token and email user. Returns True if mail sent."""
    if not user.email or "@" not in user.email or user.email.endswith("@local"):
        return False
    if not smtp_configured():
        logger.warning("password_reset_smtp_not_configured")
        return False

    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=datetime.now(timezone.utc))
    )

    raw = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES)
    db.add(
        PasswordResetToken(
            id=generate_uuid(),
            user_id=user.id,
            token_hash=_hash_token(raw),
            expires_at=expires,
        )
    )
    await db.flush()

    link = _reset_link(raw)
    subject = "AI-AGENT 密码重置"
    html = f"""
    <p>您好 {user.display_name}，</p>
    <p>我们收到了您的 AI-AGENT 账户密码重置请求。请点击以下链接设置新密码（{settings.PASSWORD_RESET_EXPIRE_MINUTES} 分钟内有效）：</p>
    <p><a href="{link}">{link}</a></p>
    <p>如非本人操作，请忽略此邮件。</p>
    """
    text = f"请打开链接重置密码（{settings.PASSWORD_RESET_EXPIRE_MINUTES} 分钟内有效）：{link}"

    send_email(to=user.email, subject=subject, html_body=html, text_body=text)
    logger.info("password_reset_email_sent", user_id=user.id, email=user.email)
    return True


async def validate_reset_token(db: AsyncSession, raw_token: str) -> User | None:
    token_hash = _hash_token(raw_token.strip())
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(PasswordResetToken, User)
        .join(User, User.id == PasswordResetToken.user_id)
        .where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
            User.is_active == True,
        )
        .limit(1)
    )
    row = result.first()
    return row[1] if row else None


async def consume_reset_token(db: AsyncSession, raw_token: str, new_password_hash: str) -> bool:
    token_hash = _hash_token(raw_token.strip())
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(PasswordResetToken, User)
        .join(User, User.id == PasswordResetToken.user_id)
        .where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .limit(1)
    )
    row = result.first()
    if not row:
        return False
    token_row, user = row
    user.password_hash = new_password_hash
    token_row.used_at = now
    await db.flush()
    return True
