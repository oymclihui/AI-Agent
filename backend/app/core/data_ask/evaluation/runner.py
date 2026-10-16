"""回归评估执行器：逐题问数 → 签名比对 → LLM judge → 指标汇总。

数据真实性红线：
- 直接调底层 _run_data_ask_impl（绕过 ask_trace 写入），评估流量绝不污染真实交互信号。
- consistency 三级：exact（一致）/ baseline（首轮建基线，不罚不奖）/ mismatch（退化）。
  基线必须来自同一执行路径才可比：trace 来源签名首轮不一致时刷新为评估基线。
- judge 失败不计分；overall 按实际可用指标加权归一，绝不用假数据填充。
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.evaluation.judge import judge_answer
from app.db.models import AgentEvalRun, AgentEvalSet, AgentQualityScore, DataSource

logger = logging.getLogger("agent_eval_runner")

PROMOTE_SQL_SUCCESS = 0.90
PROMOTE_CONSISTENCY = 0.85
MIN_EVAL_SET = 5
JUDGE_PASS_SCORE = 6.0


def signature_of(columns: Any, row_count: Any, rows: Any) -> str | None:
    """与 data_ask.service 写 ask_trace 完全一致的签名算法（保证可比性）。"""
    cols = columns or []
    if not cols:
        return None
    payload = {"c": [str(c) for c in cols], "n": row_count, "h": (rows or [])[:5]}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()[:32]


async def _ask_once(db: AsyncSession, data_source_id: str, question: str, spec_override: dict[str, Any] | None = None) -> dict[str, Any]:
    """评估专用问数：调底层实现，不写 ask_trace，不触碰交互缓存。

    spec_override：候选版本 spec（P0-A 双候选）。仅影响 goal/backstory/模型选择，
    绝不改动线上 Agent 记录。
    """
    from app.core.data_ask.service import _run_data_ask_impl

    return await _run_data_ask_impl(
        db,
        data_source_id=data_source_id,
        question=question,
        user=None,
        trace_marks={},
        execute=True,
        bypass_row_perm=True,
        spec_override=spec_override,
    )


def _chart_type(chart: Any) -> str | None:
    if isinstance(chart, dict):
        t = chart.get("type")
        return str(t) if t else None
    return None


def _item_score(item: dict[str, Any]) -> float | None:
    """逐题归一化质量分 ∈[0,1]，权重口径与 run 级 overall 一致（0.4/0.4/0.2）。

    consistency 为 None（基线只读跑不可比 / 首轮未建基线）时该项不参与加权，
    与 run 级「按实际可用指标加权归一」规则同构——绝不填假分。
    """
    parts: list[tuple[float, float]] = [(0.4, 1.0 if item.get("sql_ok") else 0.0)]
    cons = item.get("consistency")
    if cons == "exact":
        parts.append((0.4, 1.0))
    elif cons == "mismatch":
        parts.append((0.4, 0.0))
    js = item.get("judge_score")
    if js is not None:
        parts.append((0.2, float(js) / 10.0))
    return round(sum(w * v for w, v in parts) / sum(w for w, _ in parts), 4)


async def run_eval_run(
    db: AsyncSession,
    run_row: AgentEvalRun,
    source: DataSource,
    *,
    judge_limit: int = 20,
    item_limit: int = 50,
    spec_override: dict[str, Any] | None = None,
    read_only_baseline: bool = False,
    budget_retries: int | None = None,
    write_quality_score: bool | None = None,
    freeze_episode: bool = True,
    era: str | None = None,
    run_kind: str | None = None,
) -> AgentEvalRun:
    """执行一轮回归评估，结果写入 run_row + AgentQualityScore（flush，不 commit）。

    spec_override：候选版本 spec（P0-A 双候选评测，不触碰线上配置）。
    read_only_baseline：基线跑（0 号候选=当前生产）。只读评估——不回填/刷新
    AgentEvalSet 的签名基线、不写 AgentQualityScore，避免污染真实回归基线与趋势。
    budget_retries：P1-A 预算点——压低 SQL 修复重试上限（注入 spec_override），
    构造质量↔成本前沿上的另一个工作点；None = 线上默认。
    write_quality_score：默认 ``not read_only_baseline``；多预算点的附加跑显式传
    False，避免质量分时序被同一轮多点评测稀释。
    freeze_episode：P1-B——把本轮逐题结果冻结进 data_ask_replay_episode（只追加）。
    era：时期键（同一轮双候选同一 era）；None 时取当日。
    run_kind：baseline / candidate / None（手动评估），冻结时留痕供逐时期门槛筛选。
    """
    ds = str(source.id)
    t0 = time.monotonic()
    run_row.status = "running"
    await db.flush()

    if budget_retries is not None:
        # 预算点注入：与候选 spec 合并，eval 路径专用，绝不写回 Agent 记录
        spec_override = {**(spec_override or {}), "max_sql_retries": int(budget_retries)}

    questions = (
        await db.execute(
            select(AgentEvalSet)
            .where(AgentEvalSet.data_source_id == ds, AgentEvalSet.active.is_(True))
            .order_by(AgentEvalSet.created_at.asc())
            .limit(item_limit)
        )
    ).scalars().all()

    items: list[dict[str, Any]] = []
    judged = 0

    for q in questions:
        item: dict[str, Any] = {
            "qid": q.id,
            "question": q.question,
            "category": q.category or "aggregation",
            "source": q.source,
            "sql_ok": False,
            "consistency": None,
            "judge_score": None,
            "judge_reason": None,
            "chart_match": None,
            "row_count": None,
            "expected_row_count": q.expected_row_count,
            "duration_ms": None,
            "error": None,
        }
        qt0 = time.monotonic()
        try:
            result = await _ask_once(db, ds, q.question, spec_override=spec_override)
            cols = result.get("columns") or []
            rows = result.get("rows") or []
            row_count = result.get("row_count")
            sql = result.get("sql")
            item["sql_ok"] = bool(cols) and not result.get("clarification")
            item["row_count"] = row_count

            sig = signature_of(cols, row_count, rows)
            if sig and item["sql_ok"]:
                if not q.expected_signature:
                    if read_only_baseline:
                        # 基线只读跑：考题尚无签名基线时不回填，留待候选跑建立
                        item["consistency"] = None
                    else:
                        # 首次评估：回填真实基线
                        q.expected_signature = sig
                        q.expected_row_count = row_count
                        q.signature_source = "eval"
                        item["consistency"] = "baseline"
                elif sig == q.expected_signature:
                    item["consistency"] = "exact"
                elif read_only_baseline:
                    # 基线只读跑：trace 基线来自真实用户上下文不可比，仅 eval 基线可比
                    item["consistency"] = "mismatch" if (q.signature_source or "trace") == "eval" else None
                elif (q.signature_source or "trace") == "trace":
                    # trace 基线来自真实用户上下文（权限/记忆不同），首轮不一致刷新为评估基线
                    q.expected_signature = sig
                    q.expected_row_count = row_count
                    q.signature_source = "eval"
                    item["consistency"] = "baseline"
                else:
                    item["consistency"] = "mismatch"

            if q.expected_chart:
                actual = _chart_type(result.get("chart"))
                item["chart_match"] = (actual == q.expected_chart) if actual else False

            if item["sql_ok"] and judged < judge_limit:
                verdict = await judge_answer(
                    db, question=q.question, sql=sql, columns=cols, rows_sample=rows,
                )
                if verdict is not None:
                    judged += 1
                    item["judge_score"] = verdict["score"]
                    item["judge_reason"] = verdict["reason"]
        except Exception as exc:
            item["error"] = str(exc)[:300]
            logger.exception("eval_item_failed run=%s qid=%s err=%s", run_row.id, q.id, str(exc)[:200])
        item["duration_ms"] = int((time.monotonic() - qt0) * 1000)
        items.append(item)

    # ── 指标汇总 ──
    total = len(items)
    sql_ok_n = sum(1 for i in items if i["sql_ok"])
    exact_n = sum(1 for i in items if i["consistency"] == "exact")
    mismatch_n = sum(1 for i in items if i["consistency"] == "mismatch")
    cons_base = exact_n + mismatch_n
    judge_scores = [i["judge_score"] for i in items if i["judge_score"] is not None]
    chart_judged = [i["chart_match"] for i in items if i["chart_match"] is not None]

    sql_rate = round(sql_ok_n / total, 4) if total else None
    cons_rate = round(exact_n / cons_base, 4) if cons_base else None
    judge_rate = round(sum(judge_scores) / len(judge_scores) / 10.0, 4) if judge_scores else None
    chart_rate = round(sum(1 for c in chart_judged if c) / len(chart_judged), 4) if chart_judged else None

    parts: list[tuple[float, float]] = []
    if sql_rate is not None:
        parts.append((0.4, sql_rate))
    if cons_rate is not None:
        parts.append((0.4, cons_rate))
    if judge_rate is not None:
        parts.append((0.2, judge_rate))
    overall = round(sum(w * v for w, v in parts) / sum(w for w, _ in parts), 4) if parts else None

    # 弱项分布：按类目聚合失败（SQL 失败 + 结果退化）
    cat_stat: dict[str, dict[str, int]] = {}
    for i in items:
        st = cat_stat.setdefault(i["category"], {"total": 0, "fails": 0})
        st["total"] += 1
        if not i["sql_ok"] or i["consistency"] == "mismatch":
            st["fails"] += 1
    weak = [
        {"category": c, "total": s["total"], "fails": s["fails"]}
        for c, s in cat_stat.items() if s["fails"] > 0
    ]
    weak.sort(key=lambda x: -x["fails"])

    passed_n = sum(
        1 for i in items
        if i["sql_ok"] and i["consistency"] != "mismatch"
        and (i["judge_score"] is None or i["judge_score"] >= JUDGE_PASS_SCORE)
    )

    run_row.total = total
    run_row.passed = passed_n
    run_row.sql_success_rate = sql_rate
    run_row.consistency_rate = cons_rate
    run_row.judge_score = judge_rate
    run_row.overall_score = overall
    run_row.weak_categories = weak
    run_row.items = items
    run_row.status = "done"
    run_row.duration_ms = int((time.monotonic() - t0) * 1000)

    if freeze_episode:
        # P1-B：逐题冻结进回放池（只追加）。失败不阻断评估主流程。
        try:
            from app.db.models import DataAskReplayEpisode

            era_key = era or date.today().isoformat()
            for i in items:
                db.add(DataAskReplayEpisode(
                    data_source_id=ds,
                    run_id=int(run_row.id),
                    run_kind=run_kind,
                    agent_version_id=run_row.agent_version_id,
                    agent_version=run_row.agent_version,
                    era=era_key,
                    question_id=str(i["qid"]),
                    question=str(i["question"]),
                    category=i.get("category"),
                    budget_retries=budget_retries,
                    sql_ok=bool(i["sql_ok"]),
                    consistency=i.get("consistency"),
                    judge_score=i.get("judge_score"),
                    item_score=_item_score(i),
                    duration_ms=i.get("duration_ms"),
                ))
            await db.flush()
        except Exception:
            logger.exception("replay_episode_freeze_failed run=%s", run_row.id)

    if not read_only_baseline and write_quality_score is not False:
        # 基线只读跑 / 多预算点附加跑不写质量分时序，避免看板趋势被稀释
        db.add(AgentQualityScore(
            data_source_id=ds,
            agent_id=str(source.agent_id) if source.agent_id else None,
            run_id=int(run_row.id),
            score=overall if overall is not None else (sql_rate or 0.0),
            metrics={
                "sql_success_rate": sql_rate,
                "consistency_rate": cons_rate,
                "judge_score": judge_rate,
                "chart_match_rate": chart_rate,
                "total": total,
                "passed": passed_n,
                "judged": len(judge_scores),
                "baseline_refreshed": sum(1 for i in items if i["consistency"] == "baseline"),
                "duration_ms": run_row.duration_ms,
            },
        ))
    await db.flush()
    logger.info(
        "eval_run_done run=%s ds=%s total=%s sql=%s cons=%s judge=%s overall=%s",
        run_row.id, ds, total, sql_rate, cons_rate, judge_rate, overall,
    )
    return run_row


def meets_promotion_gate(run_row: AgentEvalRun) -> tuple[bool, str]:
    """晋升门槛判定：SQL 成功率 ≥0.90 且结果一致率 ≥0.85。首轮仅建基线时不晋升。"""
    if run_row.status != "done" or not run_row.total:
        return False, "评估未完成"
    if run_row.total < MIN_EVAL_SET:
        return False, f"考题不足（{run_row.total} < {MIN_EVAL_SET}）"
    if run_row.consistency_rate is None:
        return False, "首轮评估仅建立签名基线，待下轮验证一致性"
    if (run_row.sql_success_rate or 0) < PROMOTE_SQL_SUCCESS:
        return False, f"SQL 成功率 {run_row.sql_success_rate:.0%} 未达门槛 {PROMOTE_SQL_SUCCESS:.0%}"
    if run_row.consistency_rate < PROMOTE_CONSISTENCY:
        return False, f"结果一致率 {run_row.consistency_rate:.0%} 未达门槛 {PROMOTE_CONSISTENCY:.0%}"
    return True, "达标"
