"""Run multi-agent Crew from task config (shared by API + employee scheduler)."""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agents.base import Task
from app.core.orchestrator.crew import Crew
from app.core.skills.factory import build_agent_executor
from app.db.models import Agent as AgentModel


async def execute_crew_from_config(db: AsyncSession, task_config: dict[str, Any]) -> dict[str, Any]:
    goal = str(task_config.get("goal") or task_config.get("prompt") or "").strip()
    if not goal:
        raise ValueError("task_config.goal or prompt is required for crew tasks")

    agent_ids = task_config.get("agent_ids") or []
    if not agent_ids and task_config.get("agent_id"):
        agent_ids = [task_config["agent_id"]]
    if not agent_ids:
        raise ValueError("task_config.agent_ids is required for crew tasks")

    process = str(task_config.get("process") or "sequential")
    manager_id = task_config.get("manager_agent_id")

    result = await db.execute(select(AgentModel).where(AgentModel.id.in_(agent_ids)))
    agents_db = {a.id: a for a in result.scalars().all()}
    missing = [aid for aid in agent_ids if aid not in agents_db]
    if missing:
        raise ValueError(f"Agents not found: {missing}")

    executors = []
    for aid in agent_ids:
        executors.append(await build_agent_executor(db, agents_db[aid]))

    manager_executor = None
    if manager_id and manager_id in agents_db:
        manager_executor = await build_agent_executor(db, agents_db[manager_id])

    raw_tasks = task_config.get("tasks") or []
    if raw_tasks:
        tasks = [
            Task(
                description=str(t.get("description") or goal),
                agent_id=t.get("agent_id"),
            )
            for t in raw_tasks
            if isinstance(t, dict)
        ]
    else:
        tasks = [Task(description=goal, agent_id=agent_ids[0])]

    crew = Crew(
        agents=executors,
        tasks=tasks,
        process=process,
        manager_agent=manager_executor,
    )

    start = time.monotonic()
    crew_result = await crew.kickoff({"input": goal})
    duration_ms = int((time.monotonic() - start) * 1000)
    return {
        "output": crew_result.final_output,
        "task_outputs": crew_result.task_outputs,
        "token_usage": crew_result.token_usage,
        "duration_ms": duration_ms,
        "process": process,
    }
