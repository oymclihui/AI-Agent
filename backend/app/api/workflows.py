import time
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json

from app.db.session import get_db
from app.db.models import (
    Workflow as WorkflowModel,
    WorkflowExecution,
    Agent as AgentModel,
    ExecutionStatus,
)
from app.db.base import generate_uuid
from app.schemas.workflow import (
    WorkflowCreate, WorkflowUpdate, WorkflowResponse,
    WorkflowExecuteRequest, WorkflowExecutionResponse,
)
from app.core.workflow.engine import WorkflowEngine, WorkflowBuilder
from app.core.agents.base import AgentDefinition
from app.core.tools.registry import ToolRegistry

router = APIRouter(prefix="/workflows", tags=["Workflows"])


@router.post("/seed-templates", status_code=status.HTTP_200_OK)
async def seed_workflow_templates(db: AsyncSession = Depends(get_db)):
    from app.db.init_db import seed_template_workflows
    await seed_template_workflows(db)
    return {"message": "Template workflows seeded (skipped if already exist)"}


@router.get("/", response_model=list[WorkflowResponse])
async def list_workflows(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WorkflowModel).order_by(WorkflowModel.created_at.desc()))
    return result.scalars().all()


@router.post("/", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(payload: WorkflowCreate, db: AsyncSession = Depends(get_db)):
    workflow = WorkflowModel(
        id=generate_uuid(),
        name=payload.name,
        description=payload.description,
        process_type=payload.process_type,
        graph_definition=payload.graph_definition.model_dump(),
        agents_config=payload.agents_config,
        triggers_config=[t.model_dump() for t in payload.triggers_config],
    )
    db.add(workflow)
    await db.flush()
    await db.refresh(workflow)
    return workflow


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: str, db: AsyncSession = Depends(get_db)):
    workflow = await db.get(WorkflowModel, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.patch("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(workflow_id: str, payload: WorkflowUpdate, db: AsyncSession = Depends(get_db)):
    workflow = await db.get(WorkflowModel, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    update_data = payload.model_dump(exclude_none=True)
    if "graph_definition" in update_data and hasattr(update_data["graph_definition"], "model_dump"):
        update_data["graph_definition"] = update_data["graph_definition"].model_dump()

    for field, value in update_data.items():
        setattr(workflow, field, value)

    await db.flush()
    await db.refresh(workflow)
    return workflow


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: str, db: AsyncSession = Depends(get_db)):
    workflow = await db.get(WorkflowModel, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await db.delete(workflow)


@router.post("/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    payload: WorkflowExecuteRequest,
    db: AsyncSession = Depends(get_db),
):
    workflow = await db.get(WorkflowModel, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Build agent registry from database
    agent_registry: dict[str, AgentDefinition] = {}
    tool_registry = ToolRegistry.get_instance()

    result = await db.execute(select(AgentModel))
    for agent_model in result.scalars().all():
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
        )
        agent_registry[agent_model.id] = definition
        agent_registry[agent_model.role] = definition
        agent_registry[agent_model.name] = definition

    graph = await WorkflowBuilder.build(workflow, tool_registry, agent_registry)
    engine = WorkflowEngine(graph)

    execution = WorkflowExecution(
        id=generate_uuid(),
        workflow_id=workflow_id,
        status=ExecutionStatus.running,
        input_data=payload.input_data,
    )
    db.add(execution)
    await db.flush()

    start = time.monotonic()
    try:
        state = await engine.execute(payload.input_data)
        execution.status = ExecutionStatus.completed
        execution.output_data = {
            "final_output": state.final_output,
            "agent_outputs": state.agent_outputs,
        }
        execution.token_usage = state.token_usage
        execution.state_snapshot = {
            "messages": state.messages[-20:],
            "errors": state.errors,
        }
    except Exception as e:
        execution.status = ExecutionStatus.failed
        execution.error_message = str(e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        execution.duration_ms = int((time.monotonic() - start) * 1000)
        await db.flush()

    return {
        "execution_id": execution.id,
        "status": execution.status,
        "output": execution.output_data,
        "token_usage": execution.token_usage,
        "duration_ms": execution.duration_ms,
    }


@router.get("/{workflow_id}/executions", response_model=list[WorkflowExecutionResponse])
async def list_executions(workflow_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(WorkflowExecution)
        .where(WorkflowExecution.workflow_id == workflow_id)
        .order_by(WorkflowExecution.created_at.desc())
        .limit(50)
    )
    return result.scalars().all()
