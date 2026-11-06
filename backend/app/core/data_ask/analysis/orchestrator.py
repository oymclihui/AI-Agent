"""技能步骤编排执行器（蓝图《分析能力前台化》P1-②）。

技能 metadata_.steps 为线性步骤序列（蓝图 §5.1）：

    [
      {"tool": "metric_query", "params": {"metric": "销售额", "time_range": "$本月"}, "note": "可选步骤说明"},
      {"tool": "mom_compare",  "params": {"metric": "销售额", "time_range": "$最新日"}},
      {"prompt": "对比以上事实，指出下滑最明显的门店并给出可能原因"}
    ]

执行流程：
1. 逐步调用分析算子（operators.run_operator，治理链内嵌：sql_guard/列策略/行级权限/审计）；
2. prompt 步骤累积为结论生成的附加指令；
3. 汇总全部 facts → nl2sql.analyze_facts 生成最终结论（技能 answer_style 覆盖，与
   analyze_results 同一套 persona/format/grounding 机制）。

设计说明：steps 为线性序列，顺序执行器即可；若未来需要并行/条件分支，可将 steps
编译为 WorkflowGraph（core/workflow/engine.py）执行，本模块对外接口保持不变。
失败语义：单个算子步骤失败不终止整条编排（其余步骤照常执行，结论层如实说明），
全部步骤失败时返回确定性失败文案。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataSource, User

_MAX_STEP_ROWS = 30
_MAX_STEPS = 12


def _substitute(value: Any, question: str) -> Any:
    """params 中的 $问题 变量替换为当前问题文本（$本月/$最新日等时间窗变量由算子解析）。"""
    if isinstance(value, dict):
        return {k: _substitute(v, question) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, question) for v in value]
    if isinstance(value, str):
        return value.replace("$问题", question) if "$问题" in value else value
    return value


async def _emit(queue, payload: dict[str, Any]) -> None:
    if queue is not None:
        await queue.put(payload)


async def run_skill_orchestration(
    db: AsyncSession,
    *,
    source: DataSource,
    question: str,
    user: User | None,
    skill_ctx: dict[str, Any],
    llm_provider: str | None = None,
    llm_model: str | None = None,
    agent_goal: str | None = None,
    agent_backstory: str | None = None,
    stage_queue=None,
    trace_marks: dict[str, Any] | None = None,
    conclude: bool = True,
) -> dict[str, Any]:
    """执行技能 steps：逐步算子取 facts → 汇总 → LLM 结论生成。

    conclude=False 时只返回步骤和事实，不调用结论模型（试运行、回归取数用）。
    """
    from app.core.data_ask.analysis.operators import run_operator

    steps = [s for s in (skill_ctx.get("steps") or []) if isinstance(s, dict)][:_MAX_STEPS]
    if not steps:
        raise ValueError("技能未配置有效步骤（metadata_.steps 为空）")

    facts_all: list[dict[str, Any]] = []
    rows_all: list[dict[str, Any]] = []
    sqls: list[str] = []
    step_reports: list[dict[str, Any]] = []
    final_prompts: list[str] = []

    for idx, step in enumerate(steps, 1):
        if step.get("prompt"):
            final_prompts.append(str(step["prompt"]).strip())
            step_reports.append({"step": idx, "kind": "prompt"})
            continue
        op = str(step.get("tool") or "").strip()
        if not op:
            continue
        params = _substitute(dict(step.get("params") or {}), question)
        await _emit(stage_queue, {
            "event": "skill_step", "step": idx, "tool": op,
            "note": str(step.get("note") or "") or None,
        })
        try:
            out = await run_operator(
                db, operator=op, data_source_id=str(source.id), params=params, user=user,
            )
        except ValueError as exc:
            step_reports.append({"step": idx, "tool": op, "ok": False, "error": str(exc)[:300]})
            await _emit(stage_queue, {
                "event": "skill_step", "step": idx, "tool": op, "ok": False,
                "error": str(exc)[:200],
            })
            continue
        facts = out.get("facts") or []
        step_reports.append({
            "step": idx, "tool": op, "ok": True,
            "facts": len(facts), "rows": out.get("row_count") or 0,
        })
        facts_all.extend(facts)
        rows_all.extend((out.get("rows") or [])[:_MAX_STEP_ROWS])
        if out.get("sql"):
            sqls.append(str(out["sql"]))
        await _emit(stage_queue, {
            "event": "skill_step", "step": idx, "tool": op, "ok": True, "facts": len(facts),
        })

    if trace_marks is not None:
        trace_marks.setdefault("skill_steps", step_reports)

    if not facts_all:
        failed = [r for r in step_reports if r.get("ok") is False]
        reasons = "；".join(f"步骤{r['step']}({r.get('tool')})：{r.get('error')}" for r in failed[:3])
        answer = (
            f"技能「{skill_ctx.get('display_name') or ''}」的取数步骤未产出任何事实，"
            f"暂无法生成结论。{('失败原因：' + reasons) if reasons else ''}"
        )
        return {
            "answer": answer,
            "sql": ";\n".join(sqls),
            "display_sql": "",
            "explanation": "",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "chart": None,
            "analysis_mode": "skill_orchestration",
            "standalone_question": question,
            "steps_profile": step_reports,
            "facts": [],
            "detail_rows": [],
        }

    if not conclude:
        return {
            "answer": "",
            "sql": ";\n".join(sqls)[:8000],
            "display_sql": "",
            "explanation": "",
            "columns": [],
            "rows": [],
            "row_count": len(rows_all),
            "truncated": False,
            "chart": None,
            "analysis_mode": "skill_orchestration",
            "standalone_question": question,
            "steps_profile": step_reports,
            "facts": facts_all,
            "detail_rows": rows_all[:_MAX_STEP_ROWS],
        }

    # 结论生成：facts + 明细 + 步骤附加指令 → analyze_facts（技能风格覆盖）
    from app.core.data_ask.intelligence.nl2sql import analyze_facts

    answer = await analyze_facts(
        db,
        question=question,
        facts=facts_all,
        rows=rows_all[:_MAX_STEP_ROWS],
        step_reports=step_reports,
        final_prompts=final_prompts,
        llm_provider=llm_provider,
        llm_model=llm_model,
        user_id=user.id if user else None,
        agent_goal=agent_goal,
        agent_backstory=agent_backstory,
        skill_style=skill_ctx,
    )
    return {
        "answer": answer,
        "sql": ";\n".join(sqls)[:8000],
        "display_sql": "",
        "explanation": "",
        "columns": [],
        "rows": [],
        "row_count": len(rows_all),
        "truncated": False,
        "chart": None,
        "analysis_mode": "skill_orchestration",
        "standalone_question": question,
        "steps_profile": step_reports,
        "facts": facts_all,
        "detail_rows": rows_all[:_MAX_STEP_ROWS],
    }
