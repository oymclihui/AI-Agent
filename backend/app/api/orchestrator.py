"""
Orchestrator API — exposes the CrewAI-style multi-agent Crew.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field
from typing import Optional
import time
import structlog

from app.db.session import get_db
from app.db.models import Agent as AgentModel
from app.core.agents.base import AgentDefinition, Task
from app.core.agents.executor import AgentExecutor
from app.core.tools.registry import ToolRegistry
from app.core.orchestrator.crew import Crew

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/orchestrator", tags=["Orchestrator"])


class CrewTaskDef(BaseModel):
    description: str
    agent_id: Optional[str] = None


class CrewRunRequest(BaseModel):
    goal: str = Field(..., description="Overall goal for the crew")
    process: str = Field("sequential", description="sequential | hierarchical | parallel")
    agent_ids: list[str] = Field(..., min_length=1)
    tasks: list[CrewTaskDef] = Field(default_factory=list)
    manager_agent_id: Optional[str] = None


@router.post("/run")
async def run_crew(payload: CrewRunRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentModel).where(AgentModel.id.in_(payload.agent_ids)))
    agents_db = {a.id: a for a in result.scalars().all()}
    missing = [aid for aid in payload.agent_ids if aid not in agents_db]
    if missing:
        raise HTTPException(status_code=404, detail=f"Agents not found: {missing}")

    registry = ToolRegistry.get_instance()
    executors = []
    for aid in payload.agent_ids:
        agent_model = agents_db[aid]
        tool_names = [t.get("tool_name") for t in (agent_model.tools_config or [])]
        tools = registry.get_tools_for_agent(tool_names)
        definition = AgentDefinition(
            id=agent_model.id,
            name=agent_model.name,
            role=agent_model.role,
            goal=agent_model.goal,
            backstory=agent_model.backstory or "",
            llm_provider=agent_model.llm_provider,
            llm_model=agent_model.llm_model,
            temperature=agent_model.temperature,
            max_iterations=agent_model.max_iterations,
            tools=tool_names,
        )
        executors.append(AgentExecutor(definition=definition, tools=tools))

    manager_executor = None
    if payload.manager_agent_id:
        mgr = agents_db.get(payload.manager_agent_id)
        if mgr:
            tool_names = [t.get("tool_name") for t in (mgr.tools_config or [])]
            manager_executor = AgentExecutor(
                definition=AgentDefinition(
                    id=mgr.id, name=mgr.name, role=mgr.role, goal=mgr.goal,
                    backstory=mgr.backstory or "", llm_provider=mgr.llm_provider,
                    llm_model=mgr.llm_model, temperature=mgr.temperature,
                ),
                tools=registry.get_tools_for_agent(tool_names),
            )

    if payload.tasks:
        tasks = [Task(description=t.description, agent_id=t.agent_id) for t in payload.tasks]
    else:
        tasks = [Task(description=payload.goal, agent_id=payload.agent_ids[0])]

    crew = Crew(
        agents=executors,
        tasks=tasks,
        process=payload.process,
        manager_agent=manager_executor,
    )

    start = time.monotonic()
    try:
        crew_result = await crew.kickoff({"input": payload.goal})
    except Exception as e:
        logger.error("crew_run_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

    elapsed = round(time.monotonic() - start, 1)
    return {
        "output": crew_result.final_output,
        "task_outputs": crew_result.task_outputs,
        "token_usage": crew_result.token_usage,
        "elapsed_s": elapsed,
        "process": payload.process,
    }
