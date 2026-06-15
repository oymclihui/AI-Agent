from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json

from app.db.session import get_db
from app.db.models import (
    Agent as AgentModel,
    AgentExecution,
    AgentShare,
    AgentShareGranteeType,
    AgentSharePermission,
    AgentStatus,
    AgentVisibility,
    Department,
    ExecutionStatus,
    User,
)
from app.db.base import generate_uuid
from pydantic import BaseModel, Field
from app.schemas.agent import (
    AgentCreate,
    AgentUpdate,
    AgentResponse,
    AgentRunRequest,
    AgentLibraryImportRequest,
    AgentLibraryTemplate,
    AgentSharingUpdate,
    AgentSharingResponse,
    AgentShareGrantOut,
    AgentShareTargetsResponse,
    ShareTargetUser,
    ShareTargetDepartment,
    AgentVisibility as SchemaAgentVisibility,
    AgentShareGranteeType as SchemaGranteeType,
    AgentSharePermission as SchemaSharePermission,
)
from app.config import settings
from app.core.agents.base import AgentDefinition, Task
from app.core.skills.factory import build_agent_executor
from app.core.auth.deps import get_current_user
from app.core.auth.scoping import assert_admin_user
from app.core.auth.agent_access import (
    AgentListScope,
    assert_agent_owner,
    can_manage_agent,
    enrich_agent_response,
    list_agents_filter,
    require_agent_manage,
    require_agent_use,
    require_agent_view,
    write_agent_share_audit,
    is_platform_agent,
)

router = APIRouter(prefix="/agents", tags=["Agents"])


async def _agent_response(db: AsyncSession, agent: AgentModel, user: User, lang: str | None) -> dict:
    from app.core.agents.i18n import agent_to_response_dict

    base = agent_to_response_dict(agent, lang)
    return await enrich_agent_response(db, agent, user, base)


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
        visibility=AgentVisibility.private.value,
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return await _agent_response(db, agent, user, None)


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
    scope: AgentListScope = Query("usable", description="mine|shared|org|platform|usable|all"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    filt = await list_agents_filter(db, user, scope)
    result = await db.execute(
        select(AgentModel).where(filt).order_by(AgentModel.created_at.desc())
    )
    agents = result.scalars().all()
    out = []
    for agent in agents:
        out.append(await _agent_response(db, agent, user, lang))
    return out


@router.get("/share-targets", response_model=AgentShareTargetsResponse)
async def agent_share_targets(
    q: str = Query("", max_length=128),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from sqlalchemy import or_, func

    users_out: list[ShareTargetUser] = []
    term = q.strip()
    if term:
        pattern = f"%{term}%"
        user_rows = await db.execute(
            select(User)
            .where(
                User.is_active == True,
                User.id != user.id,
                or_(
                    User.display_name.ilike(pattern),
                    User.employee_no.ilike(pattern),
                    func.lower(User.email).like(pattern.lower()),
                ),
            )
            .order_by(User.display_name.asc())
            .limit(30)
        )
        users_out = [
            ShareTargetUser(
                id=u.id,
                display_name=u.display_name,
                employee_no=u.employee_no,
                primary_department_id=u.primary_department_id,
            )
            for u in user_rows.scalars().all()
        ]

    dept_rows = await db.execute(
        select(Department)
        .where(Department.is_active == True)
        .order_by(Department.path.asc())
        .limit(200)
    )
    departments = [
        ShareTargetDepartment(id=d.id, name=d.name, path=d.path or "")
        for d in dept_rows.scalars().all()
    ]
    return AgentShareTargetsResponse(users=users_out, departments=departments)


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
        visibility=AgentVisibility.private.value,
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return await _agent_response(db, agent, user, None)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    lang: str | None = Query(None, description="UI language: zh | en"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.core.agents.i18n import agent_to_response_dict

    agent = await db.get(AgentModel, agent_id)
    agent = await require_agent_view(db, agent, user)
    return await _agent_response(db, agent, user, lang)


@router.get("/{agent_id}/sharing", response_model=AgentSharingResponse)
async def get_agent_sharing(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = await db.get(AgentModel, agent_id)
    agent = await require_agent_view(db, agent, user)
    is_owner = agent.owner_id == user.id
    if not is_owner and not user.is_admin:
        raise HTTPException(status_code=403, detail="Only the owner can view sharing settings")

    grants = await _serialize_grants(db, agent_id)
    try:
        vis = SchemaAgentVisibility(str(agent.visibility or AgentVisibility.private.value))
    except ValueError:
        vis = SchemaAgentVisibility.private
    return AgentSharingResponse(
        visibility=vis,
        grants=grants,
        is_owner=is_owner,
    )


async def _serialize_grants(db: AsyncSession, agent_id: str) -> list[AgentShareGrantOut]:
    result = await db.execute(select(AgentShare).where(AgentShare.agent_id == agent_id))
    rows = list(result.scalars().all())
    user_ids = {r.grantee_id for r in rows if r.grantee_type == AgentShareGranteeType.user}
    dept_ids = {r.grantee_id for r in rows if r.grantee_type == AgentShareGranteeType.department}
    user_names: dict[str, str] = {}
    dept_names: dict[str, str] = {}
    if user_ids:
        ur = await db.execute(select(User.id, User.display_name).where(User.id.in_(user_ids)))
        user_names = {row[0]: row[1] for row in ur.all()}
    if dept_ids:
        dr = await db.execute(select(Department.id, Department.name).where(Department.id.in_(dept_ids)))
        dept_names = {row[0]: row[1] for row in dr.all()}
    out: list[AgentShareGrantOut] = []
    for row in rows:
        name = user_names.get(row.grantee_id, "") if row.grantee_type == AgentShareGranteeType.user else dept_names.get(row.grantee_id, "")
        out.append(AgentShareGrantOut(
            id=row.id,
            grantee_type=SchemaGranteeType(
                row.grantee_type.value if hasattr(row.grantee_type, "value") else row.grantee_type
            ),
            grantee_id=row.grantee_id,
            grantee_name=name or row.grantee_id[:8],
            permission=SchemaSharePermission(
                row.permission.value if hasattr(row.permission, "value") else row.permission
            ),
        ))
    return out


@router.put("/{agent_id}/sharing", response_model=AgentSharingResponse)
async def update_agent_sharing(
    agent_id: str,
    payload: AgentSharingUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = await db.get(AgentModel, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    assert_agent_owner(agent, user)
    if is_platform_agent(agent):
        raise HTTPException(status_code=403, detail="Cannot change sharing on platform agents")

    before = {"visibility": str(agent.visibility or AgentVisibility.private.value)}
    vis_value = (
        payload.visibility.value
        if isinstance(payload.visibility, SchemaAgentVisibility)
        else str(payload.visibility)
    )
    agent.visibility = vis_value

    existing = await db.execute(select(AgentShare).where(AgentShare.agent_id == agent_id))
    for row in existing.scalars().all():
        await db.delete(row)

    if vis_value == AgentVisibility.shared.value:
        for grant in payload.grants:
            db.add(AgentShare(
                id=generate_uuid(),
                agent_id=agent_id,
                grantee_type=AgentShareGranteeType(
                    grant.grantee_type.value if hasattr(grant.grantee_type, "value") else grant.grantee_type
                ),
                grantee_id=grant.grantee_id,
                permission=AgentSharePermission(
                    grant.permission.value if hasattr(grant.permission, "value") else grant.permission
                ),
                granted_by=user.id,
            ))

    await write_agent_share_audit(
        db,
        actor_id=user.id,
        agent_id=agent_id,
        action="sharing_update",
        details={"before": before, "after": payload.model_dump(mode="json")},
    )
    await db.flush()
    grants = await _serialize_grants(db, agent_id)
    try:
        vis = SchemaAgentVisibility(str(agent.visibility or AgentVisibility.private.value))
    except ValueError:
        vis = SchemaAgentVisibility.private
    return AgentSharingResponse(
        visibility=vis,
        grants=grants,
        is_owner=True,
    )


@router.post("/{agent_id}/copy", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def copy_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await db.get(AgentModel, agent_id)
    source = await require_agent_use(db, source, user)
    if source.owner_id == user.id:
        raise HTTPException(status_code=400, detail="Already yours — edit directly instead of copying")

    clone = AgentModel(
        id=generate_uuid(),
        owner_id=user.id,
        name=f"{source.name} (副本)" if any("\u4e00" <= c <= "\u9fff" for c in source.name) else f"{source.name} (copy)",
        role=source.role,
        goal=source.goal,
        backstory=source.backstory,
        status=AgentStatus.active,
        visibility=AgentVisibility.private.value,
        llm_provider=source.llm_provider,
        llm_model=source.llm_model,
        temperature=source.temperature,
        max_iterations=source.max_iterations,
        tools_config=list(source.tools_config or []),
        skills_config=list(source.skills_config or []),
        memory_config=dict(source.memory_config or {}),
        metadata_=dict(source.metadata_ or {}),
    )
    db.add(clone)
    await db.flush()
    await db.refresh(clone)
    await write_agent_share_audit(
        db,
        actor_id=user.id,
        agent_id=agent_id,
        action="agent_copy",
        details={"new_agent_id": clone.id},
    )
    return await _agent_response(db, clone, user, None)


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

    update_data = payload.model_dump(exclude_none=True)
    admin_takedown = (
        user.is_admin
        and "status" in update_data
        and update_data.get("status") == AgentStatus.inactive
        and len(update_data) == 1
    )
    if not admin_takedown:
        await require_agent_manage(db, agent, user)

    if "name" in update_data:
        from app.core.agents.i18n import apply_agent_name_update

        apply_agent_name_update(agent, update_data.pop("name"))

    for field, value in update_data.items():
        if field == "tools_config" and value is not None:
            agent.tools_config = [t if isinstance(t, dict) else t for t in value]
        elif field == "skills_config" and value is not None:
            agent.skills_config = [s if isinstance(s, dict) else s for s in value]
        elif field == "memory_config" and value is not None:
            agent.memory_config = value if isinstance(value, dict) else value
        else:
            setattr(agent, field, value)

    if admin_takedown:
        await write_agent_share_audit(
            db,
            actor_id=user.id,
            agent_id=agent_id,
            action="admin_takedown",
            details={"status": "inactive"},
        )

    await db.flush()
    await db.refresh(agent)
    return await _agent_response(db, agent, user, None)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = await db.get(AgentModel, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    from app.core.auth.agent_access import is_platform_agent

    if is_platform_agent(agent):
        assert_admin_user(user, "delete platform agents")
    elif agent.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.delete(agent)


@router.post("/{agent_id}/run")
async def run_agent(
    agent_id: str,
    payload: AgentRunRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent_model = await db.get(AgentModel, agent_id)
    agent_model = await require_agent_use(db, agent_model, user)

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
