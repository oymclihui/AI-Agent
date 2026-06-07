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
from app.core.agents.base import Task
from app.core.skills.factory import build_agent_executor
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

    executors = []
    for aid in payload.agent_ids:
        agent_model = agents_db[aid]
        executors.append(await build_agent_executor(db, agent_model))

    manager_executor = None
    if payload.manager_agent_id:
        mgr = agents_db.get(payload.manager_agent_id)
        if mgr:
            manager_executor = await build_agent_executor(db, mgr)

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
