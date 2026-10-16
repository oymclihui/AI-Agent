"""P0-C 记忆先验分档：策略 knob 网格扫 + 质量↔干预度前沿挑选（零 LLM）。

方法（移植 DREAM-RSI β-sweep 思想）：
- memory：扫 (min_score × top_k)。attainment = correction_repairable.rate
  （记忆的核心价值：纠正过的提问能否被记忆直接修复）；干预度 = coverage.policy_hit_rate
  （历史问题被记忆命中的比例，越高 prompt 干预越强、过拟合风险越大）。
  硬性门槛：golden_self_recall 必须 1.0（检索链路完好），否则该组出局。
- clarify：扫 (metric_min × vague_time_enabled × relative_time_exempt)。
  attainment = agreement_rate（与历史实际判定的一致率，分时期口径由调用方切分）；
  干预度 = false_positive_rate（当时成功作答却被反问的打扰率）。
- 前沿：Pareto 非支配点集；推荐规则 = 干预度不高于基线的前提下 attainment 最高点，
  无更高 attainment 则保守推荐基线（永不倒退）。
"""
from __future__ import annotations

from typing import Any

from app.core.data_ask.replay.strategies import replay_clarify, replay_memory

# 与线上硬默认一致（service._DEFAULT_POLICY_KNOBS）
BASELINE_MEMORY = {"min_score": 0.35, "top_k": 3}
BASELINE_CLARIFY = {"metric_min": 2, "vague_time_enabled": True, "relative_time_exempt": True}

DEFAULT_MEMORY_GRID = {
    "min_scores": [0.2, 0.35, 0.5, 0.7, 1.0],
    "top_ks": [2, 3, 5],
}
DEFAULT_CLARIFY_GRID = {
    "metric_mins": [1, 2, 3],
    "vague_time_enabled": [True, False],
    "relative_time_exempt": [True, False],
}


def _pareto_front(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """非支配筛选：attainment 越大越好、cost 越小越好；attainment 为 None 的点不参与。"""
    valid = [p for p in points if p.get("attainment") is not None and p.get("cost") is not None]
    front: list[dict[str, Any]] = []
    for p in valid:
        dominated = any(
            q is not p
            and q["attainment"] >= p["attainment"] - 1e-9
            and q["cost"] <= p["cost"] + 1e-9
            and (q["attainment"] > p["attainment"] + 1e-9 or q["cost"] < p["cost"] - 1e-9)
            for q in valid
        )
        if not dominated:
            front.append(p)
    front.sort(key=lambda p: (-p["attainment"], p["cost"]))
    return front


def _recommend(
    front: list[dict[str, Any]], baseline: dict[str, Any] | None
) -> dict[str, Any] | None:
    """推荐：干预度不高于基线（容差 1e-9）且 attainment 严格最高的前沿点；
    无优于基线的点时返回 None（调用方保守保留基线）。"""
    if baseline is None or baseline.get("attainment") is None:
        return front[0] if front else None
    base_cost = baseline.get("cost")
    base_att = baseline["attainment"]
    best: dict[str, Any] | None = None
    for p in front:
        if base_cost is not None and p["cost"] > base_cost + 1e-9:
            continue
        if p["attainment"] > base_att + 1e-9:
            if best is None or p["attainment"] > best["attainment"]:
                best = p
    return best


def sweep_memory(
    corpus: dict[str, Any],
    *,
    min_scores: list[float] | None = None,
    top_ks: list[int] | None = None,
) -> dict[str, Any]:
    """memory knob 网格扫：每组跑 replay_memory，产出 (attainment, cost) 点 + 前沿 + 推荐。"""
    min_scores = min_scores or list(DEFAULT_MEMORY_GRID["min_scores"])
    top_ks = top_ks or list(DEFAULT_MEMORY_GRID["top_ks"])
    points: list[dict[str, Any]] = []
    for ms in min_scores:
        for tk in top_ks:
            rep = replay_memory(corpus, min_score=float(ms), top_k=int(tk))
            recall = rep["golden_self_recall"]["rate"]
            repair = rep["correction_repairable"]["rate"]
            coverage = rep["coverage"]["policy_hit_rate"]
            no_hit = rep["like_regression_risk"]["no_hit"]
            pt = {
                "knobs": {"memory_min_score": float(ms), "memory_top_k": int(tk)},
                # 检索链路门槛：金标自召回非 1.0 说明打分/链路异常，直接出局
                "gate_ok": recall is None or recall >= 1.0 - 1e-9,
                "attainment": repair,          # 纠正可修复率（None=无 correction 样本）
                "cost": coverage,              # 记忆命中率（干预度）
                "like_regression_no_hit": no_hit,
                "self_recall": recall,
                "is_baseline": float(ms) == BASELINE_MEMORY["min_score"] and int(tk) == BASELINE_MEMORY["top_k"],
            }
            points.append(pt)
    eligible = [p for p in points if p["gate_ok"]]
    front = _pareto_front(eligible)
    baseline = next((p for p in eligible if p["is_baseline"]), None)
    rec = _recommend(front, baseline)
    return {
        "baseline": BASELINE_MEMORY,
        "grid_size": len(points),
        "points": points,
        "frontier": front,
        "recommended": rec["knobs"] if rec else None,
        "recommend_reason": (
            f"可修复率 {rec['attainment']} 高于基线 {baseline['attainment']} 且干预度不升"
            if rec and baseline and baseline.get("attainment") is not None
            else ("基线已是最优（无更高可修复率的操作点），保守保留" if baseline else "基线不在合格点集内")
        ),
    }


def sweep_clarify(
    corpus: dict[str, Any],
    *,
    tables: list[dict[str, Any]] | None,
    semantic: dict[str, Any] | None,
    metric_mins: list[int] | None = None,
    vague_opts: list[bool] | None = None,
    exempt_opts: list[bool] | None = None,
) -> dict[str, Any]:
    """clarify knob 网格扫：attainment=与历史判定一致率，cost=误反问打扰率。"""
    metric_mins = metric_mins or list(DEFAULT_CLARIFY_GRID["metric_mins"])
    vague_opts = vague_opts or list(DEFAULT_CLARIFY_GRID["vague_time_enabled"])
    exempt_opts = exempt_opts or list(DEFAULT_CLARIFY_GRID["relative_time_exempt"])
    points: list[dict[str, Any]] = []
    for mm in metric_mins:
        for vt in vague_opts:
            for ex in exempt_opts:
                rep = replay_clarify(
                    corpus, tables=tables, semantic=semantic,
                    metric_min=int(mm), vague_time_enabled=bool(vt),
                    relative_time_exempt=bool(ex),
                )
                total = rep["total"] or 0
                fp = rep["false_positive"]
                pt = {
                    "knobs": {
                        "clarify_metric_min": int(mm),
                        "clarify_vague_time_enabled": bool(vt),
                        "clarify_relative_time_exempt": bool(ex),
                    },
                    "gate_ok": True,
                    "attainment": rep["agreement_rate"],
                    "cost": round(fp / total, 4) if total else None,
                    "false_positive": fp,
                    "false_negative": rep["false_negative"],
                    "is_baseline": (
                        int(mm) == BASELINE_CLARIFY["metric_min"]
                        and bool(vt) == BASELINE_CLARIFY["vague_time_enabled"]
                        and bool(ex) == BASELINE_CLARIFY["relative_time_exempt"]
                    ),
                }
                points.append(pt)
    front = _pareto_front(points)
    baseline = next((p for p in points if p["is_baseline"]), None)
    rec = _recommend(front, baseline)
    return {
        "baseline": BASELINE_CLARIFY,
        "grid_size": len(points),
        "points": points,
        "frontier": front,
        "recommended": rec["knobs"] if rec else None,
        "recommend_reason": (
            f"一致率 {rec['attainment']} 高于基线 {baseline['attainment']} 且误反问率不升"
            if rec and baseline and baseline.get("attainment") is not None
            else ("基线已是最优（无更高一致率的操作点），保守保留" if baseline else "基线不在点集内")
        ),
    }


async def run_knob_sweep(
    db,
    *,
    data_source_id: str,
    limit: int = 500,
    grid: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """数据源级 knob 网格扫：构建重放语料 → memory + clarify 双扫 → 前沿与推荐。"""
    from app.core.data_ask.replay.corpus import build_replay_corpus
    from app.core.data_ask.service import load_source_context

    corpus = await build_replay_corpus(db, data_source_id=data_source_id, limit=limit)
    _, table_meta, semantic, _perm, _edges = await load_source_context(db, data_source_id)
    grid = grid or {}
    mem_grid = grid.get("memory") or {}
    cla_grid = grid.get("clarify") or {}
    memory = sweep_memory(
        corpus,
        min_scores=mem_grid.get("min_scores"),
        top_ks=mem_grid.get("top_ks"),
    )
    clarify = sweep_clarify(
        corpus, tables=table_meta, semantic=semantic,
        metric_mins=cla_grid.get("metric_mins"),
        vague_opts=cla_grid.get("vague_time_enabled"),
        exempt_opts=cla_grid.get("relative_time_exempt"),
    )
    return {
        "data_source_id": data_source_id,
        "corpus_stats": corpus["stats"],
        "memory": memory,
        "clarify": clarify,
    }
