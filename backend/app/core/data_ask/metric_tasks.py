"""训练度量日物化 Celery 任务（P1）：agent_metric_daily 每日 03:10 由 beat 触发。

与 train_metrics.compute_day 同一函数计算，保证看板实时口径与物化数据一致。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.tasks_runtime import run_in_persistent_loop
from app.worker import celery_app

logger = logging.getLogger("ds_metric_tasks")

_metric_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
MetricSessionLocal = async_sessionmaker(_metric_engine, expire_on_commit=False)


@celery_app.task(name="ds_distill.materialize_metrics", ignore_result=True, max_retries=0)
def materialize_metrics_task(day: str | None = None) -> None:
    """物化指定日（默认昨日）所有数据源的 agent_metric_daily 行。"""

    async def _run() -> None:
        from app.core.data_ask.train_metrics import materialize_day
        from app.db.models import AskTrace

        target = (
            date.fromisoformat(day)
            if day
            else (datetime.utcnow().date() - timedelta(days=1))
        )
        async with MetricSessionLocal() as db:
            res = await db.execute(select(AskTrace.data_source_id).distinct())
            ds_ids = [str(x) for (x,) in res.all()]
            done = 0
            for ds in ds_ids:
                try:
                    if await materialize_day(db, ds, target):
                        done += 1
                except Exception:
                    logger.exception("materialize_metrics failed ds=%s day=%s", ds, target)
            await db.commit()
            logger.info("materialize_metrics done day=%s sources=%s/%s", target, done, len(ds_ids))

    try:
        run_in_persistent_loop(_run())
    except Exception:
        logger.exception("materialize_metrics_task crashed")
