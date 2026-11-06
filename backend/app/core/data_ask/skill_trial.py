"""技能试运行与金标回归（蓝图 P2）。

试运行展示步骤和事实；include_answer 为真才生成结论文案。
回归只报告劣化，不阻断保存。带步骤的技能用算子事实核对期望数值，不走自由 SQL。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataSource, Skill, User

# 谭晓欢四问。期望值来自已核对的 Doris 日结。
BUILTIN_REGRESSION: list[tuple[str, list[str]]] = [
    ("2026年10月6日销售额是多少", ["177180.55"]),
    ("2026年10月6日毛利是多少", ["39400.9"]),
    ("2026年10月7日销售额和毛利是多少", ["210617.43", "14374.86"]),
    ("2026年10月11日销售额是多少", ["222674.02"]),
]


def skill_context(skill: Skill, metadata_override: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = metadata_override if isinstance(metadata_override, dict) else (
        skill.metadata_ if isinstance(skill.metadata_, dict) else {}
    )
    style = meta.get("answer_style") if isinstance(meta.get("answer_style"), dict) else {}
    steps = [s for s in (meta.get("steps") or []) if isinstance(s, dict)]
    return {
        "skill_id": skill.id,
        "slug": skill.slug,
        "display_name": skill.display_name,
        "version": skill.version or 1,
        "instructions_md": (skill.instructions_md or "")[:12000],
        "answer_style": style,
        "steps": steps,
    }


def expect_hit(blob: str, expect: str) -> bool:
    token = str(expect or "").strip()
    if not token:
        return True
    if token in blob:
        return True
    trimmed = token.rstrip("0").rstrip(".")
    return bool(trimmed) and trimmed in blob


def _blob(result: dict[str, Any]) -> str:
    return json.dumps(
        {"answer": result.get("answer"), "facts": result.get("facts")},
        ensure_ascii=False,
        default=str,
    )


async def _run_one(
    db: AsyncSession,
    *,
    source: DataSource,
    user: User | None,
    skill_ctx: dict[str, Any],
    question: str,
    include_answer: bool,
) -> dict[str, Any]:
    steps = skill_ctx.get("steps") or []
    if steps:
        from app.core.data_ask.analysis.orchestrator import run_skill_orchestration

        result = await run_skill_orchestration(
            db, source=source, question=question, user=user, skill_ctx=skill_ctx, conclude=include_answer,
        )
        return result
    if not include_answer:
        return {
            "answer": "",
            "facts": [],
            "steps_profile": [],
            "analysis_mode": "prompt_only",
            "note": "该技能没有步骤，试运行不会取数",
        }
    from app.core.data_ask.service import run_data_ask

    return await run_data_ask(
        db,
        data_source_id=str(source.id),
        question=question,
        user=user,
        skill_id=skill_ctx.get("skill_id"),
        execute=True,
    )


async def _isolated(db: AsyncSession, runner):
    """单题失败只回滚保存点，外层事务（例如正在发布的技能修订）保持有效。"""
    try:
        async with db.begin_nested():
            return await runner(), None
    except Exception as exc:
        return None, exc


async def dry_run_skill(
    db: AsyncSession,
    *,
    skill: Skill,
    source: DataSource,
    user: User | None,
    questions: list[str],
    include_answer: bool = False,
    metadata_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = skill_context(skill, metadata_override)
    items: list[dict[str, Any]] = []
    for question in questions[:5]:
        text = (question or "").strip()
        if not text:
            continue
        async def _once(question=text):
            return await _run_one(
                db, source=source, user=user, skill_ctx=ctx,
                question=question, include_answer=include_answer,
            )

        result, err = await _isolated(db, _once)
        if err is not None or result is None:
            items.append({
                "question": text,
                "ok": False,
                "facts": [],
                "steps_profile": [],
                "answer": "",
                "error": str(err or "")[:300],
            })
            continue
        profile = result.get("steps_profile") or []
        failed = [s for s in profile if isinstance(s, dict) and s.get("ok") is False]
        items.append({
            "question": text,
            "ok": not failed,
            "analysis_mode": result.get("analysis_mode"),
            "steps_profile": profile,
            "facts": result.get("facts") or [],
            "answer": result.get("answer") or "",
            "note": result.get("note"),
            "error": "；".join(str(s.get("error") or "") for s in failed) or None,
        })
    return {"skill_id": skill.id, "items": items}


def summarize_regression(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """给对话卡片和评测表用的短报告，不带整段事实。"""
    if not report:
        return None
    items = []
    for item in report.get("items") or []:
        items.append({
            "question": item.get("question"),
            "ok": bool(item.get("ok")),
            "missing": item.get("missing") or [],
            "error": item.get("error"),
        })
    total = int(report.get("total") or 0)
    passed = int(report.get("passed") or 0)
    return {
        "passed": passed,
        "total": total,
        "degraded": bool(report.get("degraded")) if total else True,
        "warning": report.get("warning"),
        "score": (passed / total) if total else 0.0,
        "items": items,
    }


async def record_regression_run(
    db: AsyncSession,
    *,
    data_source_id: str,
    agent_id: str | None,
    version_id: int | None,
    version: int | None,
    report: dict[str, Any],
    label: str,
) -> int | None:
    """写入 agent_eval_run 与质量分，供新旧版本对照。"""
    summary = summarize_regression(report)
    if summary is None or not summary["total"]:
        return None
    from app.db.models import AgentEvalRun, AgentQualityScore

    row = AgentEvalRun(
        data_source_id=str(data_source_id),
        agent_id=agent_id,
        agent_version_id=version_id,
        agent_version=version,
        trigger="release",
        status="done",
        total=summary["total"],
        passed=summary["passed"],
        consistency_rate=summary["score"],
        overall_score=summary["score"],
        items=summary["items"],
        note=label[:500],
    )
    db.add(row)
    await db.flush()
    db.add(AgentQualityScore(
        agent_id=agent_id,
        data_source_id=str(data_source_id),
        run_id=row.id,
        score=summary["score"],
        metrics={"passed": summary["passed"], "total": summary["total"], "label": label[:200]},
    ))
    await db.flush()
    return row.id


async def regress_skill(
    db: AsyncSession,
    *,
    skill: Skill,
    source: DataSource,
    user: User | None,
    questions: list[dict[str, Any]] | None = None,
    metadata_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """黄条报告：passed/total，degraded 为真时不阻断，只提示失败项。"""
    if questions:
        cases = [(str(q.get("question") or ""), [str(x) for x in (q.get("expect") or [])]) for q in questions]
    else:
        cases = list(BUILTIN_REGRESSION)
    cases = [(q, exp) for q, exp in cases if q.strip()][:8]
    ctx = skill_context(skill, metadata_override)
    items: list[dict[str, Any]] = []
    for question, expects in cases:
        async def _once(question=question):
            return await _run_one(
                db, source=source, user=user, skill_ctx=ctx,
                question=question, include_answer=not bool(ctx.get("steps")),
            )

        result, err = await _isolated(db, _once)
        if err is not None or result is None:
            items.append({
                "question": question,
                "ok": False,
                "missing": expects,
                "error": str(err or "")[:300],
            })
            continue
        blob = _blob(result)
        missing = [token for token in expects if not expect_hit(blob, token)]
        items.append({
            "question": question,
            "ok": not missing,
            "missing": missing,
            "facts": result.get("facts") or [],
            "answer_excerpt": str(result.get("answer") or "")[:240],
        })
    passed = sum(1 for item in items if item.get("ok"))
    return {
        "skill_id": skill.id,
        "passed": passed,
        "total": len(items),
        "degraded": passed < len(items),
        "warning": None if passed == len(items) else f"回归 {passed}/{len(items)}，有问句口径未对齐",
        "items": items,
    }
