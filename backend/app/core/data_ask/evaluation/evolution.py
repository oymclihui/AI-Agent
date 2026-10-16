"""每周进化闭环：蒸馏 → 候选版本 → 回归评估 → 达标晋升。

闭环逻辑：蒸馏产物（示例/模板/规则）实时生效于问数链路 → 回归评估验证
「改变后的线上行为」质量 → 达标才把对应配置快照（候选版本）转正留痕。
每个数据源独立 session 与事务，单个失败不影响其他数据源。
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import select

from app.core.data_ask.evaluation.builder import build_eval_set
from app.core.data_ask.evaluation.runner import MIN_EVAL_SET, meets_promotion_gate, run_eval_run
from app.db.models import Agent as AgentModel
from app.db.models import (
    AgentEvalRun,
    AgentEvalSet,
    AgentRelease,
    AgentVersion,
    DataAskReplayEpisode,
    DataSource,
    DataAskTrainTask,
)

logger = logging.getLogger("agent_eval_evolution")

# P0-A 平手容差（P1-A 起从单点容差降级为「全前沿平手容差」）：
# 候选须在至少一个预算点领先基线超过 ε 才晋升；任一预算点落后超过 ε 即否决。
# 依据：弱候选实测（run#32/#33）中 judge 噪声可造成 ~0.002 的虚高分差，
# 11 题评测下 1 个 judge 档位 ≈ 0.009，取 0.01 过滤噪声级差异，平手保留现版。
PROMOTE_MARGIN = 0.01

# P1-A 默认预算工作点：SQL 修复重试上限（与 service.MAX_SQL_RETRIES 一致）。
# 评测前沿 = 预算 {2,1,0} 三点；只有默认工作点的候选跑写质量分时序。
DEFAULT_BUDGET = 2


async def _era_regression_gate(
    db,
    data_source_id: str,
    *,
    current_era: str,
    margin: float,
) -> tuple[bool, str]:
    """P1-B 逐时期不回归门槛（DREAM-RSI trace_pool 全历史重放思想的移植）。

    对每个早于当前时期、且候选版本在其冻结剧集（run_kind=candidate）中出现过的
    历史 era：计算候选与基线剧集 item_score 均值差，候选落后超过 margin 即否决。
    防止「新版在新题上好、在老题上崩」的跨期回归被总均分掩盖。

    无历史剧集（首次启用）时放行——不阻塞，数据会随每轮评测自然累积。
    """
    rows = (
        await db.execute(
            select(
                DataAskReplayEpisode.era,
                DataAskReplayEpisode.run_kind,
                DataAskReplayEpisode.item_score,
            ).where(
                DataAskReplayEpisode.data_source_id == data_source_id,
                DataAskReplayEpisode.era < current_era,
                DataAskReplayEpisode.item_score.is_not(None),
                DataAskReplayEpisode.run_kind.in_(("baseline", "candidate")),
            )
        )
    ).all()

    eras = sorted({r.era for r in rows})
    for era in eras:
        cand_scores = [
            float(r.item_score) for r in rows
            if r.era == era and r.run_kind == "candidate"
        ]
        base_scores = [
            float(r.item_score) for r in rows
            if r.era == era and r.run_kind == "baseline"
        ]
        if not cand_scores or not base_scores:
            continue
        cand_mean = sum(cand_scores) / len(cand_scores)
        base_mean = sum(base_scores) / len(base_scores)
        if cand_mean < base_mean - margin:
            return False, (
                f"未晋升：逐时期不回归门槛——候选在冻结时期 {era} 落后 "
                f"{cand_mean - base_mean:+.4f}（候选 {cand_mean:.4f} vs 基线 {base_mean:.4f}，"
                f"超出容差 {margin}），保守保留现版"
            )
    return True, "ok"


async def _evolve_one(session_factory, data_source_id: str) -> dict[str, Any]:
    from app.core.data_ask.distill.example_store import distill_examples
    from app.core.data_ask.distill.rule_miner import mine_rules
    from app.core.data_ask.distill.template_miner import mine_templates
    from app.core.data_ask.factory.service import regenerate_candidate
    from app.core.data_ask.factory.versioning import active_version, promote, release, rollback

    from sqlalchemy import func

    result: dict[str, Any] = {
        "data_source_id": data_source_id,
        "data_source_name": None,
        "distill": {},
        "eval_set": {},
        "candidate_version": None,
        "eval_run_id": None,
        "scores": {},
        "promoted": False,
        "reason": "",
    }
    async with session_factory() as db:
        try:
            source = await db.get(DataSource, data_source_id)
            if not source:
                result["reason"] = "数据源不存在"
                return result
            result["data_source_name"] = source.name
            ds = str(source.id)

            # ── 第一步：知识蒸馏三件套（示例 / 模板 / 规则，幂等）──
            result["distill"]["examples"] = await distill_examples(db, data_source_id=ds)
            result["distill"]["templates"] = await mine_templates(db, data_source_id=ds, min_support=3)
            result["distill"]["rules"] = await mine_rules(db, data_source_id=ds, min_support=1)

            # ── 第二步：扩充回归考题库（golden + 正例，按问题去重幂等）──
            result["eval_set"] = await build_eval_set(db, source)

            # ── 第三步：为绑定智能体生成候选版本（不自动发布）──
            agent = await db.get(AgentModel, str(source.agent_id)) if source.agent_id else None
            prod_version = await active_version(db, str(source.agent_id)) if agent else None

            candidate = await regenerate_candidate(
                db, source, note="每周进化：蒸馏后再生成",
            )
            if candidate is not None:
                result["candidate_version"] = int(candidate.version)

            # ── 第四步：考题充足才跑回归 ──
            set_size = int((
                await db.execute(
                    select(func.count(AgentEvalSet.id)).where(
                        AgentEvalSet.data_source_id == ds, AgentEvalSet.active.is_(True),
                    )
                )
            ).scalar() or 0)
            if set_size < MIN_EVAL_SET:
                result["reason"] = (
                    f"考题库仅 {set_size} 题（<{MIN_EVAL_SET}），跳过评估与晋升；"
                    "继续通过问数反馈积累真实考题"
                )
                await db.commit()
                return result

            # ── P1-A 多预算点双候选评测 ──
            # 0 号候选 = 当前生产（只读基线跑），1 号候选 = 新版 spec 隔离跑；
            # 预算轴 = SQL 修复重试上限 {2,1,0}（2=线上默认工作点），每个预算点成对评测，
            # 晋升判据由「单点 argmax」升级为「质量↔成本前沿配对比较」（DREAM-RSI 移植）：
            # 噪声难以同时抬高 3 个预算点的整条前沿，比单点 ε 容差更本质。
            # spec_override 只作用于评估路径，绝不改动线上 Agent 记录。
            era_key = date.today().isoformat()

            cand_spec_override: dict[str, Any] | None = None
            if candidate is not None:
                spec = dict(candidate.spec or {})
                cand_spec_override = {
                    k: spec[k] for k in ("llm_provider", "llm_model", "goal", "backstory")
                    if spec.get(k)
                } or None

            async def _paired_run(kind: str, budget: int) -> AgentEvalRun:
                is_base = kind == "baseline"
                vrow = prod_version if is_base else candidate
                label = f"v{vrow.version}" if vrow is not None else "当前生产行为"
                run = AgentEvalRun(
                    data_source_id=ds,
                    agent_id=str(source.agent_id) if source.agent_id else None,
                    agent_version_id=int(vrow.id) if vrow is not None else None,
                    agent_version=int(vrow.version) if vrow is not None else None,
                    trigger="weekly",
                    status="pending",
                    note=f"P0A {'基线' if is_base else '候选'}@预算{budget}：{label}",
                )
                db.add(run)
                await db.flush()
                await run_eval_run(
                    db, run, source,
                    spec_override=None if is_base else cand_spec_override,
                    read_only_baseline=is_base,
                    budget_retries=budget,
                    # 仅默认工作点的候选跑写质量分时序，其余附加跑不稀释看板趋势
                    write_quality_score=(not is_base and budget == DEFAULT_BUDGET),
                    era=era_key,
                    run_kind=kind,
                )
                return run

            runs: dict[tuple[str, int], AgentEvalRun] = {}
            # 默认工作点先跑（该候选跑负责建立缺失签名基线），再依次降预算点；
            # 无候选时只跑默认预算点的基线，不浪费评估预算
            budget_order = (DEFAULT_BUDGET, 1, 0) if candidate is not None else (DEFAULT_BUDGET,)
            for b in budget_order:
                runs[("baseline", b)] = await _paired_run("baseline", b)
                if candidate is not None:
                    runs[("candidate", b)] = await _paired_run("candidate", b)

            baseline_run = runs[("baseline", DEFAULT_BUDGET)]
            run_row: AgentEvalRun | None = runs.get(("candidate", DEFAULT_BUDGET))
            result["baseline_run_id"] = int(baseline_run.id)
            result["baseline_scores"] = {
                "sql_success_rate": baseline_run.sql_success_rate,
                "consistency_rate": baseline_run.consistency_rate,
                "judge_score": baseline_run.judge_score,
                "overall_score": baseline_run.overall_score,
            }
            if run_row is not None:
                result["eval_run_id"] = int(run_row.id)
                result["scores"] = {
                    "sql_success_rate": run_row.sql_success_rate,
                    "consistency_rate": run_row.consistency_rate,
                    "judge_score": run_row.judge_score,
                    "overall_score": run_row.overall_score,
                }
                result["budget_scores"] = {
                    str(b): {
                        "baseline": runs[("baseline", b)].overall_score,
                        "candidate": runs[("candidate", b)].overall_score,
                        "baseline_run_id": int(runs[("baseline", b)].id),
                        "candidate_run_id": int(runs[("candidate", b)].id),
                    }
                    for b in budget_order
                }
            else:
                # 无候选版本：基线跑兼作质量记录
                result["eval_run_id"] = int(baseline_run.id)
                result["scores"] = dict(result["baseline_scores"])

            # ── 第五步：晋升判定 ──
            # P1-A：前沿配对比较（候选须在每个预算点不劣于基线、且至少一个预算点超出 ε；
            #       ε 从「单点噪声容差」降级为「全曲线平手容差」）
            # P1-B：逐时期不回归门槛（候选不得在历史冻结剧集上回归超过 ε）
            action = "skipped"
            if candidate is not None and agent is not None and run_row is not None:
                ok, gate_reason = meets_promotion_gate(run_row)
                cand_s = run_row.overall_score
                prod_s = baseline_run.overall_score
                prod_label = f"v{prod_version.version}" if prod_version is not None else "当前生产"
                if not ok:
                    result["reason"] = f"未晋升：{gate_reason}；请继续通过问数反馈训练（纠正SQL / 存示例）"
                elif prod_s is None or cand_s is None:
                    # 基线/候选任一评估分缺失（如跑失败）时不晋升——绝不无对比晋升
                    result["reason"] = "未晋升：基线或候选评估分缺失，无法对比，保守保留现版"
                else:
                    pairs: list[tuple[int, float, float]] = []
                    for b in budget_order:
                        bs = runs[("baseline", b)].overall_score
                        cs = runs[("candidate", b)].overall_score
                        if bs is None or cs is None:
                            pairs = []
                            break
                        pairs.append((b, float(cs), float(bs)))

                    if not pairs:
                        result["reason"] = "未晋升：存在预算点评估分缺失，无法构成前沿，保守保留现版"
                    elif any(cs < bs - PROMOTE_MARGIN for _b, cs, bs in pairs):
                        worst = min(pairs, key=lambda p: p[1] - p[2])
                        result["reason"] = (
                            f"未晋升：前沿未支配基线——预算点 {worst[0]} 上候选 {worst[1]:.4f} "
                            f"落后基线 {worst[2]:.4f}（差 {worst[1] - worst[2]:+.4f}，超出容差 {PROMOTE_MARGIN}）"
                        )
                    elif not any(cs > bs + PROMOTE_MARGIN for _b, cs, bs in pairs):
                        result["reason"] = (
                            f"未晋升：前沿与基线重合（全部 {len(pairs)} 个预算点分差均在平手容差 "
                            f"≤{PROMOTE_MARGIN} 内），保守保留现版"
                        )
                    else:
                        reg_ok, reg_reason = await _era_regression_gate(
                            db, ds,
                            current_era=era_key,
                            margin=PROMOTE_MARGIN,
                        )
                        if not reg_ok:
                            result["reason"] = reg_reason
                        else:
                            await promote(db, agent, candidate)
                            await release(
                                db, agent, candidate, scope="full",
                                note=(
                                    f"P1 前沿晋升：候选 v{candidate.version} 在 {len(pairs)} 个预算点"
                                    f"不劣且至少一点超出基线 {prod_label}（ε={PROMOTE_MARGIN}）"
                                ),
                            )
                            result["promoted"] = True
                            action = "promoted"
                            best_point = max(pairs, key=lambda p: p[1] - p[2])
                            result["reason"] = (
                                f"前沿对比胜出，v{candidate.version} 已晋升发布"
                                f"（{len(pairs)} 个预算点全部不劣，预算点 {best_point[0]} 领先 "
                                f"{best_point[1] - best_point[2]:+.4f} > 容差 {PROMOTE_MARGIN}；逐时期不回归通过）"
                            )
            elif agent is not None:
                # 无候选版本：仅记录质量；生产行为显著回退时自动回滚（沿用原机制）
                prod = prod_version
                prev_best = (
                    await db.execute(
                        select(func.max(AgentEvalRun.overall_score)).where(
                            AgentEvalRun.data_source_id == ds,
                            AgentEvalRun.status == "done",
                            AgentEvalRun.overall_score.is_not(None),
                            AgentEvalRun.id != int(baseline_run.id),
                        )
                    )
                ).scalar()
                if (
                    prod is not None and prev_best is not None
                    and (baseline_run.overall_score or 0) < float(prev_best) - 0.05
                ):
                    # 质量显著回退：回滚到当前生产版本的上一任「已发布过」的版本
                    prev_release = (
                        await db.execute(
                            select(AgentRelease).where(
                                AgentRelease.agent_id == str(source.agent_id),
                                AgentRelease.version_id != int(prod.id),
                            ).order_by(AgentRelease.created_at.desc(), AgentRelease.id.desc()).limit(1)
                        )
                    ).scalar_one_or_none()
                    prev_prod = await db.get(AgentVersion, int(prev_release.version_id)) if prev_release else None
                    if prev_prod is not None:
                        await rollback(
                            db, agent, prev_prod, user=None,
                            note="每周进化：生产行为显著回退，自动回滚",
                        )
                        action = "rolled_back"
                        result["rolled_back_to"] = int(prev_prod.version)
                        result["reason"] = (
                            f"生产行为显著回退，已自动回滚至 v{prev_prod.version}，"
                            "请继续通过问数反馈训练"
                        )
                if action != "rolled_back":
                    result["reason"] = "本周无候选版本，仅记录质量（双候选对比跳过）"
            else:
                result["reason"] = "未绑定智能体，仅记录质量"

            # 晋升/回滚事件留痕：训练流水线（SSE / 任务列表 / 看板）实时可见
            try:
                db.add(DataAskTrainTask(
                    data_source_id=ds, kind="promote", status="done", progress=100,
                    detail={
                        "action": action,
                        "eval_run_id": result.get("eval_run_id"),
                        "candidate_version": result.get("candidate_version"),
                        "baseline_run_id": result.get("baseline_run_id"),
                        "baseline_version": int(prod_version.version) if prod_version is not None else None,
                        "baseline_overall": baseline_run.overall_score,
                        "candidate_overall": run_row.overall_score if run_row is not None else None,
                        "budget_scores": result.get("budget_scores"),
                        "rolled_back_to": result.get("rolled_back_to"),
                        "overall": run_row.overall_score if run_row is not None else baseline_run.overall_score,
                        "promoted": bool(result.get("promoted")),
                        "reason": result.get("reason"),
                    },
                ))
            except Exception:
                pass
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.exception("weekly_evolution_source_failed ds=%s", data_source_id)
            result["reason"] = f"进化失败：{str(exc)[:300]}"
    return result


async def weekly_evolution(session_factory) -> list[dict[str, Any]]:
    """对全部数据源执行每周进化闭环，返回逐源结果。"""
    async with session_factory() as db:
        ds_ids = list((await db.execute(select(DataSource.id))).scalars().all())

    results: list[dict[str, Any]] = []
    for ds_id in ds_ids:
        results.append(await _evolve_one(session_factory, str(ds_id)))
        logger.info("weekly_evolution ds=%s -> %s", ds_id, results[-1]["reason"])
    return results
