"""Conversation deposit: suggest, draft preview, and confirmed publish to skill/KB/agent/employee."""
from __future__ import annotations

import json
from typing import Any, Literal, Optional

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.chat.export import (
    _format_transcript,
    materialize_knowledge_from_spec,
    materialize_skill_from_spec,
)
from app.core.employees.schedule import compute_next_run, validate_schedule
from app.db.base import generate_uuid
from app.db.models import (
    Agent as AgentModel,
    Conversation,
    DigitalEmployee,
    EmployeeScheduledTask,
    EmployeeStatus,
    EmployeeTaskType,
    Message,
    ScheduleType,
    Skill,
)

logger = structlog.get_logger(__name__)

DepositType = Literal["skill", "knowledge", "agent", "employee"]


def _append_skill_binding(conv: Conversation, skill_id: str) -> None:
    bindings = list(conv.skills_config or [])
    if any(isinstance(b, dict) and b.get("skill_id") == skill_id for b in bindings):
        return
    bindings.append({"skill_id": skill_id, "always_load": True, "priority": len(bindings)})
    conv.skills_config = bindings


def _append_kb_id(conv: Conversation, kb_id: str) -> None:
    ids = list(conv.knowledge_base_ids or [])
    if kb_id not in ids:
        ids.append(kb_id)
    conv.knowledge_base_ids = ids


def _merge_skill_id_lists(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for sid in group:
            if sid and sid not in seen:
                seen.add(sid)
                merged.append(sid)
    return merged


def _skill_ids_from_conv(conv: Conversation) -> list[str]:
    ids: list[str] = []
    for item in conv.skills_config or []:
        if isinstance(item, dict) and item.get("skill_id"):
            ids.append(str(item["skill_id"]))
        elif isinstance(item, str):
            ids.append(item)
    return ids


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None


async def _load_transcript(db: AsyncSession, conv_id: str) -> tuple[list[Message], str]:
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()
    return messages, _format_transcript(messages)


async def analyze_conversation_deposit(
    db: AsyncSession,
    conv: Conversation,
    user_id: str,
    *,
    lang: str = "zh",
) -> dict[str, Any]:
    """Analyze transcript and store a deposit draft on the conversation metadata."""
    from app.models_hub.router import ModelRouter

    messages, transcript = await _load_transcript(db, conv.id)
    if len(messages) < 2:
        return {"worth_deposit": False, "suggestions": [], "draft_id": None, "draft": None}

    llm = await ModelRouter.get_llm(db=db, user_id=user_id, temperature=0.2)
    lang_hint = "中文" if lang == "zh" else "English"
    system = (
        "你是企业 AI 上岗顾问。根据对话判断用户是否完成了可复用的工作（SOP、知识、岗位、定时任务）。"
        "只输出 JSON，不要 Markdown。"
    )
    domain_hint = ""
    transcript_lower = transcript.lower()
    if any(
        k in transcript_lower
        for k in (
            "整车", "车企", "制造", "比亚迪", "oem",
            "cfo", "财务vp", "司库", "fp&a", "管报", "单车成本", "双积分",
        )
    ):
        domain_hint = """
【行业上下文：制造企业集团财务】
若对话涉及该领域，employee 草案应贴近真实岗位层级，例如：
- 上层：CFO（月度董事会材料）、财务 VP（周例会）
- 中层：财务控制/制造 controller（日/周监控）、司库（资金/汇兑周报）
- 业务财务：FP&A 滚动预测、成本会计（单台/BOM/降本）、税务与政策
task_config.prompt 须包含：多业务板块、多基地、出口汇兑、政策补贴等语境；
cron 建议：日监控 工作日 7:00、周例会 周一 8–10:00、月报 每月 3–5 日。
agent.role/goal 用中英混合或中文，体现制造业财务专业度。
"""
    if any(
        k in transcript_lower
        for k in ("sidecar", "桌面", "录制", "回放", "sap gui", "openadapt", "desktop", "gui")
    ):
        domain_hint += """
【桌面自动化上下文】
若对话涉及桌面 GUI 录制/回放/SAP/Excel 桌面操作：
- 推荐 skill（GUI 操作 SOP）+ knowledge（演示步骤文档）
- agent 工具应含 desktop_list_demos, desktop_replay, desktop_capture
- employee 任务可用 task_type: "desktop_automation"，task_config 示例：
  {"demo_name": "演示名称", "instructions": "可选补充说明", "timeout_s": 120}
- 需提醒用户在本机运行 scripts/desktop_sidecar.py
"""
    user_prompt = f"""分析以下对话，判断值得沉淀的内容。输出语言：{lang_hint}。
{domain_hint}
对话记录：
{transcript[:80000]}

JSON schema:
{{
  "worth_deposit": true/false,
  "suggestions": [
    {{
      "type": "skill|knowledge|agent|employee",
      "recommended": true/false,
      "title": "简短标题",
      "reason": "推荐理由（一句话）",
      "confidence": 0.0-1.0
    }}
  ],
    "draft": {{
    "skill": {{"display_name": "...", "description": "...", "instructions_md": "完整 SOP Markdown"}},
    "knowledge": {{"kb_name": "...", "summary": "...", "document_md": "完整知识 Markdown"}},
    "agent": {{
      "name": "中文名",
      "role": "English role",
      "goal": "中文目标",
      "backstory": "中文背景",
      "tools": ["web_search", "fetch_mail"],
      "temperature": 0.7
    }},
    "employee": {{
      "name": "员工名",
      "title": "岗位",
      "description": "职责描述",
      "timezone": "Asia/Shanghai",
      "tasks": [
        {{
          "name": "任务名",
          "schedule_type": "cron",
          "cron_expression": "0 9 * * 1",
          "schedule_label": "每周一 09:00",
          "task_type": "agent|desktop_automation",
          "task_config": {{"prompt": "定时执行的完整指令"}} 或 {{"demo_name": "...", "instructions": "..."}}
        }}
      ]
    }}
  }}
}}

规则：
- 若对话只是一次性简单问答，worth_deposit=false，suggestions 为空。
- 若出现重复性工作、岗位描述、周报/日报、定时需求，推荐 employee 并给出合理 cron（工作日 9:00 等）。
- employee 的 task_config.prompt 必须可独立执行（agent 任务）；desktop_automation 任务用 demo_name/demo_id。
- cron_expression 使用标准 5 段 cron（分 时 日 月 周）。
- skill.instructions_md 与 knowledge.document_md 必须可直接发布，无需二次生成。
"""
    response = await llm.ainvoke([
        SystemMessage(content=system),
        HumanMessage(content=user_prompt),
    ])
    spec = _extract_json(response.content or "") or {}
    worth = bool(spec.get("worth_deposit"))
    suggestions = spec.get("suggestions") if isinstance(spec.get("suggestions"), list) else []
    draft_body = spec.get("draft") if isinstance(spec.get("draft"), dict) else {}

    if not worth or not suggestions:
        meta = dict(conv.metadata_ or {})
        meta.pop("deposit_draft", None)
        conv.metadata_ = meta
        return {"worth_deposit": False, "suggestions": [], "draft_id": None, "draft": None}

    draft_id = generate_uuid()
    draft_record = {
        "draft_id": draft_id,
        "lang": lang,
        "suggestions": suggestions,
        "draft": draft_body,
        "source_conversation_id": conv.id,
    }
    meta = dict(conv.metadata_ or {})
    meta["deposit_draft"] = draft_record
    conv.metadata_ = meta
    await db.flush()

    tasks_preview = []
    emp = draft_body.get("employee") if isinstance(draft_body.get("employee"), dict) else {}
    for t in emp.get("tasks") or []:
        if isinstance(t, dict):
            prompt = (t.get("task_config") or {}).get("prompt", "")
            tasks_preview.append({
                "name": t.get("name", ""),
                "schedule_type": t.get("schedule_type", "cron"),
                "cron_expression": t.get("cron_expression"),
                "schedule_label": t.get("schedule_label"),
                "prompt_preview": (prompt[:200] + "…") if len(prompt) > 200 else prompt,
            })

    skill = draft_body.get("skill") if isinstance(draft_body.get("skill"), dict) else {}
    kb = draft_body.get("knowledge") if isinstance(draft_body.get("knowledge"), dict) else {}
    agent = draft_body.get("agent") if isinstance(draft_body.get("agent"), dict) else {}

    return {
        "worth_deposit": True,
        "draft_id": draft_id,
        "suggestions": suggestions,
        "draft": {
            "skill_title": skill.get("display_name"),
            "knowledge_title": kb.get("kb_name"),
            "agent_name": agent.get("name"),
            "employee_name": emp.get("name"),
            "employee_title": emp.get("title"),
            "employee_description": emp.get("description"),
            "tasks": tasks_preview,
        },
    }


async def _create_agent_from_draft(
    db: AsyncSession,
    conv: Conversation,
    user_id: str,
    agent_spec: dict[str, Any],
    skill_ids: list[str],
) -> AgentModel:
    tools_config = [{"tool_name": t} for t in agent_spec.get("tools", []) if isinstance(t, str)]
    skills_config = [{"skill_id": sid, "always_load": True, "priority": i} for i, sid in enumerate(skill_ids)]
    agent = AgentModel(
        id=generate_uuid(),
        owner_id=user_id,
        name=str(agent_spec.get("name") or "对话智能体")[:255],
        role=str(agent_spec.get("role") or "Assistant")[:255],
        goal=str(agent_spec.get("goal") or conv.title or "协助用户完成对话中的任务")[:2000],
        backstory=str(agent_spec.get("backstory") or "")[:4000],
        llm_provider=settings.DEFAULT_LLM_PROVIDER,
        llm_model=settings.DEFAULT_LLM_MODEL,
        temperature=float(agent_spec.get("temperature", 0.7)),
        max_iterations=10,
        tools_config=tools_config,
        skills_config=skills_config,
        memory_config={},
        metadata_={"source_conversation_id": conv.id, "from_deposit": True},
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return agent


async def _create_employee_from_draft(
    db: AsyncSession,
    conv: Conversation,
    user_id: str,
    emp_spec: dict[str, Any],
    agent_id: str,
    skill_ids: list[str],
    *,
    knowledge_base_ids: list[str] | None = None,
    activate: bool = True,
) -> tuple[DigitalEmployee, int]:
    from app.db.models import User as UserModel

    owner = await db.get(UserModel, user_id)
    skills_config = [{"skill_id": sid, "always_load": True, "priority": i} for i, sid in enumerate(skill_ids)]
    emp = DigitalEmployee(
        id=generate_uuid(),
        owner_id=user_id,
        department_id=owner.primary_department_id if owner else None,
        name=str(emp_spec.get("name") or "对话数字员工")[:255],
        title=(emp_spec.get("title") or None),
        description=emp_spec.get("description"),
        status=EmployeeStatus.active if activate else EmployeeStatus.paused,
        agent_id=agent_id,
        skills_config=skills_config,
        knowledge_base_ids=knowledge_base_ids or list(conv.knowledge_base_ids or []),
        timezone=str(emp_spec.get("timezone") or "Asia/Shanghai"),
        metadata_={
            "source_conversation_id": conv.id,
            "from_deposit": True,
            "draft_until_confirm": not activate,
        },
    )
    db.add(emp)
    await db.flush()

    tasks_created = 0
    for raw_task in emp_spec.get("tasks") or []:
        if not isinstance(raw_task, dict):
            continue
        st = str(raw_task.get("schedule_type") or "cron")
        cron = raw_task.get("cron_expression")
        interval = raw_task.get("interval_seconds")
        validate_schedule(st, cron, interval)
        raw_type = str(raw_task.get("task_type") or "agent")
        try:
            task_type = EmployeeTaskType(raw_type)
        except ValueError:
            task_type = EmployeeTaskType.agent
        task = EmployeeScheduledTask(
            id=generate_uuid(),
            employee_id=emp.id,
            name=str(raw_task.get("name") or "定时任务")[:255],
            description=raw_task.get("description"),
            enabled=activate,
            schedule_type=ScheduleType.cron if st == "cron" else ScheduleType.interval,
            cron_expression=cron,
            interval_seconds=interval,
            timezone=str(emp_spec.get("timezone") or "Asia/Shanghai"),
            task_type=task_type,
            task_config=raw_task.get("task_config") if isinstance(raw_task.get("task_config"), dict) else {},
            metadata_={"source_conversation_id": conv.id},
        )
        if task.enabled:
            task.next_run_at = compute_next_run(
                st,
                cron_expression=task.cron_expression,
                interval_seconds=task.interval_seconds,
                timezone_name=task.timezone,
            )
        db.add(task)
        tasks_created += 1

    await db.flush()
    await db.refresh(emp)
    return emp, tasks_created


async def confirm_conversation_deposit(
    db: AsyncSession,
    conv: Conversation,
    user_id: str,
    *,
    draft_id: str,
    types: list[DepositType],
    activate_employee: bool = True,
    kb_id: Optional[str] = None,
    kb_name: Optional[str] = None,
    skill_title: Optional[str] = None,
) -> dict[str, Any]:
    meta = conv.metadata_ or {}
    draft_record = meta.get("deposit_draft")
    if not draft_record or draft_record.get("draft_id") != draft_id:
        raise ValueError("Deposit draft not found or expired. Run suggest-deposit again.")

    draft_body = draft_record.get("draft") if isinstance(draft_record.get("draft"), dict) else {}
    selected = set(types)
    if "employee" in selected and "agent" not in selected:
        selected.add("agent")

    result: dict[str, Any] = {
        "skill_id": None,
        "knowledge_base_id": None,
        "agent_id": None,
        "employee_id": None,
        "tasks_created": 0,
    }
    skill_ids: list[str] = []
    kb_id_result: str | None = None

    if "skill" in selected:
        skill_spec = draft_body.get("skill") if isinstance(draft_body.get("skill"), dict) else {}
        title = skill_title or skill_spec.get("display_name") or conv.title or "对话技能"
        skill = await materialize_skill_from_spec(
            db, conv, user_id, skill_spec, title=title,
        )
        result["skill_id"] = skill.id
        skill_ids.append(skill.id)
        _append_skill_binding(conv, skill.id)

    if "knowledge" in selected:
        kb_spec = draft_body.get("knowledge") if isinstance(draft_body.get("knowledge"), dict) else {}
        kb, _doc = await materialize_knowledge_from_spec(
            db,
            conv,
            user_id,
            kb_spec,
            kb_id=kb_id,
            kb_name=kb_name or kb_spec.get("kb_name"),
        )
        result["knowledge_base_id"] = kb.id
        kb_id_result = kb.id
        _append_kb_id(conv, kb.id)
        if result["skill_id"]:
            skill = await db.get(Skill, result["skill_id"])
            if skill:
                linked = list(skill.knowledge_base_ids or [])
                if kb.id not in linked:
                    linked.append(kb.id)
                skill.knowledge_base_ids = linked
                await db.flush()

    all_skill_ids = _merge_skill_id_lists(skill_ids, _skill_ids_from_conv(conv))

    agent_id: str | None = conv.agent_id
    if "agent" in selected:
        agent_spec = draft_body.get("agent") if isinstance(draft_body.get("agent"), dict) else {}
        if not agent_spec:
            raise ValueError("Agent draft missing from deposit preview")
        agent = await _create_agent_from_draft(db, conv, user_id, agent_spec, all_skill_ids)
        agent_id = agent.id
        result["agent_id"] = agent.id
        conv.agent_id = agent.id

    effective_kb_ids = list(conv.knowledge_base_ids or [])

    if "employee" in selected:
        if not agent_id:
            raise ValueError("Cannot create employee without an agent")
        emp_spec = draft_body.get("employee") if isinstance(draft_body.get("employee"), dict) else {}
        if not emp_spec:
            raise ValueError("Employee draft missing from deposit preview")
        emp, task_count = await _create_employee_from_draft(
            db,
            conv,
            user_id,
            emp_spec,
            agent_id,
            all_skill_ids,
            knowledge_base_ids=effective_kb_ids,
            activate=activate_employee,
        )
        result["employee_id"] = emp.id
        result["tasks_created"] = task_count

    meta = dict(conv.metadata_ or {})
    meta.pop("deposit_draft", None)
    meta["last_deposit"] = {
        "draft_id": draft_id,
        "types": list(selected),
        "result": {k: v for k, v in result.items() if v is not None},
    }
    conv.metadata_ = meta
    await db.flush()
    return result
