from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select
import json

from app.db.session import get_db
from app.db.models import (
    Agent as AgentModel,
    AgentEvent,
    AgentExecution,
    AgentShare,
    AgentShareGranteeType,
    AgentSharePermission,
    AgentStatus,
    AgentVisibility,
    Department,
    ExecutionStatus,
    User,
    WecomAgentBinding,
)
from app.db.base import generate_uuid
from pydantic import BaseModel, Field

from typing import Any

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
    from app.db.models import Conversation, DataSource, DigitalEmployee
    from sqlalchemy import func, update

    if is_platform_agent(agent):
        assert_admin_user(user, "delete platform agents")
    elif agent.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Digital employees require a live agent_id — block delete when still bound.
    emp_count = (
        await db.execute(
            select(func.count()).select_from(DigitalEmployee).where(DigitalEmployee.agent_id == agent_id)
        )
    ).scalar() or 0
    if emp_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent is bound to {emp_count} digital employee(s); unbind or delete them first",
        )

    # Detach nullable FKs so delete is not rolled back after a false 204.
    await db.execute(
        update(Conversation).where(Conversation.agent_id == agent_id).values(agent_id=None)
    )
    await db.execute(
        update(DataSource).where(DataSource.agent_id == agent_id).values(agent_id=None)
    )
    await db.delete(agent)
    # Flush before response so IntegrityError surfaces as 5xx instead of silent rollback.
    await db.flush()


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
    from app.core.harness.context import HarnessContext, ensure_session_directory, reset_harness_context, set_harness_context

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
        HarnessContext(user_id=user.id, source="agent", source_id=execution.id, working_directory=ensure_session_directory(execution.id))
    )

    if payload.stream:
        def _map_event(raw: dict) -> dict:
            """executor.stream_with_tools 原始事件 → SSE 事件（对标 Harness session/event）。

            向后兼容：assistant/stream 事件仍保留 token 字段，老前端只消费 token 的不会炸。
            """
            if "thinking" in raw:
                return {"type": "assistant/thinking", "thinking": raw["thinking"]}
            if "token" in raw:
                return {"type": "assistant/stream", "token": raw["token"]}
            if "tool_call" in raw:
                tc = raw["tool_call"]
                return {"type": "tool/call", "tool_call": tc, "name": tc.get("name", "")}
            if "tool_result" in raw:
                tr = raw["tool_result"]
                return {"type": "tool/result", "tool_result": tr, "name": tr.get("name", "")}
            # 兜底：原样透传，type 为 unknown
            return {"type": "unknown", **raw}

        async def event_stream():
            try:
                async for raw in executor.stream_with_tools(task, db=db, execution_id=str(execution.id)):
                    event = _map_event(raw)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'turn/end'})}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                reset_current_user_id(ctx)
                reset_harness_context(harness_token)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    try:
        result = await executor.run(task, context=payload.context, db=db, execution_id=str(execution.id))
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


# ── AgentExecution 事件回放（对标 Harness replay）──────────────────

@router.get("/executions/{execution_id}/events")
async def replay_execution_events(
    execution_id: str,
    limit: int = Query(default=500, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
):
    """Return the append-only event log for an AgentExecution (按 seq 递增).

    对标 Harness session event log replay：一条 execution 对应多条 AgentEvent，
    可用于前端 timeline 展示、问题排查、LLM 输入回放等场景。
    """
    exec_obj = await db.get(AgentExecution, execution_id)
    if not exec_obj:
        raise HTTPException(status_code=404, detail="execution not found")

    rows = (await db.execute(
        select(AgentEvent).where(AgentEvent.execution_id == execution_id)
        .order_by(AgentEvent.seq.asc())
        .limit(limit)
    )).scalars().all()

    return {
        "execution_id": execution_id,
        "agent_id": exec_obj.agent_id,
        "status": exec_obj.status.value if isinstance(exec_obj.status, ExecutionStatus) else exec_obj.status,
        "total_events": len(rows),
        "events": [
            {
                "seq": e.seq,
                "turn": e.turn,
                "step": e.step,
                "type": e.event_type,
                "name": e.name,
                "source": e.source,
                "level": e.level,
                "payload": e.payload,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in rows
        ],
    }


# ── 企业微信 Bot 关联（Bot → 智能体）─────────────────────────────

class AgentWecomBindingIn(BaseModel):
    bot_id: str = Field(..., min_length=1, max_length=128)
    enabled: bool = False
    chat_ids: list[str] = Field(default_factory=list)
    force: bool = False
    reply_template: str | None = Field(default=None, max_length=400)
    # 该智能体的显示样式覆盖，只写要改的项，空则全部继承全局
    style: dict[str, Any] | None = Field(default=None)


# 智能体级样式覆盖允许的键，需与企微全局样式保持一致
_STYLE_KEYS = frozenset({
    "theme", "font_size", "zebra", "show_title", "show_table", "show_chart",
    "table_max_rows", "table_dpi", "table_max_width", "show_thousands", "truncate_hint",
    "chart_type", "show_value_labels", "show_legend",
    "chart_width", "chart_height", "chart_dpi", "chart_max_labels",
    "text_template", "clip_bytes", "chat_limit",
    "voice_reply", "voice_name", "voice_max_chars",
    "voice_rate", "voice_volume", "voice_pitch",
    "voice_quiet_from", "voice_quiet_to",
})


def _mask_bot_id(bot_id: str) -> str:
    if not bot_id:
        return ""
    if len(bot_id) <= 12:
        return bot_id
    return f"{bot_id[:6]}…{bot_id[-6:]}"


def _wecom_connection() -> dict:
    from app.core.wecom.listener import wecom_link

    state = {
        "connected": "online",
        "relay": "online",
        "disconnected": "disconnected",
        "disabled": "disabled",
    }.get(str(wecom_link.status), "disconnected")
    return {"state": state, "raw": str(wecom_link.status)}


async def _require_agent_config(db: AsyncSession, agent_id: str, user: User) -> AgentModel:
    """管理员或智能体所有者（含 manage 授权）才能配置企业微信关联。"""
    agent = await db.get(AgentModel, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not user.is_admin:
        await require_agent_manage(db, agent, user)
    return agent


async def _wecom_payload(db: AsyncSession, agent_id: str) -> dict:
    from app.core.wecom.push import load_wecom_config, public_config

    config = public_config(await load_wecom_config(db))
    row = (
        await db.execute(select(WecomAgentBinding).where(WecomAgentBinding.agent_id == agent_id))
    ).scalars().first()
    bot_id = str(row.bot_id) if row else config["bot_id"]
    return {
        "agent_id": agent_id,
        "bound": row is not None,
        "bot_id": bot_id,
        "bot_id_masked": _mask_bot_id(bot_id),
        "bot_name": "",
        "enabled": bool(row.enabled) if row else False,
        "chat_ids": list(row.chat_ids or []) if row else [],
        "reply_template": str(row.reply_template or "") if row else "",
        "style": dict(row.style or {}) if row else {},
        "bot_configured": bool(config["bot_id"] and config["secret_set"]),
        "bot_config_enabled": bool(config["enabled"]),
        "receiver_chat_ids": config["chat_ids"],
        "connection": _wecom_connection(),
        "conflict_agent": None,
    }


@router.get("/{agent_id}/wecom")
async def get_agent_wecom(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _require_agent_config(db, agent_id, user)
    return await _wecom_payload(db, agent_id)


@router.put("/{agent_id}/wecom")
async def put_agent_wecom(
    agent_id: str,
    payload: AgentWecomBindingIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.core.wecom.push import load_wecom_config, public_config

    agent = await _require_agent_config(db, agent_id, user)
    bot_id = payload.bot_id.strip()
    config = public_config(await load_wecom_config(db))
    if not bot_id or bot_id != config["bot_id"]:
        raise HTTPException(
            status_code=400,
            detail="该 Bot 未在「设置 → 集成 → 企业微信」中配置，请先完成 BotID 与 Secret 配置",
        )
    if payload.enabled and not config["secret_set"]:
        raise HTTPException(status_code=400, detail="企业微信 Secret 未配置，无法启用关联")

    chat_ids = [str(item).strip() for item in payload.chat_ids if str(item).strip()][:50]

    other = (
        await db.execute(
            select(WecomAgentBinding).where(
                WecomAgentBinding.bot_id == bot_id, WecomAgentBinding.agent_id != agent_id
            )
        )
    ).scalars().first()
    if other and not payload.force:
        conflict = await db.get(AgentModel, other.agent_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "detail": f"该企业微信 Bot 已关联「{conflict.name if conflict else '其他智能体'}」，保存后将改绑到当前智能体",
                "code": "wecom_bot_taken",
                "conflict_agent": {
                    "id": other.agent_id,
                    "name": conflict.name if conflict else "",
                },
            },
        )
    if other:
        await db.delete(other)
        await db.flush()

    rows = (
        await db.execute(select(WecomAgentBinding).where(WecomAgentBinding.agent_id == agent_id))
    ).scalars().all()
    row = rows[0] if rows else None
    for extra in rows[1:]:
        await db.delete(extra)
    # 只保留样式白名单键，部分覆盖；空字典视为继承全局
    override = {
        key: value
        for key, value in (payload.style or {}).items()
        if key in _STYLE_KEYS and value not in (None, "")
    }
    if row:
        row.bot_id = bot_id
        row.enabled = bool(payload.enabled)
        row.chat_ids = chat_ids
        row.reply_template = (payload.reply_template or "").strip() or None
        row.style = override or None
    else:
        db.add(WecomAgentBinding(
            id=generate_uuid(),
            bot_id=bot_id,
            agent_id=agent_id,
            enabled=bool(payload.enabled),
            chat_ids=chat_ids,
            reply_template=(payload.reply_template or "").strip() or None,
            style=override or None,
            created_by=user.id,
        ))
    await write_agent_share_audit(
        db,
        actor_id=user.id,
        agent_id=agent_id,
        action="wecom_bind",
        details={"bot_id": bot_id, "enabled": bool(payload.enabled), "rebind": bool(other)},
    )
    await db.flush()
    await db.commit()
    out = await _wecom_payload(db, agent_id)
    out["agent_name"] = agent.name
    return out


@router.delete("/{agent_id}/wecom", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_wecom(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _require_agent_config(db, agent_id, user)
    await db.execute(delete(WecomAgentBinding).where(WecomAgentBinding.agent_id == agent_id))
    await write_agent_share_audit(
        db,
        actor_id=user.id,
        agent_id=agent_id,
        action="wecom_unbind",
        details={},
    )
    await db.commit()


@router.post("/{agent_id}/wecom/test")
async def test_agent_wecom(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.core.wecom.push import load_wecom_config, public_config, push_markdown

    agent = await _require_agent_config(db, agent_id, user)
    config = public_config(await load_wecom_config(db))
    if not config["enabled"] or not config["bot_id"] or not config["secret_set"]:
        raise HTTPException(status_code=400, detail="请先在「设置 → 集成 → 企业微信」启用并保存 BotID 与 Secret")
    row = (
        await db.execute(select(WecomAgentBinding).where(WecomAgentBinding.agent_id == agent_id))
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=400, detail="请先保存关联，再测试连接")
    targets = config["chat_ids"] or list(row.chat_ids or [])
    if not targets:
        raise HTTPException(
            status_code=400,
            detail="请先在「设置 → 集成 → 企业微信」填写接收人（企微 userid），测试消息会发给他",
        )
    content = f"**企业微信关联测试**\n\n当前 Bot 已关联智能体「{agent.name}」，这条是测试消息。"
    from app.core.wecom.listener import wecom_link

    if wecom_link.status == "connected":
        result = await wecom_link.send_markdown(targets, content)
    else:
        result = await push_markdown(db, targets, content)
    return {**result, "connection": _wecom_connection()}

