"""Database URL helpers for async/sync SQLAlchemy engines."""
from __future__ import annotations

from urllib.parse import quote_plus

# Business DB driver labels shown in /health and logs.
DB_DRIVER_SQLITE = "sqlite"
DB_DRIVER_POSTGRESQL = "postgresql"
DB_DRIVER_VASTBASE = "vastbase"

PG_COMPAT_DRIVERS = frozenset({DB_DRIVER_POSTGRESQL, DB_DRIVER_VASTBASE})


def is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite")


def is_postgresql_url(url: str) -> bool:
    return url.startswith("postgresql")


def resolve_db_driver(url: str, driver_setting: str = "auto") -> str:
    """Resolve configured driver label (sqlite | postgresql | vastbase)."""
    driver = (driver_setting or "auto").strip().lower()
    if driver in {DB_DRIVER_SQLITE, DB_DRIVER_POSTGRESQL, DB_DRIVER_VASTBASE}:
        return driver
    if is_sqlite_url(url):
        return DB_DRIVER_SQLITE
    if is_postgresql_url(url):
        return DB_DRIVER_POSTGRESQL
    return "unknown"


def database_label(url: str, driver_setting: str = "auto") -> str:
    return resolve_db_driver(url, driver_setting)


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
    normalized = (driver or "sqlite").strip().lower()
    if normalized == DB_DRIVER_SQLITE:
        path = sqlite_path.replace("\\", "/")
        if async_driver:
            return f"sqlite+aiosqlite:///{path.lstrip('/')}"
        return f"sqlite:///{path.lstrip('/')}"

    if normalized not in PG_COMPAT_DRIVERS:
        raise ValueError(f"Unsupported database driver: {driver}")

    if not host:
        raise ValueError("DB_HOST is required for PostgreSQL / VastBase")

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


def build_url_from_parts(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    ssl: str = "prefer",
    async_driver: bool = True,
) -> str:
    """Build PostgreSQL-protocol URL from connection parts."""
    return build_database_url(
        driver=DB_DRIVER_POSTGRESQL,
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        ssl=ssl,
        async_driver=async_driver,
    )
