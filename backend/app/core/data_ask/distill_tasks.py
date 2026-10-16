"""知识蒸馏 Celery 异步任务（Agent Evolution 阶段二 L2）。

- distill_examples_task: 反馈 → 示例库（正/负例 + Milvus 向量）
- mine_templates_task:  高频问题聚类 → 分析模板
- mine_rules_task:      纠错记录 → 业务规则（候选）
- nightly_distill_task: 三类蒸馏全跑一遍
与 profile_tasks.py 同模式：NullPool 独立引擎，跨事件循环安全。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.tasks_runtime import run_in_persistent_loop
from app.worker import celery_app

logger = logging.getLogger("ds_distill_tasks")

_distill_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
DistillSessionLocal = async_sessionmaker(_distill_engine, expire_on_commit=False)


@celery_app.task(name="ds_distill.distill_examples", ignore_result=True, max_retries=0)
def distill_examples_task(data_source_id: str, task_id: int | None = None) -> None:
    """反馈 → 示例库。task_id 非空时同步更新 data_ask_train_tasks 状态（前端轮询回显）。"""
    from app.core.data_ask.distill.example_store import distill_examples

    async def _mark(status: str, progress: int = 0, detail: dict | None = None, error: str | None = None) -> None:
        if not task_id:
            return
        from app.db.models import DataAskTrainTask

        async with DistillSessionLocal() as tdb:
            row = await tdb.get(DataAskTrainTask, int(task_id))
            if not row:
                return
            row.status = status
            row.progress = int(progress)
            if detail is not None:
                row.detail = detail
            if error:
                row.error = str(error)[:2000]
            await tdb.commit()

    async def _run() -> None:
        async with DistillSessionLocal() as db:
            out = await distill_examples(db, data_source_id=str(data_source_id))
            await db.commit()
            logger.info("distill_examples_task done ds=%s result=%s", data_source_id, out)
            await _mark("done", 100, detail=out if isinstance(out, dict) else {"result": str(out)})

    try:
        run_in_persistent_loop(_mark("running", 10))
        run_in_persistent_loop(_run())
    except Exception as exc:
        logger.exception("distill_examples_task failed ds=%s", data_source_id)
        try:
            run_in_persistent_loop(_mark("failed", 100, error=str(exc)))
        except Exception:
            pass


@celery_app.task(name="ds_distill.mine_templates", ignore_result=True, max_retries=0)
def mine_templates_task(data_source_id: str, min_support: int = 3) -> None:
    from app.core.data_ask.distill.template_miner import mine_templates

    async def _run() -> None:
        async with DistillSessionLocal() as db:
            out = await mine_templates(db, data_source_id=str(data_source_id), min_support=int(min_support or 3))
            await db.commit()
            logger.info("mine_templates_task done ds=%s result=%s", data_source_id, out)

    try:
        run_in_persistent_loop(_run())
    except Exception:
        logger.exception("mine_templates_task failed ds=%s", data_source_id)


@celery_app.task(name="ds_distill.mine_rules", ignore_result=True, max_retries=0)
def mine_rules_task(data_source_id: str, min_support: int = 1) -> None:
    from app.core.data_ask.distill.rule_miner import mine_rules

    async def _run() -> None:
        async with DistillSessionLocal() as db:
            out = await mine_rules(db, data_source_id=str(data_source_id), min_support=int(min_support or 1))
            await db.commit()
            logger.info("mine_rules_task done ds=%s result=%s", data_source_id, out)

    try:
        run_in_persistent_loop(_run())
    except Exception:
        logger.exception("mine_rules_task failed ds=%s", data_source_id)


@celery_app.task(name="ds_distill.nightly_distill", ignore_result=True, max_retries=0)
def nightly_distill_task(data_source_id: str) -> None:
    from app.core.data_ask.distill.example_store import distill_examples
    from app.core.data_ask.distill.rule_miner import mine_rules
    from app.core.data_ask.distill.template_miner import mine_templates

    async def _run() -> None:
        async with DistillSessionLocal() as db:
            ex = await distill_examples(db, data_source_id=str(data_source_id))
            await db.commit()
            logger.info("nightly_distill[examples] ds=%s result=%s", data_source_id, ex)
            try:
                tp = await mine_templates(db, data_source_id=str(data_source_id))
                await db.commit()
                logger.info("nightly_distill[templates] ds=%s result=%s", data_source_id, tp)
            except Exception:
                logger.exception("nightly_distill[templates] failed ds=%s", data_source_id)
                await db.rollback()
            try:
                rl = await mine_rules(db, data_source_id=str(data_source_id))
                await db.commit()
                logger.info("nightly_distill[rules] ds=%s result=%s", data_source_id, rl)
            except Exception:
                logger.exception("nightly_distill[rules] failed ds=%s", data_source_id)
                await db.rollback()

    try:
        run_in_persistent_loop(_run())
    except Exception:
        logger.exception("nightly_distill_task failed ds=%s", data_source_id)


# ────────────── P2：影子对比 / 单源进化闭环 ──────────────


@celery_app.task(name="ds_distill.shadow_compare", ignore_result=True, max_retries=0)
def shadow_compare_task(data_source_id: str, question: str, task_id: int) -> None:
    """影子对比：同一问题「未更新记忆 vs 已更新记忆」双路生成，程序化差异结论。"""
    from app.core.data_ask.shadow import run_shadow_compare

    async def _mark(status: str, progress: int = 0, detail: dict | None = None, error: str | None = None) -> None:
        from app.db.models import DataAskTrainTask

        async with DistillSessionLocal() as tdb:
            row = await tdb.get(DataAskTrainTask, int(task_id))
            if not row:
                return
            row.status = status
            row.progress = int(progress)
            if detail is not None:
                row.detail = detail
            if error:
                row.error = str(error)[:2000]
            await tdb.commit()

    async def _run() -> None:
        async with DistillSessionLocal() as db:
            out = await run_shadow_compare(db, data_source_id=str(data_source_id), question=str(question))
            await db.commit()
            await _mark("done", 100, detail=out)

    try:
        run_in_persistent_loop(_mark("running", 10))
        run_in_persistent_loop(_run())
    except Exception as exc:
        logger.exception("shadow_compare_task failed ds=%s", data_source_id)
        try:
            run_in_persistent_loop(_mark("failed", 100, error=str(exc)))
        except Exception:
            pass


@celery_app.task(name="ds_distill.evolve_source", ignore_result=True, max_retries=0)
def evolve_source_task(data_source_id: str, task_id: int) -> None:
    """单数据源进化闭环（手动触发）：蒸馏 → 评测 → 晋升/回滚，结果写回任务行。"""
    from app.core.data_ask.evaluation.evolution import _evolve_one

    async def _mark(status: str, progress: int = 0, detail: dict | None = None, error: str | None = None) -> None:
        from app.db.models import DataAskTrainTask

        async with DistillSessionLocal() as tdb:
            row = await tdb.get(DataAskTrainTask, int(task_id))
            if not row:
                return
            row.status = status
            row.progress = int(progress)
            if detail is not None:
                row.detail = detail
            if error:
                row.error = str(error)[:2000]
            await tdb.commit()

    async def _run() -> None:
        out = await _evolve_one(DistillSessionLocal, str(data_source_id))
        failed = str(out.get("reason") or "").startswith("进化失败")
        await _mark("failed" if failed else "done", 100, detail=out)

    try:
        run_in_persistent_loop(_mark("running", 5))
        run_in_persistent_loop(_run())
    except Exception as exc:
        logger.exception("evolve_source_task failed ds=%s", data_source_id)
        try:
            run_in_persistent_loop(_mark("failed", 100, error=str(exc)))
        except Exception:
            pass
