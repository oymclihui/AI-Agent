"""对话内技能版本操作（蓝图 §12）。

发布 / 回滚 / 对比走现有 agent_version + agent_release，不另建版本表。
技能正文在用户说「发布」之后才写入 Skill；回滚按发布时留下的 before_skill 还原。
发布前跑金标回归：通过写进回执，劣化只警告，不拦住发布。
「效果对比」对上一版和当前草案（或已发布版）各跑同一套题，并写入评测记录。
"""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.chat.reflector import (
    build_proposal,
    parse_command,
    parse_revision,
    render_proposal,
)
from app.db.models import Agent as AgentModel
from app.db.models import AgentVersion, AskTrace, DataSource, DigitalEmployee, Skill, User


def _card(answer: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "answer": answer,
        "sql": "",
        "display_sql": "",
        "explanation": "",
        "columns": [],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "chart": None,
        "analysis_mode": "skill_revision",
        "answer_mode": "L1",
        "standalone_question": "",
        "skill_revision": extra or None,
    }
    return payload


def pack_skill(skill: Skill) -> dict[str, Any]:
    return {
        "skill_id": skill.id,
        "display_name": skill.display_name,
        "version": skill.version or 1,
        "metadata_": copy.deepcopy(skill.metadata_ if isinstance(skill.metadata_, dict) else {}),
        "instructions_md": skill.instructions_md or "",
        "tools_required": list(skill.tools_required or []),
    }


def apply_skill_pack(skill: Skill, pack: dict[str, Any]) -> None:
    skill.metadata_ = copy.deepcopy(pack.get("metadata_") or {})
    if pack.get("instructions_md") is not None:
        skill.instructions_md = pack.get("instructions_md") or ""
    skill.tools_required = list(pack.get("tools_required") or [])
    skill.version = (skill.version or 1) + 1


def _revision_of(row: AgentVersion | None) -> dict[str, Any]:
    if row is None or not isinstance(row.spec, dict):
        return {}
    rev = row.spec.get("skill_revision")
    return dict(rev) if isinstance(rev, dict) else {}


def _tools_from_meta(meta: dict[str, Any]) -> list[str]:
    tools: list[str] = []
    for step in meta.get("steps") or []:
        if isinstance(step, dict) and step.get("tool"):
            tools.append(str(step["tool"]))
    return tools


async def resolve_agent(
    db: AsyncSession,
    source: DataSource,
    employee_id: str | None,
) -> AgentModel | None:
    if employee_id:
        employee = await db.get(DigitalEmployee, employee_id)
        if employee and employee.agent_id:
            agent = await db.get(AgentModel, employee.agent_id)
            if agent:
                return agent
    if source.agent_id:
        return await db.get(AgentModel, source.agent_id)
    return None


async def resolve_skill(
    db: AsyncSession,
    *,
    skill_ctx: dict[str, Any] | None,
    skill_id: str | None,
    user: User | None,
    data_source_id: str,
) -> Skill | None:
    sid = (skill_ctx or {}).get("skill_id") or skill_id
    if not sid and user is not None:
        from sqlalchemy import select

        row = (await db.execute(
            select(AskTrace)
            .where(
                AskTrace.data_source_id == str(data_source_id),
                AskTrace.user_id == str(user.id),
                AskTrace.skill_id.is_not(None),
            )
            .order_by(AskTrace.id.desc())
            .limit(1)
        )).scalar_one_or_none()
        sid = row.skill_id if row else None
    if not sid:
        return None
    skill = await db.get(Skill, sid)
    if not skill:
        return None
    status = getattr(skill.status, "value", skill.status)
    if str(status) != "active":
        return None
    return skill


async def _latest_candidate(
    db: AsyncSession,
    agent_id: str,
    skill_id: str | None,
) -> AgentVersion | None:
    from app.core.data_ask.factory import versioning

    rows = await versioning.list_versions(db, agent_id)
    for row in rows:
        if row.status != "candidate" or row.source != "feedback":
            continue
        rev = _revision_of(row)
        if skill_id and rev.get("skill_id") != skill_id:
            continue
        if rev.get("skill_id"):
            return row
    return None


async def draft_revision(
    db: AsyncSession,
    *,
    agent: AgentModel,
    skill: Skill,
    proposal: dict[str, Any],
    user: User | None,
    data_source_id: str,
) -> AgentVersion:
    from app.core.data_ask.factory import versioning

    before = pack_skill(skill)
    active = await versioning.active_version(db, str(agent.id))
    if active is None:
        base_spec = versioning.agent_spec(agent)
        base_spec["skill_revision"] = before
        base = await versioning.snapshot(
            db, agent, source="feedback", status="candidate",
            spec=base_spec, note="对话修订前的技能基线",
        )
        base.data_source_id = str(data_source_id)
        await versioning.promote(db, agent, base)
        await versioning.release(db, agent, base, user=user, note="技能修订基线")

    spec = versioning.agent_spec(agent)
    after = copy.deepcopy(before)
    after["metadata_"] = proposal["metadata_after"]
    after["tools_required"] = _tools_from_meta(proposal["metadata_after"]) or after["tools_required"]
    spec["skill_revision"] = after
    row = await versioning.snapshot(
        db, agent, source="feedback", status="candidate", spec=spec,
        note=f"对话起草技能修订：{skill.display_name}"[:500],
        coach={"before_skill": before, "changes": proposal.get("changes") or []},
    )
    row.data_source_id = str(data_source_id)
    await db.flush()
    return row


def _regression_sentence(summary: dict[str, Any] | None) -> str:
    if not summary or not summary.get("total"):
        warning = (summary or {}).get("warning")
        return f"{warning}。" if warning else "未跑回归。"
    if summary.get("degraded"):
        failed = [str(item.get("question") or "") for item in summary.get("items") or [] if not item.get("ok")]
        names = "、".join(name for name in failed[:2] if name)
        detail = f"未对齐：{names}。" if names else ""
        return f"回归 {summary['passed']}/{summary['total']}，{detail}建议查看失败项后再决定，"
    return f"回归 {summary['passed']}/{summary['total']} 通过。"


async def _run_gate(
    db: AsyncSession,
    *,
    skill: Skill,
    source: DataSource | None,
    user: User | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    from app.core.data_ask.skill_trial import regress_skill, summarize_regression

    if source is None:
        return {"passed": 0, "total": 0, "degraded": True, "warning": "未绑定数据源，未跑回归", "items": []}
    try:
        report = await regress_skill(
            db, skill=skill, source=source, user=user, metadata_override=metadata,
        )
    except Exception as exc:
        return {
            "passed": 0, "total": 0, "degraded": True,
            "warning": f"回归未完成：{exc}"[:200], "items": [],
        }
    return summarize_regression(report)


async def publish_pending(
    db: AsyncSession,
    *,
    agent: AgentModel,
    user: User | None,
    skill_id: str | None,
    source: DataSource | None = None,
) -> dict[str, Any]:
    from app.core.data_ask.factory import versioning
    from app.core.data_ask.skill_trial import record_regression_run

    target = await _latest_candidate(db, str(agent.id), skill_id)
    if target is None:
        return _card("没有待发布的技能修改。可以先说明要怎么改，例如「先看同比，再看门店排名」。")
    rev = _revision_of(target)
    skill = await db.get(Skill, rev.get("skill_id"))
    if skill is None:
        return _card("草案指向的技能已经不存在，无法发布。")
    meta = rev.get("metadata_") if isinstance(rev.get("metadata_"), dict) else {}
    ds = source
    ds_id = getattr(target, "data_source_id", None)
    if ds is None and ds_id:
        ds = await db.get(DataSource, ds_id)
    summary = await _run_gate(db, skill=skill, source=ds, user=user, metadata=meta)
    skill.metadata_ = copy.deepcopy(meta)
    tools = _tools_from_meta(meta)
    if tools:
        skill.tools_required = tools
    skill.version = (skill.version or 1) + 1
    rev["version"] = skill.version
    spec = dict(target.spec or {})
    spec["skill_revision"] = rev
    target.spec = spec
    versioning.apply_spec(agent, spec)
    await db.flush()
    await versioning.promote(db, agent, target)
    await versioning.release(db, agent, target, user=user, note="对话发布技能修订")
    if summary and summary.get("total") and ds is not None:
        await record_regression_run(
            db,
            data_source_id=str(ds.id),
            agent_id=str(agent.id),
            version_id=target.id,
            version=target.version,
            report=summary,
            label=f"发布门禁 v{target.version}",
        )
    sentence = _regression_sentence(summary)
    return _card(
        f"v{target.version} 已生效。技能「{skill.display_name}」现在按新步骤分析。{sentence}可以说「回滚上一版」或「效果对比」。",
        version=target.version,
        skill_id=skill.id,
        applied=True,
        regression=summary,
    )


async def discard_pending(
    db: AsyncSession,
    *,
    agent: AgentModel,
    skill_id: str | None,
) -> dict[str, Any]:
    target = await _latest_candidate(db, str(agent.id), skill_id)
    if target is None:
        return _card("没有待放弃的草案。")
    target.status = "retired"
    target.note = ((target.note or "") + "（已取消）")[:500]
    await db.flush()
    return _card(f"已放弃草稿 v{target.version}，技能未改动。")


async def rollback_previous(
    db: AsyncSession,
    *,
    agent: AgentModel,
    user: User | None,
) -> dict[str, Any]:
    from app.core.data_ask.factory import versioning

    if user is None:
        return _card("回滚需要登录用户。")
    current = await versioning.active_version(db, str(agent.id))
    if current is None:
        return _card("还没有可回滚的版本。")
    before = (current.coach or {}).get("before_skill") if isinstance(current.coach, dict) else None
    rows = await versioning.list_versions(db, str(agent.id))
    older = next((row for row in rows if row.version < current.version), None)
    if not isinstance(before, dict) or not before.get("skill_id"):
        if older is None:
            return _card("上一版没有技能快照，无法回滚。")
        before = _revision_of(older)
    skill = await db.get(Skill, before.get("skill_id")) if before.get("skill_id") else None
    if skill is None or older is None:
        return _card("上一版没有可还原的技能内容。")
    apply_skill_pack(skill, before)
    new_row = await versioning.rollback(db, agent, older, user=user, note="对话回滚上一版")
    spec = dict(new_row.spec or {})
    spec["skill_revision"] = pack_skill(skill)
    new_row.spec = spec
    await db.flush()
    return _card(
        f"已回滚。技能「{skill.display_name}」恢复到 v{older.version} 的内容，当前版本 v{new_row.version}。",
        version=new_row.version,
        skill_id=skill.id,
        rolled_back_to=older.version,
    )


async def diff_versions(
    db: AsyncSession,
    *,
    agent: AgentModel,
    versions: list[int],
) -> dict[str, Any]:
    from app.core.chat.reflector import _step_brief
    from app.core.data_ask.factory import versioning

    rows = await versioning.list_versions(db, str(agent.id))
    left = next((row for row in rows if row.version == versions[0]), None)
    right = next((row for row in rows if row.version == versions[1]), None)
    if left is None or right is None:
        return _card(f"没有找到 v{versions[0]} 或 v{versions[1]}。")
    lrev = _revision_of(left)
    rrev = _revision_of(right)
    lsteps = (lrev.get("metadata_") or {}).get("steps") if isinstance(lrev.get("metadata_"), dict) else None
    rsteps = (rrev.get("metadata_") or {}).get("steps") if isinstance(rrev.get("metadata_"), dict) else None
    items = versioning.diff_specs(left.spec, right.spec)
    changed = [item["field"] for item in items if item.get("changed")]
    lines = [
        f"v{left.version} 对比 v{right.version}：",
        f"步骤：{_step_brief(lsteps)} → {_step_brief(rsteps)}",
        "变更字段：" + ("、".join(changed) if changed else "无"),
    ]
    return _card("\n".join(lines), versions=[left.version, right.version], changed=changed)


async def compare_effect(
    db: AsyncSession,
    *,
    agent: AgentModel,
    user: User | None,
    source: DataSource | None,
    skill_id: str | None,
) -> dict[str, Any]:
    """新旧两版各跑同一套金标，写出质量分。不改技能。"""
    from app.core.data_ask.factory import versioning
    from app.core.data_ask.skill_trial import record_regression_run

    candidate = await _latest_candidate(db, str(agent.id), skill_id)
    if candidate is not None:
        after = _revision_of(candidate)
        before = (candidate.coach or {}).get("before_skill") if isinstance(candidate.coach, dict) else None
        right_label = f"草案 v{candidate.version}"
        right_row = candidate
        advice_low = "草案分数更低，建议先「取消」或改完再说「发布」。"
        advice_high = "草案分数更高，可以说「发布」保留。"
    else:
        current = await versioning.active_version(db, str(agent.id))
        after = _revision_of(current)
        before = (current.coach or {}).get("before_skill") if current is not None and isinstance(current.coach, dict) else None
        right_label = f"当前 v{current.version}" if current is not None else "当前版"
        right_row = current
        advice_low = "当前版分数更低，可以说「回滚上一版」。"
        advice_high = "当前版分数更高，建议保留。"
    if not isinstance(before, dict) or not before.get("metadata_") or not after.get("metadata_"):
        return _card("没有可对比的新旧两版。先说明要怎么改，或发布后再说「效果对比」。")
    skill = await db.get(Skill, after.get("skill_id") or before.get("skill_id"))
    if skill is None:
        return _card("对比用的技能已经不存在。")
    ds = source
    if ds is None and right_row is not None and getattr(right_row, "data_source_id", None):
        ds = await db.get(DataSource, right_row.data_source_id)
    left = await _run_gate(db, skill=skill, source=ds, user=user, metadata=before.get("metadata_"))
    right = await _run_gate(db, skill=skill, source=ds, user=user, metadata=after.get("metadata_"))
    if ds is not None and right_row is not None:
        await record_regression_run(
            db, data_source_id=str(ds.id), agent_id=str(agent.id),
            version_id=right_row.id, version=right_row.version,
            report=left or {}, label="效果对比·上一版",
        )
        await record_regression_run(
            db, data_source_id=str(ds.id), agent_id=str(agent.id),
            version_id=right_row.id, version=right_row.version,
            report=right or {}, label="效果对比·" + right_label,
        )
    left_score = (left or {}).get("score") or 0
    right_score = (right or {}).get("score") or 0
    if right_score > left_score:
        advice = advice_high
    elif right_score < left_score:
        advice = advice_low
    else:
        advice = "两版持平。"
    lines = [
        "效果对比（同一套金标）：",
        f"上一版 {int((left or {}).get('passed') or 0)}/{int((left or {}).get('total') or 0)}，质量分 {left_score:.0%}",
        f"{right_label} {int((right or {}).get('passed') or 0)}/{int((right or {}).get('total') or 0)}，质量分 {right_score:.0%}",
        advice,
    ]
    return _card(
        "\n".join(lines),
        regression={"before": left, "after": right},
        applied=False,
    )


async def handle_skill_dialogue(
    db: AsyncSession,
    *,
    source: DataSource,
    question: str,
    user: User | None,
    employee_id: str | None = None,
    skill_id: str | None = None,
    skill_ctx: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """问数入口调用。不是修改意见或版本指令时返回 None，主链路保持原样。"""
    command = parse_command(question)
    revision = None if command else parse_revision(question)
    if command is None and revision is None:
        return None

    agent = await resolve_agent(db, source, employee_id)
    if agent is None:
        return _card("当前数字员工和数据源都没有绑定智能体，无法记录可回滚的版本。")

    bound_skill = (skill_ctx or {}).get("skill_id") or skill_id
    if command:
        op = command["op"]
        if op == "publish":
            result = await publish_pending(
                db, agent=agent, user=user, skill_id=bound_skill, source=source,
            )
        elif op == "ab":
            result = await compare_effect(
                db, agent=agent, user=user, source=source, skill_id=bound_skill,
            )
        elif op == "rollback":
            result = await rollback_previous(db, agent=agent, user=user)
        elif op == "discard":
            result = await discard_pending(db, agent=agent, skill_id=bound_skill)
        else:
            result = await diff_versions(db, agent=agent, versions=command.get("versions") or [])
        result["standalone_question"] = question
        return result

    skill = await resolve_skill(
        db, skill_ctx=skill_ctx, skill_id=skill_id, user=user, data_source_id=str(source.id),
    )
    if skill is None:
        return _card("没有找到要修改的分析技能。请指定技能，或先用绑定了分析技能的数字员工提问。")
    proposal = build_proposal(skill, revision or {})
    if not proposal["changes"]:
        return _card("听出了修改意图，但没有对应到步骤、口径、人设或触发词。可以说「先看同比，再看门店排名」。")
    row = await draft_revision(
        db, agent=agent, skill=skill, proposal=proposal, user=user, data_source_id=str(source.id),
    )
    result = _card(
        render_proposal(proposal, version=row.version),
        version=row.version,
        skill_id=skill.id,
        changes=proposal["changes"],
        applied=False,
    )
    result["standalone_question"] = question
    return result
