"""智能体工厂服务编排：生成 → 发布（落标准 Agent 记录 + 版本快照 + 发布记录）。"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.factory import versioning
from app.core.data_ask.factory.coach import build_coach_profile
from app.core.data_ask.factory.generator import generate_factory_spec
from app.db.base import generate_uuid
from app.db.models import Agent as AgentModel, AgentRelease, AgentStatus, AgentVersion, DataSource, User

logger = logging.getLogger("agent_factory_service")


async def publish_agent(
    db: AsyncSession,
    source: DataSource,
    user: User,
    spec: dict[str, Any],
    *,
    coach: dict[str, Any] | None = None,
    note: str | None = None,
) -> tuple[AgentModel, AgentVersion, AgentRelease]:
    """把工厂配置发布为标准 Agent 记录：创建或更新 + 版本快照 + 全量发布。"""
    agent: AgentModel | None = None
    if source.agent_id:
        agent = await db.get(AgentModel, str(source.agent_id))

    if agent is None:
        agent = AgentModel(
            id=generate_uuid(),
            owner_id=user.id,
            status=AgentStatus.active,
            visibility="private",
        )
        versioning.apply_spec(agent, spec)
        db.add(agent)
        await db.flush()
        source.agent_id = agent.id
    else:
        versioning.apply_spec(agent, spec)
        await db.flush()

    version_row = await versioning.snapshot(
        db, agent, source="factory", note=note, coach=coach, status="production",
    )
    await versioning.promote(db, agent, version_row)
    rel = await versioning.release(
        db, agent, version_row, scope="full", gray_users=[], user=user, note=note or "工厂发布",
    )
    logger.info("factory_publish agent=%s ds=%s version=%s", agent.id, source.id, version_row.version)
    return agent, version_row, rel


async def regenerate_candidate(
    db: AsyncSession, source: DataSource, *, nl_prompt: str | None = None, note: str | None = None,
) -> AgentVersion | None:
    """蒸馏后再生成：为已绑定智能体创建新候选版本（不自动发布）。"""
    if not source.agent_id:
        return None
    agent = await db.get(AgentModel, str(source.agent_id))
    if not agent:
        return None
    coach = await build_coach_profile(db, source)
    spec = await generate_factory_spec(db, source, coach, nl_prompt=nl_prompt)
    spec.pop("opening_questions", None)
    row = await versioning.snapshot(
        db, agent, source="factory", note=note or "蒸馏后再生成候选", coach=coach,
        status="candidate", spec=spec,
    )
    return row
