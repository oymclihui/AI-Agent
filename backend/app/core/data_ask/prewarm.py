"""问数热点预计算（蓝图一期 L4 缓存优化）：定时回填结果缓存，首次提问即命中。

设计：
- 活跃 (user, data_source) 对取自最近 ask_trace（按 id 倒序窗口内去重）
- 预热问题 = 标准问法（今天/昨天/上周 × 核心指标，与追问 chips 模板一致）
  + 该用户真实问过的独立问句（跳过指代类追问，避免无 history 改写错口径）
- 只预热指标层可命中的问题（_resolve_relative_time 标注 + try_metric_route 预判），
  避免 LLM 路径慢查询风暴
- 写入与 run_data_ask wrapper 完全一致的缓存键；直接调 _run_data_ask_impl，
  不写 ask_trace（不污染统计）
"""
from __future__ import annotations

import asyncio
import logging
import os
import re

from sqlalchemy import select

from app.core.cache.redis_cache import cache_set_json, make_dataask_cache_key
from app.db.models import AskTrace, DataSource, User
from app.db.session import AsyncSessionLocal
from app.core.data_ask.service import (
    _cacheable_question,
    _resolve_relative_time,
    _run_data_ask_impl,
    _user_key,
    load_source_context,
)
from app.core.data_ask.metric_layer import try_metric_route

logger = logging.getLogger("data_ask_prewarm")

PREWARM_INTERVAL = int(os.getenv("DATAASK_PREWARM_INTERVAL", "300"))       # 轮询间隔
PREWARM_MAX_PAIRS = int(os.getenv("DATAASK_PREWARM_MAX_PAIRS", "10"))      # 每轮最多 (user, ds) 对
PREWARM_MAX_Q = int(os.getenv("DATAASK_PREWARM_MAX_Q", "32"))              # 每对最多问题数
PREWARM_TTL = int(os.getenv("DATAASK_PREWARM_TTL", "900"))                 # 预热键 TTL（跨轮存活）
PREWARM_Q_TIMEOUT = int(os.getenv("DATAASK_PREWARM_Q_TIMEOUT", "20"))      # 单问超时（秒）
PREWARM_CONCURRENCY = int(os.getenv("DATAASK_PREWARM_CONCURRENCY", "3"))   # 对间并行度
PREWARM_ENABLED = os.getenv("DATAASK_PREWARM_ENABLED", "1") != "0"

# 指代类追问（与 session_engine._RE_REFERENTIAL 同式）：预热不带会话历史，改写口径会错，跳过
_RE_REFERENTIAL = re.compile(r"^[那么再还又]|呢[？?。!！]?$|换(成|个|一下)|看看?")


def _standard_questions() -> list[str]:
    """标准问法（按优先级排序）：今天/昨天/上周 × 全指标优先，再补关联指标与走势/门店。

    顺序即截断优先级——与 build_suggestions chips 模板对齐，用户点 chips 即精确命中。
    """
    from app.core.data_ask.metric_layer import METRICS
    from app.core.data_ask.session_engine import _RELATED

    names = [m.name for m in METRICS.values()]
    out = [f"今天{n}是多少" for n in names]
    out += [f"昨天{n}是多少" for n in names]
    out += [f"上周{n}是多少" for n in names]
    out += [f"昨天{_RELATED[n]}是多少" for n in names if n in _RELATED]
    out += [f"最近7天每天{n}走势" for n in names]
    out += [f"各门店{n}" for n in names]
    return _dedupe(out)


async def _active_pairs() -> list[tuple[str, str]]:
    """最近 trace 里活跃的 (user_id, data_source_id) 对（去重，保序）。"""
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(AskTrace.user_id, AskTrace.data_source_id)
                .where(AskTrace.success.is_(True), AskTrace.user_id.isnot(None))
                .order_by(AskTrace.id.desc())
                .limit(500)
            )
        ).all()
    seen: set[tuple[str, str]] = set()
    pairs: list[tuple[str, str]] = []
    for uid, dsid in rows:
        key = (str(uid), str(dsid))
        if key not in seen:
            seen.add(key)
            pairs.append(key)
    return pairs[:PREWARM_MAX_PAIRS]


async def _recent_questions(user_id: str, ds_id: str) -> list[str]:
    """该用户在该数据源上问过的独立问句（成功记录，去重，最近的优先）。"""
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(AskTrace.question)
                .where(
                    AskTrace.user_id == user_id,
                    AskTrace.data_source_id == ds_id,
                    AskTrace.success.is_(True),
                )
                .order_by(AskTrace.id.desc())
                .limit(100)
            )
        ).all()
    out: list[str] = []
    seen: set[str] = set()
    for (q,) in rows:
        text = (q or "").strip()
        if (
            text
            and text not in seen
            and not _RE_REFERENTIAL.search(text)
            and _cacheable_question(text)
        ):
            seen.add(text)
            out.append(text)
    return out


async def _prewarm_pair(user: User, ds_id: str, questions: list[str]) -> int:
    """对一个 (user, ds) 执行可命中指标层的问题并写缓存。返回写入数。"""
    done = 0
    async with AsyncSessionLocal() as db:
        source = await db.get(DataSource, ds_id)
        if source is None:
            return 0
        try:
            source, all_tables, _sem, _pt, _pr = await load_source_context(db, ds_id)
        except Exception:
            return 0
        for q in questions:
            if not _cacheable_question(q):
                continue
            try:
                annotated = await _resolve_relative_time(source, all_tables, q)
                hit = await try_metric_route(source, annotated, all_tables)
                if not hit:
                    continue
                result = await asyncio.wait_for(
                    _run_data_ask_impl(
                        db, data_source_id=ds_id, question=q, user=user,
                        execute=True, use_memory=False,
                    ),
                    timeout=PREWARM_Q_TIMEOUT,
                )
            except Exception:
                continue
            if not isinstance(result, dict) or result.get("route") != "metric":
                continue
            # 与 wrapper 一致：缓存前挂上追问建议
            try:
                from app.core.data_ask.session_engine import build_suggestions, extract_state

                state = extract_state(result)
                if not result.get("suggestions"):
                    result["suggestions"] = build_suggestions(state)
            except Exception:
                pass
            try:
                key = make_dataask_cache_key(
                    data_source_id=ds_id, question=q, execute=True,
                    user_key=_user_key(user),
                )
                await cache_set_json(key, result, ttl=PREWARM_TTL)
                done += 1
            except Exception:
                continue
            await asyncio.sleep(0.2)
        await db.rollback()  # 预热只读不落库；回滚可能的快照残留
    return done


async def prewarm_once() -> dict:
    """跑一轮预热（对间并行）。返回统计（供日志/测试）。"""
    pairs = await _active_pairs()
    sem = asyncio.Semaphore(PREWARM_CONCURRENCY)
    detail: list[str] = []
    lock = asyncio.Lock()

    async def one(uid: str, ds_id: str) -> None:
        async with sem:
            # 历史问题限 8 条（最可能再问），其余配额给标准问法（今天/昨天/上周 × 全指标）
            questions = _dedupe(
                (await _recent_questions(uid, ds_id))[:8] + _standard_questions()
            )[:PREWARM_MAX_Q]
            if not questions:
                return
            async with AsyncSessionLocal() as db:
                user = await db.get(User, uid)
            if user is None:
                return
            try:
                done = await _prewarm_pair(user, ds_id, questions)
            except Exception as exc:
                logger.warning("prewarm_pair_failed ds=%s err=%s", ds_id, str(exc)[:200])
                return
            async with lock:
                detail.append(f"{ds_id[:8]}:{done}/{len(questions)}")

    await asyncio.gather(*(one(uid, ds) for uid, ds in pairs))
    warmed = sum(int(d.split(":")[1].split("/")[0]) for d in detail)
    return {"pairs": len(pairs), "warmed": warmed, "detail": detail}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


async def _prewarm_loop() -> None:
    await asyncio.sleep(30)  # 等服务就绪再开跑
    while True:
        try:
            stats = await prewarm_once()
            logger.info("prewarm_done %s", stats)
        except Exception as exc:
            logger.warning("prewarm_failed err=%s", str(exc)[:300])
        await asyncio.sleep(PREWARM_INTERVAL)


def start_prewarm_engine() -> None:
    """main.py lifespan 调用；失败不影响主服务。"""
    if not PREWARM_ENABLED:
        logger.info("prewarm_disabled")
        return
    asyncio.create_task(_prewarm_loop())
    logger.info("prewarm_started interval=%s", PREWARM_INTERVAL)
