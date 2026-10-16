"""评估进化 Celery 任务（Agent Evolution 阶段四 L4）。

- ds_eval.run_evaluation:   异步执行一轮回归评估（手动触发）
- ds_eval.weekly_evolution: 每周进化闭环（celery beat 周一 02:00 UTC，也可手动触发）
与 factory_tasks.py 同模式：NullPool 独立引擎，跨事件循环安全。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.tasks_runtime import run_in_persistent_loop
from app.worker import celery_app

logger = logging.getLogger("agent_eval_tasks")

_eval_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
EvalSessionLocal = async_sessionmaker(_eval_engine, expire_on_commit=False)


@celery_app.task(name="ds_eval.run_evaluation", ignore_result=True, max_retries=0)
def run_evaluation(data_source_id: str, run_id: int) -> None:
    from app.core.data_ask.evaluation.runner import run_eval_run
    from app.db.models import AgentEvalRun, DataSource

    async def _run() -> None:
        async with EvalSessionLocal() as db:
            run_row = await db.get(AgentEvalRun, int(run_id))
            source = await db.get(DataSource, str(data_source_id))
            if not run_row or not source:
                logger.warning("run_evaluation_skip run=%s ds=%s not found", run_id, data_source_id)
                return
            try:
                await run_eval_run(db, run_row, source)
                await db.commit()
                logger.info(
                    "run_evaluation done run=%s ds=%s overall=%s",
                    run_id, data_source_id, run_row.overall_score,
                )
            except Exception as exc:
                await db.rollback()
                logger.exception("run_evaluation failed run=%s", run_id)
                async with EvalSessionLocal() as edb:
                    err_row = await edb.get(AgentEvalRun, int(run_id))
                    if err_row:
                        err_row.status = "failed"
                        err_row.error_message = str(exc)[:500]
                        await edb.commit()

    try:
        run_in_persistent_loop(_run())
    except Exception:
        logger.exception("run_evaluation_task failed run=%s ds=%s", run_id, data_source_id)


@celery_app.task(name="ds_eval.weekly_evolution", ignore_result=True, max_retries=0)
def weekly_evolution_task() -> None:
    from app.core.data_ask.evaluation.evolution import weekly_evolution

    async def _run() -> None:
        results = await weekly_evolution(EvalSessionLocal)
        promoted = [r for r in results if r.get("promoted")]
        logger.info(
            "weekly_evolution done sources=%s promoted=%s",
            len(results), len(promoted),
        )

    try:
        run_in_persistent_loop(_run())
    except Exception:
        logger.exception("weekly_evolution_task failed")
