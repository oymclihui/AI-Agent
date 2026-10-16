"""模拟器精确性自校验：重放结论必须与库内当时实测一致。

回测对象：v15→v16（→v17）版本时期边界取自 agent_version.created_at，
把历史轨迹按时期切分，用现行确定性策略逐时期重放，与库内记录
（clarification 标志、success 标志、金标召回）逐条比对：
- guard：历史成功 SQL 重放现行守门必须全部放行（误杀率 = 0）；
- clarify：重放判定与库内 clarification 标志逐时期一致率；
- memory：金标自检索必须命中自身（打分精确路径）。
任何不一致逐条列出，不构造、不填充（数据真实性红线）。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.replay.corpus import build_replay_corpus
from app.core.data_ask.replay.strategies import replay_clarify, replay_guard, replay_memory
from app.db.models import AgentVersion, DataSource

logger = logging.getLogger("ds_replay_selfcheck")


async def _era_boundaries(db: AsyncSession, agent_id: str | None) -> list[dict[str, Any]]:
    """绑定智能体的版本时间线（升序）：[{version, created_at}]。"""
    if not agent_id:
        return []
    rows = (
        await db.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == str(agent_id))
            .order_by(AgentVersion.version.asc())
        )
    ).scalars().all()
    return [{"version": int(v.version), "created_at": v.created_at} for v in rows]


def _era_of(created_at: Any, boundaries: list[dict[str, Any]]) -> str:
    label = "before-v1"
    for b in boundaries:
        if created_at is not None and b["created_at"] is not None and created_at >= b["created_at"]:
            label = f"v{b['version']}"
    return label


async def run_selfcheck(db: AsyncSession, *, data_source_id: str, limit: int = 500) -> dict[str, Any]:
    from app.core.data_ask.service import load_source_context

    source = await db.get(DataSource, str(data_source_id))
    if source is None:
        return {"ok": False, "error": "数据源不存在"}
    _, table_meta, semantic, _perm, _edges = await load_source_context(db, str(source.id))
    allowed_tables = {t["table_name"] for t in table_meta}
    dialect = str(source.driver) if source.driver else None

    corpus = await build_replay_corpus(db, data_source_id=str(source.id), limit=limit)
    traces = corpus["traces"]

    # ── 检查 1：sql_guard 重放（现行守门，历史成功 SQL 零误杀）──
    guard = replay_guard(corpus, baseline_allowed_tables=allowed_tables, dialect=dialect)

    # ── 检查 2：clarify 重放（现行阈值 vs 库内实际）──
    clarify = replay_clarify(corpus, tables=table_meta, semantic=semantic)

    # ── 检查 3：memory 重放（现行策略：threshold 0.35 / top_k 3）──
    memory = replay_memory(corpus, min_score=0.35, top_k=3)

    # ── 时期回测：v15→v16（→v17）逐时期重放一致性 ──
    boundaries = await _era_boundaries(db, source.agent_id)
    eras: dict[str, dict[str, int]] = {}
    for t in traces:
        era = _era_of(t["created_at"], boundaries)
        slot = eras.setdefault(era, {"total": 0, "clarify_agree": 0, "clarify_actual": 0, "clarify_pred": 0, "false_kill": 0, "sql_total": 0})
        slot["total"] += 1
        pred = None
        if t["question"]:
            from app.core.data_ask.replay.strategies import clarify_decision

            pred = clarify_decision(t["question"], table_meta, semantic)
        if bool(pred) == t["clarification"]:
            slot["clarify_agree"] += 1
        slot["clarify_actual"] += 1 if t["clarification"] else 0
        slot["clarify_pred"] += 1 if pred else 0
        if t["sql_text"]:
            slot["sql_total"] += 1

    era_report = []
    for era, s in sorted(eras.items()):
        era_report.append({
            "era": era,
            "traces": s["total"],
            "clarify_agreement": round(s["clarify_agree"] / s["total"], 4) if s["total"] else None,
            "clarify_actual": s["clarify_actual"],
            "clarify_predicted": s["clarify_pred"],
            "sql_total": s["sql_total"],
        })

    checks = [
        {
            "name": "guard_zero_false_kill",
            "desc": "历史成功 SQL 重放现行守门零误杀",
            "value": guard["false_kill_rate"],
            "expect": 0.0,
            "pass": guard["false_kill_rate"] == 0.0,
            "detail": {"total": guard["total"], "false_kills": guard["false_kills"]},
        },
        {
            "name": "memory_golden_self_recall",
            "desc": "金标自检索命中自身（打分精确路径）",
            "value": memory["golden_self_recall"]["rate"],
            "expect": 1.0,
            "pass": memory["golden_self_recall"]["rate"] == 1.0,
            "detail": memory["golden_self_recall"],
        },
        {
            "name": "clarify_era_agreement",
            "desc": "clarify 重放与各时期库内实测一致率（最低时期 ≥ 0.80）",
            "value": min((e["clarify_agreement"] for e in era_report if e["clarify_agreement"] is not None), default=None),
            "expect": ">= 0.80",
            "pass": bool(era_report) and all(
                (e["clarify_agreement"] is None) or (e["clarify_agreement"] >= 0.80) for e in era_report
            ),
            "detail": era_report,
        },
    ]
    ok = all(c["pass"] for c in checks)
    report = {
        "ok": ok,
        "data_source_id": str(source.id),
        "data_source_name": source.name,
        "corpus_stats": corpus["stats"],
        "agent_bound": bool(source.agent_id),
        "era_boundaries": [
            {"version": b["version"], "created_at": str(b["created_at"])} for b in boundaries
        ],
        "checks": checks,
        "guard": {k: guard[k] for k in ("total", "baseline_blocked", "variant_blocked", "false_kills", "false_kill_rate")},
        "clarify": {k: clarify[k] for k in ("total", "predicted_clarify", "actual_clarify", "agreement_rate", "false_positive", "false_negative")},
        "memory": memory,
        "era_report": era_report,
    }
    logger.info("replay_selfcheck ds=%s ok=%s corpus=%s", source.id, ok, corpus["stats"])
    return report
