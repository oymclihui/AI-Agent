"""Database URL helpers for async/sync SQLAlchemy engines."""
from __future__ import annotations

from urllib.parse import quote_plus


def is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite")


def is_postgresql_url(url: str) -> bool:
    return url.startswith("postgresql")


def build_database_url(
    *,
    driver: str = "sqlite",
    host: str | None = None,
    port: int = 5432,
    user: str = "aiagnet",
    password: str = "",
    database: str = "aiagnet",
    sqlite_path: str = "./aiagnet.db",
    ssl: str = "prefer",
    async_driver: bool = True,
) -> str:
    """Build a SQLAlchemy database URL."""
    if driver == "sqlite":
        path = sqlite_path.replace("\\", "/")
        if async_driver:
            return f"sqlite+aiosqlite:///{path.lstrip('/')}"
        return f"sqlite:///{path.lstrip('/')}"

    if not host:
        raise ValueError("DB_HOST is required for PostgreSQL")

    pwd = quote_plus(password or "")
    scheme = "postgresql+asyncpg" if async_driver else "postgresql+psycopg2"
    url = f"{scheme}://{user}:{pwd}@{host}:{port}/{database}"
    if ssl == "require":
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}ssl=require"
    return url


def to_sync_url(async_url: str) -> str:
    """Convert async SQLAlchemy URL to sync driver equivalent."""
    if async_url.startswith("sqlite+aiosqlite"):
        return async_url.replace("sqlite+aiosqlite", "sqlite", 1)
    if async_url.startswith("postgresql+asyncpg"):
        return async_url.replace("postgresql+asyncpg", "postgresql+psycopg2", 1)
    return async_url


def database_label(url: str) -> str:
    if is_sqlite_url(url):
        return "sqlite"
    if is_postgresql_url(url):
        return "postgresql"
    return "unknown"
