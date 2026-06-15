"""Agent visibility, sharing ACL, and access checks."""
from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import and_, false as sql_false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Agent,
    AgentShare,
    AgentShareGranteeType,
    AgentSharePermission,
    AgentStatus,
    AgentVisibility,
    Department,
    User,
    UserDepartment,
)

AgentListScope = Literal["usable", "mine", "shared", "org", "platform", "all"]

_USE_LEVEL = frozenset({AgentSharePermission.view, AgentSharePermission.use, AgentSharePermission.manage})
_VIEW_LEVEL = frozenset({AgentSharePermission.view, AgentSharePermission.use, AgentSharePermission.manage})
_MANAGE_LEVEL = frozenset({AgentSharePermission.manage})


def effective_visibility(agent: Agent) -> AgentVisibility:
    raw = agent.visibility
    if raw is None:
        return AgentVisibility.platform if agent.owner_id is None else AgentVisibility.private
    if isinstance(raw, AgentVisibility):
        vis = raw
    else:
        try:
            vis = AgentVisibility(str(raw))
        except ValueError:
            vis = AgentVisibility.private
    if agent.owner_id is None and vis == AgentVisibility.private:
        return AgentVisibility.platform
    return vis


def _vis_col(value: AgentVisibility) -> str:
    return value.value if isinstance(value, AgentVisibility) else str(value)


def is_platform_agent(agent: Agent) -> bool:
    return effective_visibility(agent) == AgentVisibility.platform


async def user_department_ids(db: AsyncSession, user_id: str) -> set[str]:
    ids: set[str] = set()
    user = await db.get(User, user_id)
    if user and user.primary_department_id:
        ids.add(user.primary_department_id)
    result = await db.execute(
        select(UserDepartment.department_id).where(UserDepartment.user_id == user_id)
    )
    ids.update(row[0] for row in result.all())
    return ids


async def department_path_map(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(
        select(Department.id, Department.path).where(Department.is_active == True)
    )
    return {row[0]: row[1] for row in result.all() if row[1]}


async def shared_agent_permissions(
    db: AsyncSession,
    user_id: str,
) -> dict[str, set[AgentSharePermission]]:
    """Map agent_id -> permissions granted via agent_shares (not including owner/org/platform)."""
    user_dept_ids = await user_department_ids(db, user_id)
    dept_paths = await department_path_map(db)

    user_dept_paths = [dept_paths[d] for d in user_dept_ids if d in dept_paths]

    result = await db.execute(select(AgentShare))
    perms: dict[str, set[AgentSharePermission]] = {}
    for share in result.scalars().all():
        matched = False
        if share.grantee_type == AgentShareGranteeType.user and share.grantee_id == user_id:
            matched = True
        elif share.grantee_type == AgentShareGranteeType.department:
            grant_path = dept_paths.get(share.grantee_id)
            if grant_path and user_dept_paths:
                for user_path in user_dept_paths:
                    if user_path == grant_path or user_path.startswith(grant_path):
                        matched = True
                        break
        if matched:
            perms.setdefault(share.agent_id, set()).add(share.permission)
    return perms


def _perm_level(granted: set[AgentSharePermission], needed: frozenset) -> bool:
    return bool(granted & needed)


async def can_view_agent(db: AsyncSession, agent: Agent, user: User) -> bool:
    if user.is_admin:
        return True
    if agent.owner_id == user.id:
        return True
    if agent.status != AgentStatus.active:
        return False
    vis = effective_visibility(agent)
    if vis == AgentVisibility.platform or vis == AgentVisibility.org:
        return True
    if vis == AgentVisibility.shared:
        shared = await shared_agent_permissions(db, user.id)
        return _perm_level(shared.get(agent.id, set()), _VIEW_LEVEL)
    return False


async def can_use_agent(db: AsyncSession, agent: Agent, user: User) -> bool:
    if user.is_admin:
        return True
    if agent.owner_id == user.id:
        return agent.status == AgentStatus.active
    if agent.status != AgentStatus.active:
        return False
    vis = effective_visibility(agent)
    if vis in (AgentVisibility.platform, AgentVisibility.org):
        return True
    if vis == AgentVisibility.shared:
        shared = await shared_agent_permissions(db, user.id)
        return _perm_level(shared.get(agent.id, set()), _USE_LEVEL)
    return False


async def can_manage_agent(db: AsyncSession, agent: Agent, user: User) -> bool:
    if is_platform_agent(agent):
        return user.is_admin
    if agent.owner_id == user.id:
        return True
    if agent.status != AgentStatus.active:
        return agent.owner_id == user.id
    shared = await shared_agent_permissions(db, user.id)
    return _perm_level(shared.get(agent.id, set()), _MANAGE_LEVEL)


def assert_agent_owner(agent: Agent, user: User) -> None:
    if agent.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner can change sharing")


async def require_agent_view(db: AsyncSession, agent: Agent | None, user: User) -> Agent:
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if not await can_view_agent(db, agent, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


async def require_agent_use(db: AsyncSession, agent: Agent | None, user: User) -> Agent:
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if not await can_use_agent(db, agent, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


async def require_agent_manage(db: AsyncSession, agent: Agent | None, user: User) -> Agent:
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if not await can_manage_agent(db, agent, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return agent


async def list_agents_filter(
    db: AsyncSession,
    user: User,
    scope: AgentListScope,
) -> list:
    """Return SQLAlchemy filter clause for Agent list queries."""
    if user.is_admin and scope == "all":
        return true()

    shared = await shared_agent_permissions(db, user.id)
    shared_ids = list(shared.keys())

    active = Agent.status == AgentStatus.active
    mine = Agent.owner_id == user.id
    platform = and_(Agent.visibility == _vis_col(AgentVisibility.platform), active)
    org_vis = and_(Agent.visibility == _vis_col(AgentVisibility.org), active)
    if shared_ids:
        shared_vis = and_(
            Agent.visibility == _vis_col(AgentVisibility.shared),
            Agent.id.in_(shared_ids),
            active,
        )
    else:
        shared_vis = sql_false()

    if scope == "mine":
        return mine
    if scope == "platform":
        return platform
    if scope == "org":
        return and_(org_vis, Agent.owner_id != user.id)
    if scope == "shared":
        return and_(shared_vis, Agent.owner_id != user.id)
    if scope == "usable":
        return or_(
            mine,
            platform,
            org_vis,
            shared_vis,
        )
    if scope == "all":
        return or_(mine, platform, org_vis, shared_vis)
    return mine


async def enrich_agent_response(
    db: AsyncSession,
    agent: Agent,
    user: User,
    base: dict,
) -> dict:
    out = dict(base)
    out["visibility"] = effective_visibility(agent).value
    out["is_owner"] = agent.owner_id == user.id
    out["can_manage"] = await can_manage_agent(db, agent, user)
    return out


async def write_agent_share_audit(
    db: AsyncSession,
    *,
    actor_id: str,
    agent_id: str,
    action: str,
    details: dict,
) -> None:
    from app.db.base import generate_uuid
    from app.db.models import AgentShareAuditLog

    db.add(AgentShareAuditLog(
        id=generate_uuid(),
        actor_user_id=actor_id,
        agent_id=agent_id,
        action=action,
        details=details,
    ))
