"""Create digital employee + agent from data source."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.semantic.mdl import default_semantic_model
from app.core.employees.schedule import compute_next_run
from app.db.base import generate_uuid
from app.db.models import (
    Agent as AgentModel,
    AgentStatus,
    DataSource,
    DigitalEmployee,
    EmployeeScheduledTask,
    EmployeeStatus,
    EmployeeTaskType,
    ScheduleType,
    User,
)


async def generate_agent_blueprint(
    db: AsyncSession,
    source: DataSource,
    *,
    nl_prompt: str | None = None,
) -> dict[str, Any]:
    tables = source.metadata_.get("registered_tables") or []
    name = source.name or "问数分析"
    prompt = nl_prompt or f"基于数据源「{name}」进行数据分析与报告撰写"
    return {
        "agent": {
            "name": f"{name}分析顾问",
            "role": "Data Analyst",
            "goal": prompt,
            "backstory": f"熟悉数据源 {name}，表: {', '.join(tables[:5])}",
            "temperature": 0.35,
        },
        "employee": {
            "name": f"{name}分析助理",
            "title": "数据问数助理",
            "description": prompt,
        },
        "task": {
            "name": "每日数据报告",
            "cron_expression": "0 8 * * *",
            "queries": [
                {"name": "KPI概览", "question": "按国家汇总本周销量与上周对比"},
                {"name": "异常明细", "question": "列出销量环比下降超过20%的国家"},
            ],
            "prompt": (
                "你是数据分析助理。以下是由系统预查询的数据快照，请撰写《每日数据分析简报》（中文 Markdown）。\n\n"
                "{data_snapshot}\n\n"
                "结构：1.执行摘要 2.关键指标 3.异常项 4.建议"
            ),
        },
    }


async def create_agent_for_source(
    db: AsyncSession,
    source: DataSource,
    user: User,
    blueprint: dict[str, Any] | None = None,
) -> AgentModel:
    bp = blueprint or await generate_agent_blueprint(db, source)
    spec = bp.get("agent") or {}
    agent = AgentModel(
        id=generate_uuid(),
        owner_id=user.id,
        name=str(spec.get("name") or f"{source.name}分析顾问")[:255],
        role=str(spec.get("role") or "Data Analyst")[:255],
        goal=str(spec.get("goal") or "数据分析")[:5000],
        backstory=spec.get("backstory"),
        status=AgentStatus.active,
        temperature=float(spec.get("temperature") or 0.35),
        tools_config=[{"tool_name": "calculator"}, {"tool_name": "datetime"}],
        metadata_={"data_source_id": source.id, "data_ask": True},
    )
    db.add(agent)
    await db.flush()
    source.agent_id = agent.id
    return agent


async def create_employee_for_source(
    db: AsyncSession,
    source: DataSource,
    user: User,
    *,
    blueprint: dict[str, Any] | None = None,
    cron: str = "0 8 * * *",
) -> tuple[DigitalEmployee, int]:
    bp = blueprint or await generate_agent_blueprint(db, source)
    agent = await db.get(AgentModel, source.agent_id) if source.agent_id else None
    if not agent:
        agent = await create_agent_for_source(db, source, user, bp)

    emp_spec = bp.get("employee") or {}
    emp = DigitalEmployee(
        id=generate_uuid(),
        owner_id=user.id,
        department_id=user.primary_department_id,
        name=str(emp_spec.get("name") or f"{source.name}助理")[:255],
        title=emp_spec.get("title"),
        description=emp_spec.get("description"),
        status=EmployeeStatus.active,
        agent_id=agent.id,
        skills_config=[],
        timezone="Asia/Shanghai",
        metadata_={"data_source_id": source.id, "data_ask": True},
    )
    db.add(emp)
    await db.flush()
    source.employee_id = emp.id

    task_spec = bp.get("task") or {}
    task = EmployeeScheduledTask(
        id=generate_uuid(),
        employee_id=emp.id,
        name=str(task_spec.get("name") or "每日数据报告"),
        description=f"数据源 {source.name} 自动报告",
        enabled=True,
        schedule_type=ScheduleType.cron,
        cron_expression=cron or task_spec.get("cron_expression") or "0 8 * * *",
        timezone="Asia/Shanghai",
        task_type=EmployeeTaskType.agent,
        task_config={
            "prompt": task_spec.get("prompt") or bp["task"]["prompt"],
            "data_ask": True,
            "data_source_id": source.id,
            "queries": task_spec.get("queries") or bp.get("task", {}).get("queries"),
        },
    )
    task.next_run_at = compute_next_run("cron", cron_expression=task.cron_expression, timezone_name=task.timezone)
    db.add(task)
    await db.flush()
    return emp, 1


async def ensure_semantic_model(source: DataSource) -> None:
    if not source.semantic_model:
        source.semantic_model = default_semantic_model()
