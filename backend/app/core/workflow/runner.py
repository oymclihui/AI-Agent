"""Run a workflow definition and return execution output (shared by API + employee scheduler)."""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agents.base import AgentDefinition
from app.core.artifacts import collect_artifacts_from_output, merge_artifacts
from app.core.tools.registry import ToolRegistry
from app.core.workflow.engine import WorkflowBuilder, WorkflowEngine
from app.core.workflow.langgraph_engine import LangGraphWorkflowEngine
from app.db.base import generate_uuid
from app.db.models import Agent as AgentModel, ExecutionStatus, Workflow as WorkflowModel, WorkflowExecution


async def execute_workflow_by_id(
    db: AsyncSession,
    workflow_id: str,
    input_data: dict[str, Any] | None = None,
    *,
    owner_user_id: str | None = None,
    persist_execution: bool = True,
) -> dict[str, Any]:
    workflow = await db.get(WorkflowModel, workflow_id)
    if not workflow:
        raise ValueError(f"Workflow not found: {workflow_id}")

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
    # lg5: Use LangGraph StateGraph engine (falls back to custom engine on error)
    use_langgraph = True
    if use_langgraph:
        engine = LangGraphWorkflowEngine(graph, max_steps=100)
    else:
        engine = WorkflowEngine(graph)

    execution: WorkflowExecution | None = None
    if persist_execution:
        execution = WorkflowExecution(
            id=generate_uuid(),
            workflow_id=workflow_id,
            status=ExecutionStatus.running,
            input_data=input_data or {},
        )
        db.add(execution)
        await db.flush()

    start = time.monotonic()
    from app.core.auth.context import reset_current_user_id, set_current_user_id

    ctx_user = owner_user_id or workflow.owner_id
    ctx_token = None
    payload = dict(input_data or {})
    if ctx_user:
        ctx_token = set_current_user_id(ctx_user)
        payload["_user_id"] = ctx_user

    try:
        state = await engine.execute(payload)
        artifacts = merge_artifacts(
            state.context.get("artifacts") if isinstance(state.context.get("artifacts"), list) else None,
            collect_artifacts_from_output(state.final_output),
        )
        output_data = {
            "final_output": state.final_output,
            "agent_outputs": state.agent_outputs,
            "errors": state.errors,
            "rows": state.context.get("rows"),
            "preview": state.context.get("preview"),
            "output_path": state.context.get("output_path"),
            "download_url": state.context.get("download_url"),
            "artifacts": artifacts,
        }
        if execution is not None:
            execution.status = ExecutionStatus.completed
            execution.output_data = output_data
            execution.token_usage = state.token_usage
            execution.state_snapshot = {
                "messages": state.messages[-20:],
                "errors": state.errors,
            }
        duration_ms = int((time.monotonic() - start) * 1000)
        return {
            "workflow_execution_id": execution.id if execution else None,
            "output_data": output_data,
            "token_usage": state.token_usage,
            "duration_ms": duration_ms,
        }
    except Exception as exc:
        if execution is not None:
            execution.status = ExecutionStatus.failed
            execution.error_message = str(exc)
        raise
    finally:
        if ctx_token is not None:
            reset_current_user_id(ctx_token)
