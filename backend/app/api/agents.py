from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json

from app.db.session import get_db
from app.db.models import Agent as AgentModel, AgentExecution, ExecutionStatus, User
from app.db.base import generate_uuid
from pydantic import BaseModel, Field
from app.schemas.agent import (
    AgentCreate,
    AgentUpdate,
    AgentResponse,
    AgentRunRequest,
    AgentLibraryImportRequest,
    AgentLibraryTemplate,
)
from app.config import settings
from app.core.agents.base import AgentDefinition, Task
from app.core.skills.factory import build_agent_executor
from app.core.auth.deps import get_current_user
from app.core.auth.scoping import scope_list_visible, can_read_record, assert_mutable_by_user

router = APIRouter(prefix="/agents", tags=["Agents"])


class AgentGenerateRequest(BaseModel):
    description: str = Field(..., min_length=5, description="Natural language description of the agent")


@router.post("/generate", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def generate_agent(
    payload: AgentGenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create an agent from a natural-language description using the default LLM."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from app.models_hub.router import ModelRouter

    llm = await ModelRouter.get_llm(db=db, user_id=user.id)
    prompt = (
        "You are an agent designer. Given a user description, output ONLY valid JSON with keys: "
        "name (Chinese), role (English job title), goal (Chinese), backstory (Chinese), "
        "tools (array of tool names from: web_search, calculator, http_request, datetime, fetch_mail, "
        "desktop_list_demos, desktop_replay, desktop_capture), "
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
        owner_id=user.id,
        name=spec.get("name", "新智能体"),
        role=spec.get("role", "Assistant"),
        goal=spec.get("goal", payload.description),
        backstory=spec.get("backstory", ""),
        llm_provider=settings.DEFAULT_LLM_PROVIDER,
        llm_model=settings.DEFAULT_LLM_MODEL,
        temperature=float(spec.get("temperature", 0.7)),
        max_iterations=10,
        tools_config=tools_config,
        skills_config=[],
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


@router.get("/library/sources")
async def agent_library_sources():
    from app.core.agents.agency_library import AgencyAgentLibrary
    return AgencyAgentLibrary.get_sources()


@router.get("/library/catalog", response_model=list[AgentLibraryTemplate])
async def agent_library_catalog(
    source: str | None = None,
    division: str | None = None,
    q: str | None = None,
    lang: str | None = Query(None, description="UI language: zh | en"),
):
    from app.core.agents.agency_library import AgencyAgentLibrary
    return AgencyAgentLibrary.list_catalog(source=source, division=division, query=q, lang=lang)


@router.get("/library/divisions")
async def agent_library_divisions(source: str | None = None):
    from app.core.agents.agency_library import AgencyAgentLibrary
    return AgencyAgentLibrary.list_divisions(source=source)


@router.post("/library/sync")
async def agent_library_sync():
    from app.core.agents.agency_library import AgencyAgentLibrary
    try:
        return await AgencyAgentLibrary.sync_catalog()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to sync agent library: {exc}")


@router.post("/library/i18n-backfill")
async def agent_i18n_backfill(db: AsyncSession = Depends(get_db)):
    """Refresh metadata.i18n for seed and Agency agents already in the database."""
    from app.core.agents.i18n_backfill import backfill_all_agent_i18n

    try:
        stats = await backfill_all_agent_i18n(db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return stats


@router.post("/library/import")
async def agent_library_import(payload: AgentLibraryImportRequest, db: AsyncSession = Depends(get_db)):
    from app.core.agents.agency_library import AgencyAgentLibrary
    try:
        if payload.import_all:
            return await AgencyAgentLibrary.import_all(db, overwrite=payload.overwrite)
        return await AgencyAgentLibrary.import_templates(
            db,
            payload.items,
            overwrite=payload.overwrite,
            import_skills=payload.import_skills,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/", response_model=list[AgentResponse])
async def list_agents(
    lang: str | None = Query(None, description="UI language: zh | en"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.core.agents.i18n import agent_to_response_dict

    result = await db.execute(
        select(AgentModel)
        .where(scope_list_visible(AgentModel, user))
        .order_by(AgentModel.created_at.desc())
    )
    return [agent_to_response_dict(a, lang) for a in result.scalars().all()]


@router.post("/", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = AgentModel(
        id=generate_uuid(),
        owner_id=user.id,
        name=payload.name,
        role=payload.role,
        goal=payload.goal,
        backstory=payload.backstory,
        llm_provider=payload.llm_provider,
        llm_model=payload.llm_model,
        temperature=payload.temperature,
        max_iterations=payload.max_iterations,
        tools_config=[t.model_dump() for t in payload.tools_config],
        skills_config=[s.model_dump() for s in payload.skills_config],
        memory_config=payload.memory_config.model_dump(),
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return agent


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    lang: str | None = Query(None, description="UI language: zh | en"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.core.agents.i18n import agent_to_response_dict

    agent = await db.get(AgentModel, agent_id)
    if not agent or not can_read_record(agent, user):
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent_to_response_dict(agent, lang)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = await db.get(AgentModel, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    assert_mutable_by_user(agent, user.id, "agent")

    for field, value in payload.model_dump(exclude_none=True).items():
        if field == "tools_config" and value is not None:
            agent.tools_config = [t if isinstance(t, dict) else t for t in value]
        elif field == "skills_config" and value is not None:
            agent.skills_config = [s if isinstance(s, dict) else s for s in value]
        elif field == "memory_config" and value is not None:
            agent.memory_config = value if isinstance(value, dict) else value
        else:
            setattr(agent, field, value)

    await db.flush()
    await db.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = await db.get(AgentModel, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    assert_mutable_by_user(agent, user.id, "agent")
    await db.delete(agent)


@router.post("/{agent_id}/run")
async def run_agent(
    agent_id: str,
    payload: AgentRunRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent_model = await db.get(AgentModel, agent_id)
    if not agent_model or not (agent_model.owner_id == user.id or agent_model.owner_id is None):
        raise HTTPException(status_code=404, detail="Agent not found")

    executor = await build_agent_executor(db, agent_model)
    task = Task(description=payload.task)

    from app.core.auth.context import set_current_user_id, reset_current_user_id
    from app.core.harness.context import HarnessContext, reset_harness_context, set_harness_context

    ctx = set_current_user_id(user.id)

    execution = AgentExecution(
        id=generate_uuid(),
        agent_id=agent_id,
        task_description=payload.task,
        status=ExecutionStatus.running,
    )
    db.add(execution)
    await db.flush()

    harness_token = set_harness_context(
        HarnessContext(user_id=user.id, source="agent", source_id=execution.id)
    )

    if payload.stream:
        async def token_stream():
            try:
                async for token in executor.stream(task):
                    yield f"data: {json.dumps({'token': token})}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                reset_current_user_id(ctx)
                reset_harness_context(harness_token)

        return StreamingResponse(token_stream(), media_type="text/event-stream")

    try:
        result = await executor.run(task, context=payload.context, db=db)
        execution.status = ExecutionStatus.completed
        execution.output = result["output"]
        execution.token_usage = result.get("token_usage", {})
        trace = result.get("steps", [])
        if result.get("harness_trace"):
            trace = [*trace, {"harness_trace": result["harness_trace"]}]
        execution.steps = trace
    except Exception as e:
        execution.status = ExecutionStatus.failed
        execution.error_message = str(e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        reset_current_user_id(ctx)
        reset_harness_context(harness_token)
        await db.flush()

    return {
        "execution_id": execution.id,
        "output": execution.output,
        "token_usage": execution.token_usage,
        "steps": execution.steps,
        "harness_trace": result.get("harness_trace", []),
    }
