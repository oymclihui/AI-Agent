"""P0-B 重放模拟器 API：确定性策略零 LLM 离线评估。

- POST /data-sources/{sid}/replay/selfcheck  模拟器精确性自校验（v15→v16 时期回测）
- POST /data-sources/{sid}/replay/guard      sql_guard 变体重放（误杀率/拦截差异）
- POST /data-sources/{sid}/replay/memory     记忆选择策略重放（采纳/可修复率）
- POST /data-sources/{sid}/replay/clarify    clarify 阈值重放（误反问/漏反问）
全部为只读评估：不写 ask_trace / 不改任何配置，写操作需数据源 manage 权限。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_user
from app.core.data_ask.govern.access import assert_data_source_access
from app.core.data_ask.replay.corpus import build_replay_corpus
from app.core.data_ask.replay.selfcheck import run_selfcheck
from app.core.data_ask.replay.strategies import (
    replay_clarify,
    replay_guard,
    replay_memory,
    replay_memory_tier,
)
from app.db.models import DataSource, User
from app.db.session import get_db

router = APIRouter(tags=["DsReplay"])


async def _get_source(db: AsyncSession, sid: str) -> DataSource:
    source = await db.get(DataSource, sid)
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return source


async def _context(db: AsyncSession, source: DataSource) -> tuple[set[str], str | None, list[dict[str, Any]], dict[str, Any] | None]:
    from app.core.data_ask.service import load_source_context

    _, table_meta, semantic, _perm, _edges = await load_source_context(db, str(source.id))
    allowed = {t["table_name"] for t in table_meta}
    dialect = str(source.driver) if source.driver else None
    return allowed, dialect, table_meta, semantic


class GuardVariantIn(BaseModel):
    allowed_tables: list[str] | None = Field(default=None, description="变体白名单；空=沿用数据源全表")
    dialect: str | None = Field(default=None, description="变体方言；空=沿用 source.driver")
    limit: int = Field(default=500, ge=1, le=2000)


@router.post("/data-sources/{sid}/replay/guard")
async def replay_guard_api(
    sid: str,
    payload: GuardVariantIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    allowed, dialect, _meta, _semantic = await _context(db, source)
    corpus = await build_replay_corpus(db, data_source_id=str(source.id), limit=payload.limit)
    variant_tables = {t.strip() for t in (payload.allowed_tables or []) if t.strip()} or allowed
    report = replay_guard(
        corpus,
        baseline_allowed_tables=allowed, dialect=dialect,
        variant_allowed_tables=variant_tables,
        variant_dialect=payload.dialect,
    )
    report["corpus_stats"] = corpus["stats"]
    return report


class MemoryPolicyIn(BaseModel):
    min_score: float = Field(default=0.35, ge=0.0, le=10.0)
    top_k: int = Field(default=3, ge=1, le=20)
    limit: int = Field(default=500, ge=1, le=2000)


@router.post("/data-sources/{sid}/replay/memory")
async def replay_memory_api(
    sid: str,
    payload: MemoryPolicyIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    corpus = await build_replay_corpus(db, data_source_id=str(source.id), limit=payload.limit)
    report = replay_memory(corpus, min_score=payload.min_score, top_k=payload.top_k)
    report["corpus_stats"] = corpus["stats"]
    return report


class ClarifyPolicyIn(BaseModel):
    metric_min: int = Field(default=2, ge=1, le=10)
    vague_time_enabled: bool = True
    relative_time_exempt: bool = True
    limit: int = Field(default=500, ge=1, le=2000)


@router.post("/data-sources/{sid}/replay/clarify")
async def replay_clarify_api(
    sid: str,
    payload: ClarifyPolicyIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    _allowed, _dialect, table_meta, semantic = await _context(db, source)
    corpus = await build_replay_corpus(db, data_source_id=str(source.id), limit=payload.limit)
    report = replay_clarify(
        corpus, tables=table_meta, semantic=semantic,
        metric_min=payload.metric_min,
        vague_time_enabled=payload.vague_time_enabled,
        relative_time_exempt=payload.relative_time_exempt,
    )
    report["corpus_stats"] = corpus["stats"]
    return report


class MemoryTierIn(BaseModel):
    min_score: float = Field(default=0.35, ge=0.0, le=10.0)
    top_k: int = Field(default=3, ge=1, le=20)
    strong_scores: list[float] | None = Field(default=None, description="自定义 τ 网格；空=默认网格")
    limit: int = Field(default=500, ge=1, le=2000)
    apply: bool = Field(default=False, description="true=把推荐阈值固化到 metadata.policy_knobs.memory_strong_score")


@router.post("/data-sources/{sid}/replay/memory-tier")
async def replay_memory_tier_api(
    sid: str,
    payload: MemoryTierIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """P1-C 记忆分档阈值重放（零 LLM）：选「强沿用档零误伤且覆盖最大」的 τ。

    apply=true 且有推荐时写入数据源 metadata.policy_knobs.memory_strong_score
    （线上读取优先级：spec_override > metadata.policy_knobs > 硬默认 0.85）。
    """
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    corpus = await build_replay_corpus(db, data_source_id=str(source.id), limit=payload.limit)
    report = replay_memory_tier(
        corpus,
        min_score=payload.min_score,
        top_k=payload.top_k,
        strong_scores=payload.strong_scores,
    )
    report["corpus_stats"] = corpus["stats"]
    if payload.apply:
        rec = report.get("recommended")
        if rec:
            meta = dict(getattr(source, "metadata_", None) or {})
            knobs = dict(meta.get("policy_knobs") or {})
            knobs.update(rec)
            meta["policy_knobs"] = knobs
            source.metadata_ = meta
            await db.commit()
            report["applied"] = rec
        else:
            report["applied"] = None
            report["apply_note"] = "无零误伤阈值推荐，未改动配置"
    return report


class TreeBackfillIn(BaseModel):
    limit: int = Field(default=500, ge=1, le=2000)


@router.post("/data-sources/{sid}/replay/tree-backfill")
async def replay_tree_backfill_api(
    sid: str,
    payload: TreeBackfillIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """P1-D：存量 ask_trace 离线回填成发现树（root + result，已回填自动跳过）。"""
    from app.core.data_ask.tree import backfill_ask_tree

    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    return await backfill_ask_tree(db, data_source_id=str(source.id), limit=payload.limit)


@router.get("/data-sources/{sid}/replay/tree/{trace_id}")
async def replay_tree_get_api(
    sid: str,
    trace_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """P1-D：按 trace_id 查看发现树节点（root/intent/candidate/execution/result）。"""
    from app.core.data_ask.tree import get_ask_tree

    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    tree = await get_ask_tree(db, data_source_id=str(source.id), trace_id=trace_id)
    if tree is None:
        raise HTTPException(status_code=404, detail="轨迹不存在")
    return tree


class DreamIn(BaseModel):
    n_variants: int = Field(default=6, ge=1, le=12)
    limit: int = Field(default=500, ge=1, le=2000)
    apply: bool = Field(default=False, description="true=把重放赢家 knobs 固化到 metadata.policy_knobs")


@router.post("/data-sources/{sid}/replay/dream")
async def replay_dream_api(
    sid: str,
    payload: DreamIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """P2-E 做梦式候选生成：1 次 LLM 提议 N 个策略变体 + 冻结语料零 LLM 重放打分。

    只有支配基线的重放赢家才被推荐；apply=true 时把赢家 knobs 合并进
    metadata.policy_knobs（与 knob-sweep apply 同语义），无赢家则不动配置。
    """
    from app.core.data_ask.replay.dream import run_dream_cycle

    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    report = await run_dream_cycle(
        db, data_source_id=str(source.id), n_variants=payload.n_variants,
        limit=payload.limit, user_id=str(user.id) if user else None,
    )
    if payload.apply:
        rec = report.get("recommended")
        if rec and rec.get("name") != "baseline":
            meta = dict(getattr(source, "metadata_", None) or {})
            knobs = dict(meta.get("policy_knobs") or {})
            knobs.update(rec.get("knobs") or {})
            meta["policy_knobs"] = knobs
            source.metadata_ = meta
            await db.commit()
            report["applied"] = rec.get("knobs")
        else:
            report["applied"] = None
            report["apply_note"] = "无支配基线的重放赢家，未改动配置"
    return report


@router.post("/data-sources/{sid}/replay/selfcheck")
async def replay_selfcheck_api(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    return await run_selfcheck(db, data_source_id=str(source.id))


class KnobSweepIn(BaseModel):
    limit: int = Field(default=500, ge=1, le=2000)
    grid: dict[str, Any] | None = Field(default=None, description="自定义网格覆盖；空=默认网格")
    apply: bool = Field(default=False, description="true=把推荐操作点固化到 source.metadata.policy_knobs")


@router.post("/data-sources/{sid}/replay/knob-sweep")
async def replay_knob_sweep_api(
    sid: str,
    payload: KnobSweepIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """P0-C 记忆先验分档：memory/clarify knob 网格扫 + 前沿推荐（零 LLM）。

    apply=true 时把推荐操作点写入数据源 metadata.policy_knobs（线上读取优先级：
    spec_override > metadata.policy_knobs > 硬默认）；无推荐（基线已最优）时不写。
    """
    from app.core.data_ask.replay.sweep import run_knob_sweep

    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    report = await run_knob_sweep(
        db, data_source_id=str(source.id), limit=payload.limit, grid=payload.grid,
    )
    if payload.apply:
        applied: dict[str, Any] = {}
        for part in ("memory", "clarify"):
            rec = report[part].get("recommended")
            if rec:
                applied.update(rec)
        if applied:
            meta = dict(getattr(source, "metadata_", None) or {})
            knobs = dict(meta.get("policy_knobs") or {})
            knobs.update(applied)
            meta["policy_knobs"] = knobs
            source.metadata_ = meta
            await db.commit()
            report["applied"] = applied
        else:
            report["applied"] = None
            report["apply_note"] = "无更优操作点（基线已最优），未改动配置"
    return report
