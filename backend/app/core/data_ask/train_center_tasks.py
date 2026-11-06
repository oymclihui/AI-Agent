"""训练中心 P1+P2 Celery 任务：统一训练工单（五步向导）。

P2 新增 stage_prompt（GEPA 式反思改写 role/goal/backstory，经评测门禁才采纳）。
"""
from __future__ import annotations

import logging
import os
import time as _time
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.tasks_runtime import run_in_persistent_loop
from app.worker import celery_app

logger = logging.getLogger("train_center_tasks")

_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
TrainSessionLocal = async_sessionmaker(_engine, expire_on_commit=False)

SPEC_OVERRIDE_FIELDS = ("llm_provider", "llm_model", "role", "goal", "backstory")

# LiteLLM 代理（backend 容器内用容器名 aiagnet_litellm 直连）
_LITELLM_BASE = os.environ.get("LITELLM_BASE_URL") or "http://aiagnet_litellm:4000"
_LITELLM_KEY = os.environ.get("LITELLM_MASTER_KEY") or ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _call_qwen_max(
    prompt: str, *, system: str = "你是严格的提示词优化专家", max_retries: int = 2,
) -> str:
    """异步调 LiteLLM 代理 qwen-max，返回纯文本。Celery 上下文可用。"""
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15)) as client:
                r = await client.post(
                    f"{_LITELLM_BASE}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {_LITELLM_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "qwen-max",
                        "temperature": 0.4,
                        "max_tokens": 1200,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
                if r.status_code != 200:
                    raise RuntimeError(f"litellm_status={r.status_code} body={r.text[:200]}")
                data = r.json()
                return data["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001 — 网络抖动重试
            last_err = exc
            logger.warning("qwen_max_attempt_failed attempt=%s err=%s", attempt, exc)
            await _async_sleep(1.5)
    raise RuntimeError(f"qwen_max_failed: {last_err}")


async def _async_sleep(sec: float) -> None:
    import asyncio
    await asyncio.sleep(sec)



def _recompute(job, stages: list[dict]) -> None:
    total = max(len(stages), 1)
    done = sum(1 for s in stages if s.get("status") in ("done", "skipped"))
    running = next((s for s in stages if s.get("status") == "running"), None)
    part = float(running.get("progress") or 0) / 100.0 if running else 0.0
    job.progress = min(99, int(((done + part) / total) * 100))


def _score_block(row) -> dict:
    if row is None:
        return {}
    return {
        "run_id": int(row.id),
        "total": int(row.total or 0),
        "passed": int(row.passed or 0),
        "sql_success_rate": row.sql_success_rate,
        "consistency_rate": row.consistency_rate,
        "judge_score": row.judge_score,
        "overall_score": row.overall_score,
        "weak_categories": list(row.weak_categories or []),
    }


async def _resolve_target(db, job):
    from app.db.models import Agent as AgentModel
    from app.db.models import DataSource

    if job.target_type == "agent":
        agent = await db.get(AgentModel, str(job.target_id))
        if not agent:
            return None, None
        source = (
            await db.execute(select(DataSource).where(DataSource.agent_id == str(agent.id)).limit(1))
        ).scalar_one_or_none()
        if source is None:
            ds_id = str((agent.metadata_ or {}).get("data_source_id") or "")
            source = await db.get(DataSource, ds_id) if ds_id else None
        return source, agent

    source = await db.get(DataSource, str(job.target_id))
    agent = await db.get(AgentModel, str(source.agent_id)) if source and source.agent_id else None
    return source, agent


async def _stage_collect(db, job, source, agent) -> dict:
    from app.db.models import AgentEvalSet, AskExample, AskFeedback, AskTrace

    ds = str(source.id)

    async def _count(model):
        return int((await db.execute(
            select(func.count()).select_from(model).where(model.data_source_id == ds)
        )).scalar() or 0)

    traces = await _count(AskTrace)
    feedback = await _count(AskFeedback)
    examples = await _count(AskExample)
    eval_set = int((await db.execute(
        select(func.count(AgentEvalSet.id)).where(
            AgentEvalSet.data_source_id == ds, AgentEvalSet.active.is_(True),
        )
    )).scalar() or 0)
    detail = {"traces": traces, "feedback": feedback, "examples": examples, "eval_set": eval_set}
    message = (
        f"轨迹 {traces} 条 · 反馈 {feedback} 条 · 示例 {examples} 条 · 考题 {eval_set} 题"
    )
    return {"status": "done", "message": message, "detail": detail}


async def _stage_collect_for_prompt(db, job, source, agent) -> dict:
    """P2 prompt 专用：拉最近 eval run 的失败样本作为反思输入。"""
    from app.db.models import AgentEvalRun

    ds = str(source.id)
    rows = (
        await db.execute(
            select(AgentEvalRun)
            .where(AgentEvalRun.data_source_id == ds, AgentEvalRun.status == "done")
            .order_by(AgentEvalRun.created_at.desc())
            .limit(3)
        )
    ).scalars().all()
    if not rows:
        return {
            "status": "skipped",
            "message": "未发现历史评测记录（先跑一次训练全流程，或手补考题）",
            "detail": {"runs_searched": 3, "failed_items": 0},
        }

    failures: list[dict[str, Any]] = []
    for run in rows:
        items = run.items or []
        for i in items:
            if not (i.get("sql_ok") and i.get("consistency") != "mismatch"):
                failures.append({
                    "run_id": int(run.id),
                    "run_version": run.agent_version,
                    "question": i.get("question"),
                    "sql_ok": i.get("sql_ok"),
                    "consistency": i.get("consistency"),
                    "judge_score": i.get("judge_score"),
                    "category": i.get("category"),
                })
    failures = failures[:30]
    message = f"取最近 {len(rows)} 次评测，失败样本 {len(failures)} 条"
    return {"status": "done", "message": message, "detail": {"runs": len(rows), "failures": failures}}


async def _stage_prompt(db, job, source, agent) -> dict:
    """P2 GEPA 式反思改写 role/goal/backstory。产出 PromptCandidate + AgentVersion candidate。"""
    import json as _json

    from app.db.models import AgentVersion, PromptCandidate

    if agent is None or not source.agent_id:
        return {"status": "skipped", "message": "数据源未绑定智能体", "detail": {}}

    detail_collect = ((job.detail or {}).get("collect") or {}) if isinstance(job.detail, dict) else {}
    failures: list[dict[str, Any]] = list(detail_collect.get("failures") or [])
    if not failures:
        return {
            "status": "skipped",
            "message": "没有失败样本可反思（请先跑一次训练积累评测）",
            "detail": {"failures": 0},
        }

    # 聚合成 1-3 组失败模式（按 category 合并）
    clusters: list[dict[str, Any]] = []
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for f in failures:
        cat = str(f.get("category") or "未分类")
        by_cat.setdefault(cat, []).append(f)
    for cat, items in by_cat.items():
        if len(clusters) >= 3:
            break
        clusters.append({
            "category": cat,
            "count": len(items),
            "sample_questions": [it.get("question") for it in items[:3] if it.get("question")],
            "sql_fail_rate": sum(1 for it in items if not it.get("sql_ok")) / max(len(items), 1),
        })
    clusters.sort(key=lambda c: -c["count"])

    # 取基线版本（active_version）
    from app.core.data_ask.factory.versioning import active_version

    base_ver = await active_version(db, str(agent.id))
    base_spec: dict[str, Any] = {}
    if base_ver is not None:
        base_spec = dict(base_ver.spec or {})
    else:
        base_spec = {f: getattr(agent, f, None) for f in ("role", "goal", "backstory")}

    current_role = base_spec.get("role") or getattr(agent, "role", "") or ""
    current_goal = base_spec.get("goal") or getattr(agent, "goal", "") or ""
    current_backstory = base_spec.get("backstory") or getattr(agent, "backstory", "") or ""

    prompt_text = _json.dumps({
        "task": "反思式提示词优化。给出失败样本聚类 + 当前提示词，生成 1-3 条可落地改写建议。",
        "output_format": {
            "candidates": [
                {"field": "goal|role|backstory", "after": "...", "reason": "..."},
            ]
        },
        "failure_clusters": clusters,
        "current": {
            "role": current_role[:500],
            "goal": current_goal[:1500],
            "backstory": current_backstory[:1500],
        },
    }, ensure_ascii=False, indent=2)

    try:
        raw = await _call_qwen_max(
            prompt_text,
            system=(
                "你是 GEPA/DSPy 风格的提示词优化专家。不要发散，只给可直接替换的改写 + 简短理由。"
                "输出严格 JSON，顶层键 'candidates'，每项键 'field','after','reason'。after 长度 ≤ 800。"
            ),
        )
    except Exception as exc:
        logger.exception("train_prompt_llm_failed job=%s", job.id)
        return {
            "status": "failed", "message": f"反思改写调用失败：{str(exc)[:120]}",
            "detail": {"failures": len(failures)},
        }

    # 解析 JSON（容错：找 {} 块）
    candidates: list[dict[str, Any]] = []
    try:
        parsed = _json.loads(raw.strip())
        candidates = list(parsed.get("candidates") or [])
    except Exception:
        import re
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                parsed = _json.loads(m.group(0))
                candidates = list(parsed.get("candidates") or [])
            except Exception:
                pass

    valid_fields = {"role", "goal", "backstory"}
    prompt_rows: list[PromptCandidate] = []
    for c in candidates[:3]:
        field = str(c.get("field") or "").strip()
        if field not in valid_fields:
            continue
        after = str(c.get("after") or "").strip()
        reason = str(c.get("reason") or "").strip()
        before_map = {"role": current_role, "goal": current_goal, "backstory": current_backstory}
        before = before_map.get(field, "")
        if not after or after == before:
            continue
        row = PromptCandidate(
            agent_id=str(agent.id),
            data_source_id=str(source.id),
            base_version_id=int(base_ver.id) if base_ver is not None else None,
            field=field,
            before=before, after=after,
            reason=reason or None,
            failure_clusters=clusters,
            status="pending",
            train_job_id=str(job.id),
            model="qwen-max",
            created_by=str(job.created_by) if job.created_by else None,
        )
        db.add(row)
        prompt_rows.append(row)
    await db.commit()

    if not prompt_rows:
        return {
            "status": "skipped",
            "message": "LLM 未产出可落地改写（after 为空或与 before 相同）",
            "detail": {"llm_raw": raw[:400]},
        }

    # 合成新 spec，regenerate_candidate
    merged_spec = dict(base_spec)
    changed_fields: list[str] = []
    for row in prompt_rows:
        merged_spec[row.field] = row.after
        changed_fields.append(row.field)
    # 用非空字段做 generate 的 nl_prompt 提示，把改写后 spec 塞进去
    from app.core.data_ask.factory.service import regenerate_candidate
    from app.core.data_ask.factory import versioning
    from app.db.base import generate_uuid

    # 直接 snapshot 改好的 spec，不走 regenerate_candidate（避免二次 LLM 改写）
    coach = {"source": "prompt_pipeline", "kind": "gepa"}
    cand_version: AgentVersion | None = None
    try:
        cand_version = await versioning.snapshot(
            db, agent, source="prompt",
            note=f"训练中心 prompt 改写（{','.join(changed_fields)}）·{job.id}",
            coach=coach, status="candidate", spec=merged_spec,
        )
        await db.commit()
    except Exception as exc:
        logger.exception("train_prompt_snapshot_failed job=%s", job.id)
        await db.rollback()
        return {
            "status": "failed",
            "message": f"候选版本快照失败：{str(exc)[:150]}",
            "detail": {"prompt_candidates": len(prompt_rows)},
        }

    detail = {
        "prompt_candidates": [
            {
                "id": r.id, "field": r.field, "reason": r.reason,
                "before": r.before[:80], "after": r.after[:80],
            }
            for r in prompt_rows
        ],
        "candidate": {"version": int(cand_version.version), "version_id": int(cand_version.id)},
        "changed_fields": changed_fields,
        "failures": len(failures),
        "clusters": clusters,
    }
    # 同时写顶层 candidate（与 full kind 的 _stage_candidate 对齐，方便 _stage_eval 读取）
    return {
        "status": "done",
        "message": (
            f"反思改写 {len(prompt_rows)} 条（{','.join(changed_fields)}）→ 候选 v{cand_version.version}"
        ),
        "detail": detail,
        # 顶层 candidate 让 _run_job 合并到 job.detail["candidate"]，eval/promote 直接读取
        "_top_level_candidate": {"version": int(cand_version.version), "version_id": int(cand_version.id)},
    }


async def _stage_distill(db, job, source, agent) -> dict:
    from app.core.data_ask.distill.example_store import distill_examples
    from app.core.data_ask.distill.rule_miner import mine_rules
    from app.core.data_ask.distill.template_miner import mine_templates

    ds = str(source.id)
    out: dict = {}
    errors: list[str] = []
    for key, fn, kwargs in (
        ("examples", distill_examples, {}),
        ("templates", mine_templates, {"min_support": 3}),
        ("rules", mine_rules, {"min_support": 1}),
    ):
        try:
            out[key] = await fn(db, data_source_id=ds, **kwargs)
            await db.commit()
        except Exception as exc:  # 单项失败不阻断其余蒸馏
            logger.exception("train_job_distill_failed job=%s part=%s", job.id, key)
            await db.rollback()
            errors.append(f"{key}: {str(exc)[:200]}")
            out[key] = {"error": str(exc)[:300]}

    if len(errors) >= 3:
        return {"status": "failed", "message": "；".join(errors), "detail": out}
    parts: list[str] = []
    for key, label in (("examples", "示例"), ("templates", "模板"), ("rules", "规则")):
        val = out.get(key)
        if isinstance(val, dict) and not val.get("error"):
            created = val.get("created") or val.get("new") or 0
            parts.append(f"{label} +{created}")
    message = "，".join(parts) if parts else "蒸馏完成（幂等，无新增）"
    if errors:
        message += "；部分失败：" + "；".join(errors)
    return {"status": "done", "message": message, "detail": out}


async def _stage_build_eval(db, job, source, agent) -> dict:
    from app.core.data_ask.evaluation.builder import build_eval_set

    out = await build_eval_set(db, source)
    await db.commit()
    detail = out if isinstance(out, dict) else {"result": str(out)}
    return {"status": "done", "message": "考题库已按真实 golden / 正例扩容（幂等）", "detail": detail}


async def _stage_candidate(db, job, source, agent) -> dict:
    from app.core.data_ask.factory.service import regenerate_candidate

    if not source.agent_id or agent is None:
        return {
            "status": "skipped",
            "message": "该数据源未绑定智能体：请先在「智能体工厂」发布，再训练配置",
            "detail": {"skipped": True},
        }
    row = await regenerate_candidate(db, source, note=f"训练中心 {job.id}：学习后生成候选")
    await db.commit()
    if row is None:
        return {"status": "skipped", "message": "候选生成未返回版本", "detail": {"skipped": True}}
    detail = {"version": int(row.version), "version_id": int(row.id)}
    return {"status": "done", "message": f"候选版本 v{row.version} 已生成（不自动上线）", "detail": detail}


async def _stage_eval(db, job, source, agent) -> dict:
    from app.core.data_ask.evaluation.runner import MIN_EVAL_SET, meets_promotion_gate, run_eval_run
    from app.core.data_ask.factory.versioning import active_version
    from app.db.models import AgentEvalRun, AgentEvalSet, AgentVersion

    ds = str(source.id)
    set_size = int((await db.execute(
        select(func.count(AgentEvalSet.id)).where(
            AgentEvalSet.data_source_id == ds, AgentEvalSet.active.is_(True),
        )
    )).scalar() or 0)
    if set_size < MIN_EVAL_SET:
        return {
            "status": "skipped",
            "message": f"考题库仅 {set_size} 题（<{MIN_EVAL_SET}），请先积累反馈并重新建考题",
            "detail": {"eval_set_size": set_size, "min_eval_set": MIN_EVAL_SET},
        }

    prod = await active_version(db, str(source.agent_id)) if source.agent_id else None
    cand_id = ((job.detail or {}).get("candidate") or {}).get("version_id")
    candidate = await db.get(AgentVersion, int(cand_id)) if cand_id else None

    baseline = AgentEvalRun(
        data_source_id=ds,
        agent_id=str(source.agent_id) if source.agent_id else None,
        agent_version_id=int(prod.id) if prod is not None else None,
        agent_version=int(prod.version) if prod is not None else None,
        trigger="manual",
        status="pending",
        note=f"训练中心 {job.id}：基线（现役）",
    )
    db.add(baseline)
    await db.flush()
    await run_eval_run(db, baseline, source, read_only_baseline=True, run_kind="baseline")
    await db.commit()
    if str(baseline.status) == "failed":
        raise RuntimeError(f"基线评测失败：{baseline.error_message or '未知原因'}")

    cand_run = None
    if candidate is not None:
        spec = dict(candidate.spec or {})
        override = {k: spec[k] for k in SPEC_OVERRIDE_FIELDS if spec.get(k)} or None
        cand_run = AgentEvalRun(
            data_source_id=ds,
            agent_id=str(source.agent_id) if source.agent_id else None,
            agent_version_id=int(candidate.id),
            agent_version=int(candidate.version),
            trigger="manual",
            status="pending",
            note=f"训练中心 {job.id}：候选 v{candidate.version}",
        )
        db.add(cand_run)
        await db.flush()
        await run_eval_run(db, cand_run, source, spec_override=override, run_kind="candidate")
        await db.commit()
        if str(cand_run.status) == "failed":
            raise RuntimeError(f"候选评测失败：{cand_run.error_message or '未知原因'}")

    gate_row = cand_run if cand_run is not None else baseline
    try:
        gate_ok, gate_reason = meets_promotion_gate(gate_row)
    except Exception as exc:
        logger.exception("train_job_gate_failed job=%s", job.id)
        gate_ok, gate_reason = False, f"门禁判定异常：{str(exc)[:120]}"
    detail = {
        "eval_set_size": set_size,
        "baseline": _score_block(baseline),
        "candidate": _score_block(cand_run),
        "gate": {"ok": bool(gate_ok), "reason": gate_reason},
    }
    base_score = baseline.overall_score
    cand_score = cand_run.overall_score if cand_run is not None else None
    if cand_run is None:
        message = f"仅基线评测：综合分 {base_score if base_score is not None else '—'}（无候选可比）"
    else:
        message = (
            f"基线 {base_score if base_score is not None else '—'} vs 候选 "
            f"{cand_score if cand_score is not None else '—'}；门禁：{gate_reason}"
        )
    # ── P2: 回写本轮 PromptCandidate 的 score_delta / eval_run_id / status ──
    if job.kind == "prompt":
        from app.db.models import PromptCandidate

        prompt_detail = ((job.detail or {}).get("prompt") or {}) if isinstance(job.detail, dict) else {}
        pcs = prompt_detail.get("prompt_candidates") or []
        if pcs and cand_run is not None:
            base_score = baseline.overall_score
            cand_score = cand_run.overall_score
            delta = None
            if base_score is not None and cand_score is not None:
                delta = round(float(cand_score) - float(base_score), 6)
            for pc_meta in pcs:
                pc_row = await db.get(PromptCandidate, str(pc_meta.get("id")))
                if pc_row is not None:
                    pc_row.eval_run_id = int(cand_run.id)
                    pc_row.score_delta = delta
                    pc_row.status = "evaluated"
            await db.commit()
    return {"status": "done", "message": message, "detail": detail}


async def _stage_promote(db, job, source, agent) -> dict:
    from app.core.data_ask.factory.versioning import apply_spec, promote, release
    from app.db.models import AgentVersion, PromptCandidate, User

    eval_detail = ((job.detail or {}).get("eval") or {}) if isinstance(job.detail, dict) else {}
    cand_ver = ((job.detail or {}).get("candidate") or {}) if isinstance(job.detail, dict) else {}
    cand_id = cand_ver.get("version_id")
    gate = eval_detail.get("gate") or {}

    async def _tag_prompt(status: str) -> None:
        """给本轮 PromptCandidate 统一打 accepted / rejected（仅有 eval 对比时才回写）。"""
        if job.kind != "prompt":
            return
        prompt_detail = ((job.detail or {}).get("prompt") or {}) if isinstance(job.detail, dict) else {}
        pcs = prompt_detail.get("prompt_candidates") or []
        for pc_meta in pcs:
            row = await db.get(PromptCandidate, str(pc_meta.get("id")))
            if row is not None:
                row.status = status

    if not source.agent_id or agent is None or not cand_id:
        return {
            "status": "skipped",
            "message": "无候选版本可上线（仅记录评测结果，现版继续服务）",
            "detail": {"promoted": False, "reason": "no_candidate"},
        }

    candidate = await db.get(AgentVersion, int(cand_id))
    if candidate is None:
        return {
            "status": "skipped", "message": "候选版本不存在",
            "detail": {"promoted": False, "reason": "candidate_missing"},
        }

    base_score = ((eval_detail.get("baseline") or {}).get("overall_score"))
    cand_score = ((eval_detail.get("candidate") or {}).get("overall_score"))
    if not eval_detail.get("baseline"):
        return {
            "status": "skipped",
            "message": "未执行回归评测（考题不足或缺失），保守保留现版",
            "detail": {"promoted": False, "version": int(candidate.version), "reason": "eval_not_run"},
        }
    if not gate.get("ok"):
        await _tag_prompt("rejected")
        await db.commit()
        return {
            "status": "done",
            "message": f"未上线：{gate.get('reason') or '评测门禁未通过'}，保留现版",
            "detail": {"promoted": False, "version": int(candidate.version), "reason": gate.get("reason")},
        }
    if base_score is None or cand_score is None:
        return {
            "status": "done", "message": "未上线：基线或候选缺分，保守保留现版",
            "detail": {"promoted": False, "version": int(candidate.version), "reason": "score_missing"},
        }
    if float(cand_score) <= float(base_score):
        await _tag_prompt("rejected")
        await db.commit()
        return {
            "status": "done",
            "message": f"未上线：候选 {cand_score:.4f} 未优于现版 {base_score:.4f}，保守保留现版",
            "detail": {"promoted": False, "version": int(candidate.version), "reason": "not_better"},
        }

    apply_spec(agent, dict(candidate.spec or {}))
    await db.flush()
    await promote(db, agent, candidate)
    user = await db.get(User, str(job.created_by)) if job.created_by else None
    rel = await release(
        db, agent, candidate, scope="full", user=user,
        note=f"训练中心 {job.id} 晋升：v{candidate.version} 优于现版 {base_score:.4f}→{cand_score:.4f}",
    )
    await _tag_prompt("accepted")
    await db.commit()
    return {
        "status": "done",
        "message": f"已上线 v{candidate.version}（综合分 {base_score:.4f} → {cand_score:.4f}）",
        "detail": {
            "promoted": True, "version": int(candidate.version),
            "version_id": int(candidate.id), "release_id": rel.id,
            "reason": "gate_passed_and_better",
        },
    }


# ────────────────────── P3: 多轮与工具轨迹 ──────────────────────

TRAJ_LIMIT = 500


async def _stage_traj_collect(db, job, source, agent) -> dict:
    """采集轨迹信号：run 数 / 节点数 / 轨迹数 / 澄清触发 / 苏格拉底反问样本。"""
    from app.db.models import AgentSocraticTrace, AskTrace, DataAskReplayEpisode, DataAskTreeNode

    ds = str(source.id)

    async def _count(model, *conds):
        return int((await db.execute(
            select(func.count()).select_from(model).where(model.data_source_id == ds, *conds)
        )).scalar() or 0)

    runs = int((await db.execute(
        select(func.count(func.distinct(DataAskTreeNode.run_id))).where(
            DataAskTreeNode.data_source_id == ds,
        )
    )).scalar() or 0)
    nodes = await _count(DataAskTreeNode)
    traces = await _count(AskTrace)
    clarify = await _count(AskTrace, AskTrace.clarification.is_(True))
    episodes = await _count(DataAskReplayEpisode)
    socratic = 0
    if agent is not None:
        socratic = int((await db.execute(
            select(func.count()).select_from(AgentSocraticTrace).where(
                AgentSocraticTrace.agent_id == str(agent.id),
            )
        )).scalar() or 0)

    detail = {
        "runs": runs, "nodes": nodes, "traces": traces,
        "clarify_traces": clarify, "socratic": socratic, "replay_episodes": episodes,
    }
    return {
        "status": "done",
        "message": (
            f"问答 run {runs} 次 · 轨迹节点 {nodes} 个 · 澄清 {clarify} 条 · 反问样本 {socratic} 条"
        ),
        "detail": detail,
    }


async def _stage_traj_normalize(db, job, source, agent) -> dict:
    """轨迹标准化：把 data_ask_tree_node 按 run_id 合成 问题→计划→工具调用→观测→结果→奖励。"""
    from sqlalchemy import delete as sa_delete

    from app.db.models import AskTrace, DataAskTreeNode, TrainTrajectory

    ds = str(source.id)
    run_rows = (await db.execute(
        select(DataAskTreeNode.run_id, func.max(DataAskTreeNode.created_at))
        .where(DataAskTreeNode.data_source_id == ds)
        .group_by(DataAskTreeNode.run_id)
        .order_by(func.max(DataAskTreeNode.created_at).desc())
        .limit(TRAJ_LIMIT)
    )).all()
    run_ids = [str(r[0]) for r in run_rows]
    if not run_ids:
        return {
            "status": "skipped",
            "message": "未发现问答轨迹节点（先在问数页提问，或执行一次树回填）",
            "detail": {"runs": 0},
        }

    nodes = (await db.execute(
        select(DataAskTreeNode).where(
            DataAskTreeNode.data_source_id == ds,
            DataAskTreeNode.run_id.in_(run_ids),
        )
    )).scalars().all()
    by_run: dict[str, list] = {}
    for n in nodes:
        by_run.setdefault(str(n.run_id), []).append(n)

    trace_ids = {int(n.trace_id) for n in nodes if n.trace_id is not None}
    trace_map: dict[int, Any] = {}
    if trace_ids:
        rows = (await db.execute(
            select(AskTrace).where(AskTrace.id.in_(list(trace_ids)))
        )).scalars().all()
        trace_map = {int(t.id): t for t in rows}

    await db.execute(sa_delete(TrainTrajectory).where(TrainTrajectory.data_source_id == ds))

    created = 0
    success_n = 0
    reward_sum = 0.0
    cand_total = 0
    invalid_total = 0
    for run_id, ns in by_run.items():
        ordered = sorted(ns, key=lambda x: (int(x.node_order or 0), str(x.id)))
        by_kind = {k: next((n for n in ordered if n.node_kind == k), None) for k in ("root", "intent", "execution", "result")}
        cands = [n for n in ordered if n.node_kind == "candidate"]
        root_p = dict((by_kind["root"].payload or {})) if by_kind["root"] else {}
        intent_p = dict((by_kind["intent"].payload or {})) if by_kind["intent"] else {}
        exec_p = dict((by_kind["execution"].payload or {})) if by_kind["execution"] else {}
        result_p = dict((by_kind["result"].payload or {})) if by_kind["result"] else {}

        tid = next((int(n.trace_id) for n in ordered if n.trace_id is not None), None)
        trace = trace_map.get(tid) if tid is not None else None

        question = root_p.get("question") or (trace.question if trace else None)
        standalone = root_p.get("standalone") or (trace.standalone_question if trace else None)

        ok = result_p.get("ok")
        if ok is None:
            ok = bool(exec_p.get("ok")) if exec_p else bool(trace.success) if trace else False
        ok = bool(ok)

        mode = result_p.get("mode") or (trace.analysis_mode if trace else None)
        clarified = bool(result_p.get("clarification") or (trace.clarification if trace else False))
        if not mode and (clarified or not cands):
            mode = "clarification" if clarified else mode

        tool_calls = [
            {
                "index": (c.payload or {}).get("index"),
                "mode": (c.payload or {}).get("mode"),
                "sql": ((c.payload or {}).get("sql") or "")[:4000] or None,
                "error": ((c.payload or {}).get("error") or "")[:500] or None,
                "row_count": (c.payload or {}).get("row_count"),
                "won": bool((c.payload or {}).get("won")),
            }
            for c in cands
        ]
        n_candidates = len(tool_calls)
        n_invalid = sum(1 for t in tool_calls if t.get("error"))
        n_rounds = max(1, n_candidates)
        invalid_rate = n_invalid / n_candidates if n_candidates else 0.0
        reward = round(max(0.0, (1.0 if ok else 0.0) - 0.5 * invalid_rate), 4)

        db.add(TrainTrajectory(
            data_source_id=ds,
            agent_id=str(source.agent_id) if source.agent_id else None,
            trace_id=tid,
            run_id=str(run_id),
            question=(question or "")[:4000] or None,
            standalone_question=(standalone or "")[:4000] or None,
            mode=mode,
            plan=intent_p or None,
            tool_calls=tool_calls,
            observation=exec_p or None,
            result=result_p or None,
            reward=reward,
            success=ok,
            n_candidates=n_candidates,
            n_invalid_calls=n_invalid,
            n_rounds=n_rounds,
            source="backfill" if str(run_id).startswith("bf-") else "tree",
            train_job_id=str(job.id),
        ))
        created += 1
        success_n += 1 if ok else 0
        reward_sum += reward
        cand_total += n_candidates
        invalid_total += n_invalid
    await db.commit()

    detail = {
        "runs": created,
        "success": success_n,
        "candidates": cand_total,
        "invalid_calls": invalid_total,
        "avg_reward": round(reward_sum / created, 4) if created else None,
    }
    return {
        "status": "done",
        "message": (
            f"标准化 {created} 条轨迹：成功 {success_n} · 候选 SQL {cand_total} · 无效 {invalid_total}"
        ),
        "detail": detail,
    }


async def _stage_traj_metrics(db, job, source, agent) -> dict:
    """多轮指标：工具选择准确率 / 无效调用率 / 平均轮数 / 澄清收敛率。"""
    from app.db.models import AgentSocraticTrace, AskTrace, TrainTrajectory

    ds = str(source.id)
    rows = (await db.execute(
        select(TrainTrajectory).where(TrainTrajectory.data_source_id == ds)
    )).scalars().all()
    n = len(rows)
    if n == 0:
        return {
            "status": "skipped",
            "message": "无标准化轨迹，先执行轨迹标准化",
            "detail": {"trajectories": 0},
        }

    with_exec = [r for r in rows if r.observation]
    exec_ok = sum(1 for r in with_exec if bool((r.observation or {}).get("ok")))
    success_n = sum(1 for r in rows if r.success)
    cand_total = sum(int(r.n_candidates or 0) for r in rows)
    invalid_total = sum(int(r.n_invalid_calls or 0) for r in rows)
    rounds_total = sum(int(r.n_rounds or 1) for r in rows)
    reward_sum = sum(float(r.reward or 0.0) for r in rows)

    traces_total = int((await db.execute(
        select(func.count()).select_from(AskTrace).where(AskTrace.data_source_id == ds)
    )).scalar() or 0)
    clarify_total = int((await db.execute(
        select(func.count()).select_from(AskTrace).where(
            AskTrace.data_source_id == ds, AskTrace.clarification.is_(True),
        )
    )).scalar() or 0)

    convergence = None
    socratic_total = 0
    socratic_resolved = 0
    if agent is not None:
        socratic_total = int((await db.execute(
            select(func.count()).select_from(AgentSocraticTrace).where(
                AgentSocraticTrace.agent_id == str(agent.id),
            )
        )).scalar() or 0)
        if socratic_total:
            socratic_resolved = int((await db.execute(
                select(func.count()).select_from(AgentSocraticTrace).where(
                    AgentSocraticTrace.agent_id == str(agent.id),
                    AgentSocraticTrace.resolved.is_(True),
                )
            )).scalar() or 0)
            convergence = round(socratic_resolved / socratic_total, 4)

    metrics = {
        "trajectories": n,
        "runs_with_execution": len(with_exec),
        "tool_selection_accuracy": round(exec_ok / len(with_exec), 4) if with_exec else None,
        "candidates": cand_total,
        "invalid_calls": invalid_total,
        "invalid_call_rate": round(invalid_total / cand_total, 4) if cand_total else None,
        "avg_rounds": round(rounds_total / n, 2),
        "success_rate": round(success_n / n, 4),
        "avg_reward": round(reward_sum / n, 4),
        "clarify_trigger_rate": round(clarify_total / traces_total, 4) if traces_total else None,
        "clarify_convergence": convergence,
        "socratic_total": socratic_total,
        "socratic_resolved": socratic_resolved,
    }
    return {
        "status": "done",
        "message": (
            f"工具选择准确率 {metrics['tool_selection_accuracy'] if metrics['tool_selection_accuracy'] is not None else '—'}"
            f" · 无效调用率 {metrics['invalid_call_rate'] if metrics['invalid_call_rate'] is not None else '—'}"
            f" · 平均轮数 {metrics['avg_rounds']}"
            f" · 澄清收敛率 {convergence if convergence is not None else '无样本'}"
        ),
        "detail": metrics,
    }


async def _stage_traj_replay(db, job, source, agent) -> dict:
    """沙箱回放：现配置 vs 网格扫推荐配置，逐轨迹对比动作差异（零 LLM 确定性）。"""
    from app.core.data_ask.replay.corpus import build_replay_corpus
    from app.core.data_ask.replay.strategies import clarify_decision, replay_clarify, replay_memory
    from app.core.data_ask.replay.sweep import sweep_clarify, sweep_memory
    from app.core.data_ask.service import _resolve_policy_knobs, load_source_context

    ds = str(source.id)
    corpus = await build_replay_corpus(db, data_source_id=ds, limit=TRAJ_LIMIT)
    if not corpus.get("traces"):
        return {
            "status": "skipped",
            "message": "重放语料为空（无可回放的历史提问）",
            "detail": {"corpus": corpus.get("stats")},
        }

    _, table_meta, semantic, _perm, _edges = await load_source_context(db, ds)
    current = _resolve_policy_knobs(source, None)

    mem_sweep = sweep_memory(corpus)
    cla_sweep = sweep_clarify(corpus, tables=table_meta, semantic=semantic)
    recommended: dict[str, Any] = {}
    if mem_sweep.get("recommended"):
        recommended.update(mem_sweep["recommended"])
    if cla_sweep.get("recommended"):
        recommended.update(cla_sweep["recommended"])

    mem_cur = replay_memory(
        corpus, min_score=float(current["memory_min_score"]), top_k=int(current["memory_top_k"]),
    )
    cla_cur = replay_clarify(
        corpus, tables=table_meta, semantic=semantic,
        metric_min=int(current["clarify_metric_min"]),
        vague_time_enabled=bool(current["clarify_vague_time_enabled"]),
        relative_time_exempt=bool(current["clarify_relative_time_exempt"]),
    )

    if recommended:
        cand = dict(current)
        cand.update(recommended)
        mem_new = replay_memory(
            corpus, min_score=float(cand["memory_min_score"]), top_k=int(cand["memory_top_k"]),
        )
        cla_new = replay_clarify(
            corpus, tables=table_meta, semantic=semantic,
            metric_min=int(cand["clarify_metric_min"]),
            vague_time_enabled=bool(cand["clarify_vague_time_enabled"]),
            relative_time_exempt=bool(cand["clarify_relative_time_exempt"]),
        )
        diffs: list[dict[str, Any]] = []
        from app.core.data_ask.experience.overview import is_overview_question

        for t in corpus["traces"]:
            if is_overview_question(str(t.get("standalone_question") or t["question"] or "")):
                continue
            old = clarify_decision(
                t["question"], table_meta, semantic,
                metric_min=int(current["clarify_metric_min"]),
                vague_time_enabled=bool(current["clarify_vague_time_enabled"]),
                relative_time_exempt=bool(current["clarify_relative_time_exempt"]),
            )
            new = clarify_decision(
                t["question"], table_meta, semantic,
                metric_min=int(cand["clarify_metric_min"]),
                vague_time_enabled=bool(cand["clarify_vague_time_enabled"]),
                relative_time_exempt=bool(cand["clarify_relative_time_exempt"]),
            )
            if bool(old) != bool(new):
                diffs.append({
                    "trace_id": t["trace_id"],
                    "question": str(t["question"])[:80],
                    "old_action": "clarify" if old else "direct",
                    "new_action": "clarify" if new else "direct",
                    "success": bool(t.get("success")),
                })
        cand_knobs = cand
    else:
        mem_new = mem_cur
        cla_new = cla_cur
        diffs = []
        cand_knobs = None

    mem_gain = (
        mem_new["coverage"]["policy_hit_rate"] is not None
        and mem_cur["coverage"]["policy_hit_rate"] is not None
        and mem_new["coverage"]["policy_hit_rate"] > mem_cur["coverage"]["policy_hit_rate"]
    )
    mem_risk_ok = mem_new["like_regression_risk"]["no_hit"] <= mem_cur["like_regression_risk"]["no_hit"]
    cla_gain = (
        cla_new.get("agreement_rate") is not None
        and cla_cur.get("agreement_rate") is not None
        and cla_new["agreement_rate"] > cla_cur["agreement_rate"]
    )
    cla_fp_ok = cla_new.get("false_positive", 0) <= cla_cur.get("false_positive", 0)

    if not recommended:
        gate_ok = False
        gate_reason = "网格扫未发现优于现配置的操作点（当前配置已在前沿），保守保留"
    elif not mem_risk_ok:
        gate_ok = False
        gate_reason = "回放出现点赞轨迹召回退化，拒绝变更"
    elif not cla_fp_ok:
        gate_ok = False
        gate_reason = "回放误反问数上升，拒绝变更"
    elif not (mem_gain or cla_gain):
        gate_ok = False
        gate_reason = "回放无严格提升（覆盖率/一致率未增），保守保留"
    else:
        gate_ok = True
        gate_reason = "回放无退化且覆盖/一致率提升，允许固化配置"

    detail = {
        "corpus": corpus.get("stats"),
        "current_knobs": current,
        "candidate_knobs": cand_knobs,
        "memory": {
            "current": {k: mem_cur[k] for k in ("golden_self_recall", "coverage", "correction_repairable", "like_regression_risk")},
            "candidate": {k: mem_new[k] for k in ("golden_self_recall", "coverage", "correction_repairable", "like_regression_risk")},
            "sweep_recommended": mem_sweep.get("recommended"),
            "sweep_reason": mem_sweep.get("recommend_reason"),
        },
        "clarify": {
            "current": {k: cla_cur.get(k) for k in ("total", "agreement_rate", "false_positive", "false_negative", "actual_clarify", "predicted_clarify")},
            "candidate": {k: cla_new.get(k) for k in ("total", "agreement_rate", "false_positive", "false_negative", "actual_clarify", "predicted_clarify")},
            "sweep_recommended": cla_sweep.get("recommended"),
            "sweep_reason": cla_sweep.get("recommend_reason"),
        },
        "action_diffs": diffs[:50],
        "changed_count": len(diffs),
        "recommended": recommended or None,
        "gate": {"ok": bool(gate_ok), "reason": gate_reason},
    }
    return {
        "status": "done",
        "message": (
            f"回放 {corpus['stats']['traces']} 条轨迹：动作变化 {len(diffs)} 条；门禁：{gate_reason}"
        ),
        "detail": detail,
    }


async def _stage_traj_promote(db, job, source, agent) -> dict:
    """上线判定：门禁通过才把推荐 knobs 固化到 source.metadata_.policy_knobs（不改代码）。"""
    replay = ((job.detail or {}).get("replay") or {}) if isinstance(job.detail, dict) else {}
    gate = replay.get("gate") or {}
    rec = replay.get("recommended") or {}

    if not rec:
        return {
            "status": "done",
            "message": "未固化：回放无优于现配置的操作点，保留现配置",
            "detail": {"promoted": False, "reason": "no_recommendation"},
        }
    if not gate.get("ok"):
        return {
            "status": "done",
            "message": f"未固化：{gate.get('reason') or '回放门禁未通过'}，保留现配置",
            "detail": {"promoted": False, "reason": gate.get("reason"), "candidate": rec},
        }

    meta = dict(getattr(source, "metadata_", None) or {})
    knobs = dict(meta.get("policy_knobs") or {})
    knobs.update(rec)
    meta["policy_knobs"] = knobs
    source.metadata_ = meta
    await db.commit()
    applied = ", ".join(f"{k}={v}" for k, v in rec.items())
    return {
        "status": "done",
        "message": f"已固化配置：{applied}",
        "detail": {"promoted": True, "applied": rec, "policy_knobs": knobs},
    }


_STAGE_IMPL = {
    "collect": lambda db, job, source, agent:
        _stage_traj_collect(db, job, source, agent) if job.kind == "trajectory"
        else _stage_collect_for_prompt(db, job, source, agent) if job.kind == "prompt"
        else _stage_collect(db, job, source, agent),
    "normalize": _stage_traj_normalize,
    "metrics": _stage_traj_metrics,
    "replay": _stage_traj_replay,
    "traj_promote": _stage_traj_promote,
    "distill": _stage_distill,
    "prompt": _stage_prompt,
    "build_eval": _stage_build_eval,
    "candidate": _stage_candidate,
    "eval": _stage_eval,
    "promote": _stage_promote,
}


async def _run_job(job_id: str, from_stage: str | None = None) -> None:
    from app.db.models import TrainJob

    async with TrainSessionLocal() as db:
        job = await db.get(TrainJob, str(job_id))
        if not job:
            logger.warning("train_job_skip job=%s not found", job_id)
            return

        source, agent = await _resolve_target(db, job)
        if source is None:
            job.status = "failed"
            job.error = "训练对象不存在或数据源未绑定"
            job.stages = [
                {**s, "status": "failed" if i == 0 else "pending"}
                for i, s in enumerate(list(job.stages or []))
            ]
            await db.commit()
            return

        stages = list(job.stages or [])
        start = 0
        if from_stage:
            keys = [s.get("key") for s in stages]
            if from_stage in keys:
                start = keys.index(from_stage)

        job.status = "running"
        job.error = None
        job.stages = [dict(s) for s in stages]
        await db.commit()

        for i in range(start, len(stages)):
            st = stages[i]
            st.update({
                "status": "running", "progress": 5, "message": None,
                "started_at": _now(), "finished_at": None,
            })
            job.stage = st.get("key") or "unknown"
            job.stages = [dict(s) for s in stages]
            _recompute(job, stages)
            await db.commit()

            try:
                impl = _STAGE_IMPL.get(str(st.get("key")))
                if impl is None:
                    raise RuntimeError(f"未知阶段 {st.get('key')}")
                out = await impl(db, job, source, agent)
            except Exception as exc:
                logger.exception("train_job_stage_failed job=%s stage=%s", job_id, st.get("key"))
                await db.rollback()
                job = await db.get(TrainJob, str(job_id))
                stages = list(job.stages or [])
                if i < len(stages):
                    stages[i].update({
                        "status": "failed", "progress": 100,
                        "message": str(exc)[:500], "finished_at": _now(),
                    })
                job.stages = [dict(s) for s in stages]
                job.status = (
                    "partial"
                    if any(s.get("status") in ("done", "skipped") for s in stages)
                    else "failed"
                )
                job.error = str(exc)[:2000]
                _recompute(job, stages)
                job.progress = min(int(job.progress), 99)
                await db.commit()
                return

            status = str(out.get("status") or "done")
            st.update({
                "status": status, "progress": 100,
                "message": out.get("message"), "detail": out.get("detail"),
                "finished_at": _now(),
            })
            merged = dict(job.detail or {})
            merged[str(st.get("key"))] = out.get("detail")
            # P2 prompt 阶段产出的 candidate 要同时暴露到顶层，让 eval/promote 直接读
            if out.get("_top_level_candidate"):
                merged["candidate"] = out["_top_level_candidate"]
            job.detail = merged
            job.stages = [dict(s) for s in stages]
            _recompute(job, stages)
            await db.commit()

            if status == "failed":
                job.status = (
                    "partial"
                    if any(s.get("status") in ("done", "skipped") for s in stages)
                    else "failed"
                )
                job.error = str(out.get("message") or "阶段失败")[:2000]
                job.stages = [dict(s) for s in stages]
                await db.commit()
                return

        job.status = "done"
        job.stage = "done"
        job.progress = 100
        job.stages = [dict(s) for s in stages]
        await db.commit()
        logger.info("train_job_done job=%s target=%s/%s kind=%s",
                    job_id, job.target_type, job.target_id, job.kind)


async def _mark_fatal(job_id: str) -> None:
    from app.db.models import TrainJob

    async with TrainSessionLocal() as db:
        job = await db.get(TrainJob, str(job_id))
        if not job or job.status in ("done", "failed", "partial"):
            return
        stages = list(job.stages or [])
        for s in stages:
            if s.get("status") == "running":
                s.update({"status": "failed", "progress": 100, "finished_at": _now(),
                          "message": "任务异常中断"})
        job.stages = [dict(s) for s in stages]
        job.status = "partial" if any(s.get("status") in ("done", "skipped") for s in stages) else "failed"
        job.error = "任务异常中断，可从失败阶段重试"
        await db.commit()


@celery_app.task(name="train_center.run_job", ignore_result=True, max_retries=0)
def run_train_job(job_id: str, from_stage: str | None = None) -> None:
    try:
        run_in_persistent_loop(_run_job(job_id, from_stage))
    except Exception:
        logger.exception("train_job_task_failed job=%s", job_id)
        try:
            run_in_persistent_loop(_mark_fatal(job_id))
        except Exception:
            logger.exception("train_job_mark_fatal_failed job=%s", job_id)
