import ssl

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import event
from sqlalchemy.pool import NullPool
from typing import AsyncGenerator
from app.config import settings
from app.database_url import is_sqlite_url, DB_DRIVER_VASTBASE

_is_sqlite = is_sqlite_url(settings.DATABASE_URL)
_is_vastbase = settings.resolved_db_driver == DB_DRIVER_VASTBASE

_engine_kwargs: dict = {
    "echo": settings.SQL_ECHO,
}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"timeout": 30}
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs.update({"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20})
    connect_args: dict = {}
    if settings.DB_SSL == "disable":
        connect_args["ssl"] = False
    elif settings.DB_SSL == "require":
        connect_args["ssl"] = ssl.create_default_context()
    if _is_vastbase:
        connect_args.setdefault("server_settings", {})["application_name"] = "aiagnet"
    if connect_args:
        _engine_kwargs["connect_args"] = connect_args

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)


if _is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
