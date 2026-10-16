"""智能体工厂 Celery 异步任务（Agent Evolution 阶段三 L3）。

- regenerate_candidate_task: 蒸馏后再生成 → 为已绑定智能体创建新候选版本（不自动发布）
与 distill_tasks.py / profile_tasks.py 同模式：NullPool 独立引擎，跨事件循环安全。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.tasks_runtime import run_in_persistent_loop
from app.worker import celery_app

logger = logging.getLogger("agent_factory_tasks")

_factory_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
FactorySessionLocal = async_sessionmaker(_factory_engine, expire_on_commit=False)


@celery_app.task(name="agent_factory.regenerate_candidate", ignore_result=True, max_retries=0)
def regenerate_candidate_task(data_source_id: str, nl_prompt: str | None = None) -> None:
    from app.core.data_ask.factory.service import regenerate_candidate
    from app.db.models import DataSource

    async def _run() -> None:
        async with FactorySessionLocal() as db:
            source = await db.get(DataSource, str(data_source_id))
            if not source:
                logger.warning("regenerate_skip ds=%s not found", data_source_id)
                return
            row = await regenerate_candidate(db, source, nl_prompt=nl_prompt)
            await db.commit()
            logger.info(
                "regenerate_candidate_task done ds=%s version=%s",
                data_source_id, getattr(row, "version", None),
            )

    try:
        run_in_persistent_loop(_run())
    except Exception:
        logger.exception("regenerate_candidate_task failed ds=%s", data_source_id)
