from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json

from app.db.session import get_db
from app.db.models import Agent as AgentModel, AgentExecution, ExecutionStatus
from app.db.base import generate_uuid
from pydantic import BaseModel, Field
from app.schemas.agent import AgentCreate, AgentUpdate, AgentResponse, AgentRunRequest
from app.config import settings
from app.core.agents.base import AgentDefinition, Task, AgentType
from app.core.agents.executor import AgentExecutor
from app.core.tools.registry import ToolRegistry

router = APIRouter(prefix="/agents", tags=["Agents"])


class AgentGenerateRequest(BaseModel):
    description: str = Field(..., min_length=5, description="Natural language description of the agent")


@router.post("/generate", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def generate_agent(payload: AgentGenerateRequest, db: AsyncSession = Depends(get_db)):
    """Create an agent from a natural-language description using the default LLM."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from app.models_hub.router import ModelRouter

    llm = await ModelRouter.get_llm()
    prompt = (
        "You are an agent designer. Given a user description, output ONLY valid JSON with keys: "
        "name (Chinese), role (English job title), goal (Chinese), backstory (Chinese), "
        "tools (array of tool names from: web_search, calculator, http_request, datetime), "
        "temperature (0.0-1.0).\n\n"
        f"Description: {payload.description}"
    )
    response = await llm.ainvoke([
        SystemMessage(content="Respond with JSON only, no markdown."),
        HumanMessage(content=prompt),
    ])
    import json as _json
    raw = (response.content or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        spec = _json.loads(raw)
    except _json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"LLM returned invalid JSON: {e}")

    tools_config = [{"tool_name": t} for t in spec.get("tools", []) if isinstance(t, str)]
    agent = AgentModel(
        id=generate_uuid(),
        name=spec.get("name", "新智能体"),
        role=spec.get("role", "Assistant"),
        goal=spec.get("goal", payload.description),
        backstory=spec.get("backstory", ""),
        llm_provider=settings.DEFAULT_LLM_PROVIDER,
        llm_model=settings.DEFAULT_LLM_MODEL,
        temperature=float(spec.get("temperature", 0.7)),
        max_iterations=10,
        tools_config=tools_config,
        memory_config={},
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return agent


@router.post("/seed-templates", status_code=status.HTTP_200_OK)
async def seed_agent_templates(db: AsyncSession = Depends(get_db)):
    from app.db.init_db import seed_template_agents
    await seed_template_agents(db)
    return {"message": "Template agents seeded (skipped if already exist)"}


@router.get("/", response_model=list[AgentResponse])
async def list_agents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentModel).order_by(AgentModel.created_at.desc()))
    return result.scalars().all()


@router.post("/", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(payload: AgentCreate, db: AsyncSession = Depends(get_db)):
    agent = AgentModel(
        id=generate_uuid(),
        name=payload.name,
        role=payload.role,
        goal=payload.goal,
        backstory=payload.backstory,
        llm_provider=payload.llm_provider,
        llm_model=payload.llm_model,
        temperature=payload.temperature,
        max_iterations=payload.max_iterations,
        tools_config=[t.model_dump() for t in payload.tools_config],
        memory_config=payload.memory_config.model_dump(),
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return agent


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    agent = await db.get(AgentModel, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(agent_id: str, payload: AgentUpdate, db: AsyncSession = Depends(get_db)):
    agent = await db.get(AgentModel, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(agent, field, value)

    await db.flush()
    await db.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    agent = await db.get(AgentModel, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    await db.delete(agent)


@router.post("/{agent_id}/run")
async def run_agent(
    agent_id: str,
    payload: AgentRunRequest,
    db: AsyncSession = Depends(get_db),
):
    agent_model = await db.get(AgentModel, agent_id)
    if not agent_model:
        raise HTTPException(status_code=404, detail="Agent not found")

    tool_names = [t.get("tool_name") for t in (agent_model.tools_config or [])]
    registry = ToolRegistry.get_instance()
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
    executor = AgentExecutor(definition=definition, tools=tools)
    task = Task(description=payload.task)

    execution = AgentExecution(
        id=generate_uuid(),
        agent_id=agent_id,
        task_description=payload.task,
        status=ExecutionStatus.running,
    )
    db.add(execution)
    await db.flush()

    if payload.stream:
        async def token_stream():
            async for token in executor.stream(task):
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(token_stream(), media_type="text/event-stream")

    try:
        result = await executor.run(task, context=payload.context)
        execution.status = ExecutionStatus.completed
        execution.output = result["output"]
        execution.token_usage = result.get("token_usage", {})
        execution.steps = result.get("steps", [])
    except Exception as e:
        execution.status = ExecutionStatus.failed
        execution.error_message = str(e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await db.flush()

    return {
        "execution_id": execution.id,
        "output": execution.output,
        "token_usage": execution.token_usage,
        "steps": execution.steps,
    }
