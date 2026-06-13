"""Detect whether first-run setup is still required."""
from __future__ import annotations

from sqlalchemy import func, select, text

from app.config import settings
from app.core.setup.token import setup_token_required
from app.core.database.env_config import current_db_config
from app.db.models import User
from app.db.session import engine


async def count_users() -> int | None:
    """Return user count, or None if DB/users table is unavailable."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        async with engine.begin() as conn:
            result = await conn.execute(select(func.count()).select_from(User))
            return int(result.scalar() or 0)
    except Exception:
        return None


async def setup_status_snapshot() -> dict:
    cfg = current_db_config()
    db_connected = False
    connection_message = ""
    user_count: int | None = None

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_connected = True
        connection_message = "Connected"
        user_count = await count_users()
    except Exception as exc:
        connection_message = str(exc)[:400]

    has_users = (user_count or 0) > 0
    setup_required = not has_users

    return {
        "setup_required": setup_required,
        "setup_token_required": setup_token_required(),
        "db_connected": db_connected,
        "connection_message": connection_message,
        "has_users": has_users,
        "user_count": user_count or 0,
        "default_admin_login": settings.DEFAULT_ADMIN_EMPLOYEE_NO,
        "db_driver": cfg["driver"],
        "db_host": cfg["host"],
        "db_port": cfg["port"],
        "db_user": cfg["user"],
        "db_name": cfg["database"],
        "db_schema": cfg["db_schema"],
    }
