"""Schema 画像 Celery 异步任务（Agent Evolution 阶段一）。

- build_profile_task: 数据源画像构建（API 触发后不阻塞响应）
- 与 ml_evolution/tasks.py 同模式：NullPool 独立引擎，跨事件循环安全
- LLM 推断在任务进程内调用，失败仅影响 inferred_comment 字段，画像其余部分照常落库
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.tasks_runtime import run_in_persistent_loop
from app.worker import celery_app

logger = logging.getLogger("ds_profile_tasks")

_profile_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
ProfileSessionLocal = async_sessionmaker(_profile_engine, expire_on_commit=False)


@celery_app.task(name="ds_profile.build_profile", ignore_result=True, max_retries=0)
def build_profile_task(data_source_id: str, trigger: str = "manual", profile_id: int | None = None) -> None:
    from app.core.data_ask.profile import build_schema_profile
    from app.db.models import DataSource

    async def _run() -> None:
        async with ProfileSessionLocal() as db:
            source = await db.get(DataSource, data_source_id)
            if not source:
                logger.warning("build_profile_task: data source %s not found", data_source_id)
                return
            row = await build_schema_profile(db, source, trigger=trigger, profile_id=profile_id)
            await db.commit()
            logger.info(
                "build_profile_task done ds=%s version=%s status=%s tables=%s cols=%s ms=%s",
                data_source_id, row.version, row.status, row.table_count, row.column_count, row.duration_ms,
            )

    try:
        run_in_persistent_loop(_run())
    except Exception:
        logger.exception("build_profile_task failed ds=%s", data_source_id)
