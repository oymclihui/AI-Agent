"""Load and import bundled digital employee templates."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.employees.schedule import compute_next_run, validate_schedule
from app.db.base import generate_uuid
from app.db.models import (
    Agent,
    AgentStatus,
    DigitalEmployee,
    EmployeeScheduledTask,
    EmployeeStatus,
    EmployeeTaskType,
    KnowledgeBase,
    ScheduleType,
    Skill,
    SkillStatus,
    User,
)

logger = structlog.get_logger(__name__)

TEMPLATES_DIR = Path(__file__).with_name("templates")
TEMPLATE_STATUS_ACTIVE = "active"
TEMPLATE_STATUS_DRAFT = "draft"


def _template_publish_status(data: dict[str, Any]) -> str:
    return str(data.get("status") or TEMPLATE_STATUS_DRAFT).lower()


def template_visible_to_user(data: dict[str, Any], user: User | None) -> bool:
    """Admin sees all; others only see published templates in allowed categories."""
    if user is None:
        return False
    if user.is_admin:
        return True
    if _template_publish_status(data) != TEMPLATE_STATUS_ACTIVE:
        return False
    category = str(data.get("category") or "general").lower()
    return category in settings.employee_template_user_categories


def list_templates(user: User | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not TEMPLATES_DIR.exists():
        return items
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if user is not None and not template_visible_to_user(data, user):
                continue
            items.append(_template_summary(data))
        except Exception as exc:
            logger.warning("employee_template_load_failed", path=str(path), error=str(exc))
    return items


def get_template(template_id: str) -> dict[str, Any]:
    path = TEMPLATES_DIR / f"{template_id}.json"
    if not path.exists():
        raise ValueError(f"Template not found: {template_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _template_summary(data: dict[str, Any]) -> dict[str, Any]:
    employee = data.get("employee") or {}
    tasks = data.get("tasks") or []
    return {
        "template_id": data.get("template_id", ""),
        "name_zh": data.get("name_zh", ""),
        "name_en": data.get("name_en", ""),
        "description_zh": data.get("description_zh", ""),
        "description_en": data.get("description_en", ""),
        "category": data.get("category", "general"),
        "status": _template_publish_status(data),
        "employee_name": employee.get("name", ""),
        "employee_title": employee.get("title"),
        "task_count": len(tasks),
        "tasks_preview": [t.get("name", "") for t in tasks[:3]],
        "suggested_questions": data.get("suggested_questions") or [],
    }


async def _resolve_agent(db: AsyncSession, agent_spec: dict[str, Any]) -> Agent:
    if agency_slug := str(agent_spec.get("agency_slug") or "").strip():
        result = await db.execute(select(Agent))
        for agent in result.scalars().all():
            if (agent.metadata_ or {}).get("agency_slug") == agency_slug:
                return agent
        raise ValueError(f"Agency agent not imported yet: {agency_slug}. Import from Agent library first.")

    if ref := str(agent_spec.get("ref") or "").strip():
        result = await db.execute(select(Agent).where(Agent.name == ref).limit(1))
        agent = result.scalar_one_or_none()
        if agent:
            return agent
        raise ValueError(f"Agent not found: {ref}. Create agents first or use seed templates.")

    name = str(agent_spec.get("name") or "").strip()
    role = str(agent_spec.get("role") or "").strip()
    goal = str(agent_spec.get("goal") or "").strip()
    if not name or not role or not goal:
        raise ValueError("agent.ref or agent.name/role/goal is required")

    tools = agent_spec.get("tools") or []
    tools_config = (
        [{"tool_name": t} if isinstance(t, str) else t for t in tools]
        if isinstance(tools, list) else []
    )

    agent = Agent(
        id=generate_uuid(),
        name=name,
        role=role,
        goal=goal,
        backstory=str(agent_spec.get("backstory") or ""),
        llm_provider=agent_spec.get("llm_provider") or settings.DEFAULT_LLM_PROVIDER,
        llm_model=agent_spec.get("llm_model") or settings.DEFAULT_LLM_MODEL,
        temperature=float(agent_spec.get("temperature", 0.7)),
        max_iterations=int(agent_spec.get("max_iterations", 10)),
        tools_config=tools_config,
        memory_config={},
        status=AgentStatus.active,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _resolve_skills(db: AsyncSession, skills_spec: list[Any]) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for item in skills_spec or []:
        if not isinstance(item, dict):
            continue
        skill_id: str | None = None
        if ref := str(item.get("ref") or item.get("slug") or "").strip():
            result = await db.execute(select(Skill).where(Skill.slug == ref).limit(1))
            skill = result.scalar_one_or_none()
            if not skill and item.get("display_name"):
                skill = Skill(
                    id=generate_uuid(),
                    slug=ref,
                    display_name=str(item.get("display_name") or ref),
                    description=str(item.get("description") or ref),
                    instructions_md=str(item.get("instructions_md") or ""),
                    status=SkillStatus.active,
                    scope="global",
                    auto_invoke=False,
                    tags=item.get("tags") or [],
                )
                db.add(skill)
                await db.flush()
            if skill:
                skill_id = skill.id
            else:
                raise ValueError(f"Skill not found: {ref}")
        bindings.append({
            "skill_id": skill_id,
            "always_load": bool(item.get("always_load", True)),
            "priority": int(item.get("priority", 0)),
        })
    return [b for b in bindings if b.get("skill_id")]


async def _resolve_knowledge_ids(db: AsyncSession, kb_spec: list[Any]) -> list[str]:
    ids: list[str] = []
    for item in kb_spec or []:
        if not isinstance(item, dict):
            continue
        if ref := str(item.get("ref") or item.get("name") or "").strip():
            result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.name == ref).limit(1))
            kb = result.scalar_one_or_none()
            if kb:
                ids.append(kb.id)
            else:
                logger.warning("employee_template_kb_not_found", ref=ref)
    return ids


async def import_template(
    db: AsyncSession,
    template_id: str,
    *,
    employee_name_override: str | None = None,
    user: User | None = None,
) -> tuple[DigitalEmployee, int]:
    data = get_template(template_id)
    if user is not None and not template_visible_to_user(data, user):
        raise ValueError(f"Template not available: {template_id}")
    agent = await _resolve_agent(db, data.get("agent") or {})
    skills_config = await _resolve_skills(db, data.get("skills") or [])
    knowledge_base_ids = await _resolve_knowledge_ids(db, data.get("knowledge") or [])

    emp_spec = data.get("employee") or {}
    name = (employee_name_override or emp_spec.get("name") or data.get("name_zh") or template_id).strip()
    if not name:
        raise ValueError("Employee name is required")

    emp = DigitalEmployee(
        id=generate_uuid(),
        owner_id=user.id if user else None,
        department_id=user.primary_department_id if user else None,
        name=name,
        title=emp_spec.get("title"),
        description=emp_spec.get("description") or data.get("description_zh"),
        status=EmployeeStatus.active,
        agent_id=agent.id,
        skills_config=skills_config,
        knowledge_base_ids=knowledge_base_ids,
        timezone=str(emp_spec.get("timezone") or "Asia/Shanghai"),
        metadata_={
            "template_id": template_id,
            **({k: v for k, v in (emp_spec.get("metadata") or {}).items()}),
        },
    )
    db.add(emp)
    await db.flush()

    task_count = 0
    for task_spec in data.get("tasks") or []:
        if not isinstance(task_spec, dict):
            continue
        prompt = str((task_spec.get("task_config") or {}).get("prompt") or "").strip()
        if not prompt:
            logger.warning("employee_template_skip_task_no_prompt", template_id=template_id)
            continue

        schedule_type = str(task_spec.get("schedule_type") or "cron")
        cron_expression = task_spec.get("cron_expression")
        interval_seconds = task_spec.get("interval_seconds")
        tz = str(task_spec.get("timezone") or emp.timezone)

        validate_schedule(schedule_type, cron_expression, interval_seconds)

        task = EmployeeScheduledTask(
            id=generate_uuid(),
            employee_id=emp.id,
            name=str(task_spec.get("name") or "Scheduled task"),
            description=task_spec.get("description"),
            enabled=bool(task_spec.get("enabled", True)),
            schedule_type=ScheduleType(schedule_type),
            cron_expression=cron_expression,
            interval_seconds=interval_seconds,
            timezone=tz,
            task_type=EmployeeTaskType.agent,
            task_config=task_spec.get("task_config") or {"prompt": prompt},
            retry_max=int(task_spec.get("retry_max", 0)),
            timeout_seconds=int(task_spec.get("timeout_seconds", 600)),
        )
        if task.enabled:
            task.next_run_at = compute_next_run(
                schedule_type,
                cron_expression=cron_expression,
                interval_seconds=interval_seconds,
                timezone_name=tz,
            )
        db.add(task)
        task_count += 1

    await db.flush()
    await db.refresh(emp)
    return emp, task_count
