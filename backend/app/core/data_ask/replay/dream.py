"""P2-E 做梦式候选生成（Dream-RSI 移植）：LLM 离线批量产策略变体 → 冻结重放零成本打分。

与 P0-C knob-sweep（人工网格）互补：本模块让 LLM 当「策略提议者」，在 knob 策略空间里
提出 N 个变体（一次 LLM 调用），随后全部在 P0-B 冻结语料上确定性重放打分（零 LLM），
只有支配基线的重放赢家才被推荐 apply——复刻「生成 N 个候选只真跑赢家」的成本曲线：
本周期成本 = 1 次 LLM 提议调用 + 0 次真跑评测。

策略空间 = 六个 policy knob（P0-C 参数化）：memory_min_score / memory_top_k /
memory_strong_score / clarify_metric_min / clarify_vague_time_enabled /
clarify_relative_time_exempt。LLM 只提议参数组合，不触碰 prompt 与代码（机制三：
经验经由机制生效，不硬塞提示词）。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.core.data_ask.replay.sweep import _pareto_front, _recommend
from app.core.data_ask.replay.strategies import replay_clarify, replay_memory

logger = logging.getLogger("ds_dream")

# 策略空间（提议者可见的合法取值域；越界值被 _clamp_knobs 收敛）
STRATEGY_SPACE: dict[str, dict[str, Any]] = {
    "memory_min_score": {"type": "float", "min": 0.2, "max": 1.0},
    "memory_top_k": {"type": "int", "min": 1, "max": 5},
    "memory_strong_score": {"type": "float", "min": 0.5, "max": 0.99},
    "clarify_metric_min": {"type": "int", "min": 1, "max": 3},
    "clarify_vague_time_enabled": {"type": "bool"},
    "clarify_relative_time_exempt": {"type": "bool"},
}

BASELINE_KNOBS: dict[str, Any] = {
    "memory_min_score": 0.35,
    "memory_top_k": 3,
    "memory_strong_score": 0.85,
    "clarify_metric_min": 2,
    "clarify_vague_time_enabled": True,
    "clarify_relative_time_exempt": True,
}


def _clamp_knobs(raw: Any) -> dict[str, Any] | None:
    """把 LLM 提议的 knobs 收敛到策略空间；完全非法返回 None。"""
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    for name, spec in STRATEGY_SPACE.items():
        if name not in raw:
            continue
        v = raw[name]
        try:
            if spec["type"] == "bool":
                out[name] = bool(v)
            elif spec["type"] == "int":
                out[name] = int(max(spec["min"], min(spec["max"], int(v))))
            else:
                out[name] = float(max(spec["min"], min(spec["max"], float(v))))
        except (TypeError, ValueError):
            continue
    return out or None


def _mean(vals: list[float | None]) -> float | None:
    xs = [v for v in vals if v is not None]
    return sum(xs) / len(xs) if xs else None


def score_variant(
    corpus: dict[str, Any],
    *,
    tables: list[dict[str, Any]] | None,
    semantic: dict[str, Any] | None,
    knobs: dict[str, Any],
) -> dict[str, Any] | None:
    """一个 knob 组合的零 LLM 重放打分（P0-B 语料）。金标自召回非 1.0 直接出局。"""
    mem = replay_memory(
        corpus,
        min_score=float(knobs.get("memory_min_score", BASELINE_KNOBS["memory_min_score"])),
        top_k=int(knobs.get("memory_top_k", BASELINE_KNOBS["memory_top_k"])),
    )
    recall = mem["golden_self_recall"]["rate"]
    gate_ok = recall is None or recall >= 1.0 - 1e-9
    if not gate_ok:
        return None
    clar = replay_clarify(
        corpus, tables=tables, semantic=semantic,
        metric_min=int(knobs.get("clarify_metric_min", BASELINE_KNOBS["clarify_metric_min"])),
        vague_time_enabled=bool(knobs.get(
            "clarify_vague_time_enabled", BASELINE_KNOBS["clarify_vague_time_enabled"])),
        relative_time_exempt=bool(knobs.get(
            "clarify_relative_time_exempt", BASELINE_KNOBS["clarify_relative_time_exempt"])),
    )
    repair = mem["correction_repairable"]["rate"]
    hit = mem["coverage"]["policy_hit_rate"]
    agree = clar.get("agreement_rate")
    total = clar.get("total") or 0
    fp_rate = (clar.get("false_positive") or 0) / total if total else None
    attainment = _mean([repair, agree])
    cost = _mean([hit, fp_rate])
    return {
        "attainment": round(attainment, 6) if attainment is not None else None,
        "cost": round(cost, 6) if cost is not None else None,
        "parts": {
            "memory_repair": repair, "memory_hit": hit,
            "clarify_agreement": agree, "clarify_fp_rate": fp_rate,
            "self_recall": recall,
        },
    }


def _propose_prompt(n_variants: int, context: dict[str, Any]) -> tuple[str, str]:
    space_desc = "\n".join(
        f"- {k}：{v['type']}" + (f"，取值 [{v['min']}, {v['max']}]" if "min" in v else "，true/false")
        for k, v in STRATEGY_SPACE.items()
    )
    system = (
        "你是问数智能体策略调优的提议者。平台已有 6 个可调策略参数（policy knobs），"
        "你需要在历史语料的重放指标基础上，提出与基线不同、有明确理由的参数组合变体。\n"
        "规则：\n"
        "1. 只输出 JSON 数组，不要输出其他文字；\n"
        "2. 每个变体形如 {\"name\": \"...\", \"rationale\": \"...\", \"knobs\": {<部分或全部参数>}}；\n"
        "3. knobs 至少有一个参数与基线不同；变体之间必须方向不同（不要交出同质变体）；\n"
        "4. 参数取值必须在给定范围内；不确定就少改参数，保守优先。\n"
        f"参数空间：\n{space_desc}"
    )
    user = json.dumps(context, ensure_ascii=False, indent=1, default=str)
    return system, user


async def propose_variants(
    db: Any,
    *,
    n_variants: int = 6,
    context: dict[str, Any],
    llm_provider: str | None = None,
    llm_model: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """一次 LLM 调用产出 N 个策略变体（解析失败/非法项丢弃，不重试）。"""
    from langchain_core.messages import HumanMessage, SystemMessage
    from app.models_hub.router import ModelRouter

    system, user = _propose_prompt(n_variants, context)
    llm = await ModelRouter.get_llm(
        db=db, provider=llm_provider, model=llm_model, user_id=user_id,
        response_style="precise",
    )
    resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("dream_propose_parse_failed len=%s", len(text))
        return []
    if not isinstance(items, list):
        return []

    seen: list[str] = []
    variants: list[dict[str, Any]] = []
    for raw in items[: max(n_variants * 2, 12)]:
        if not isinstance(raw, dict):
            continue
        knobs = _clamp_knobs(raw.get("knobs"))
        if knobs is None:
            continue
        diff = {k: v for k, v in knobs.items() if v != BASELINE_KNOBS.get(k)}
        if not diff:
            continue
        name = str(raw.get("name") or "").strip()[:60] or f"变体{len(variants) + 1}"
        sig = json.dumps(knobs, sort_keys=True, default=str)
        if sig in seen:
            continue
        seen.append(sig)
        variants.append({
            "name": name,
            "rationale": str(raw.get("rationale") or "")[:300],
            "knobs": {**BASELINE_KNOBS, **knobs},
            "diff": diff,
        })
        if len(variants) >= n_variants:
            break
    return variants


async def run_dream_cycle(
    db: Any,
    *,
    data_source_id: str,
    n_variants: int = 6,
    limit: int = 500,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """完整做梦周期：冻结语料 → LLM 提议 N 变体 → 零 LLM 重放打分 → 前沿 + 推荐赢家。"""
    from app.core.data_ask.replay.corpus import build_replay_corpus
    from app.core.data_ask.service import load_source_context

    corpus = await build_replay_corpus(db, data_source_id=data_source_id, limit=limit)
    _, table_meta, semantic, _, _ = await load_source_context(db, data_source_id)

    base_score = score_variant(corpus, tables=table_meta, semantic=semantic, knobs=BASELINE_KNOBS)
    baseline = {
        "name": "baseline", "knobs": dict(BASELINE_KNOBS), "diff": {},
        "is_baseline": True, **(base_score or {}),
    }

    variants = await propose_variants(
        db, n_variants=n_variants,
        context={
            "data_source_id": data_source_id,
            "corpus_stats": corpus.get("stats"),
            "baseline_knobs": BASELINE_KNOBS,
            "baseline_scores": (base_score or {}).get("parts"),
            "note": "attainment 越大越好（纠正可修复率与反问一致率的均值），cost 越小越好（记忆命中率与误反问率的均值）",
        },
        llm_provider=llm_provider, llm_model=llm_model, user_id=user_id,
    )

    points: list[dict[str, Any]] = [baseline]
    for v in variants:
        s = score_variant(corpus, tables=table_meta, semantic=semantic, knobs=v["knobs"])
        if s is None:
            v["gate_failed"] = True
            continue
        points.append({"name": v["name"], "knobs": v["knobs"], "diff": v["diff"],
                       "rationale": v["rationale"], **s})

    front = _pareto_front(points)
    winner = _recommend(front, baseline)
    return {
        "data_source_id": str(data_source_id),
        "cost": {"llm_calls": 1, "real_runs": 0,
                 "note": "1 次 LLM 提议调用 + 0 次真跑评测（重放全零成本）"},
        "corpus_stats": corpus.get("stats"),
        "baseline": baseline,
        "variants": points[1:],
        "frontier": [
            {"name": p["name"], "attainment": p.get("attainment"), "cost": p.get("cost")}
            for p in front
        ],
        "recommended": winner,
    }
