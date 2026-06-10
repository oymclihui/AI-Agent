import ssl

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import event
from sqlalchemy.pool import NullPool
from typing import AsyncGenerator
from app.config import settings
from app.database_url import is_sqlite_url

_is_sqlite = is_sqlite_url(settings.DATABASE_URL)

_engine_kwargs: dict = {
    "echo": settings.SQL_ECHO,
}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"timeout": 30}
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs.update({"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20})
    if settings.DB_SSL == "disable":
        _engine_kwargs["connect_args"] = {"ssl": False}
    elif settings.DB_SSL == "require":
        _engine_kwargs["connect_args"] = {"ssl": ssl.create_default_context()}

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
