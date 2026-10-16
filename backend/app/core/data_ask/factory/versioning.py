"""Agent Evolution 阶段三 L3：配置版本化（快照 / diff / 回滚 / 发布与灰度）。

与 ML Evolution 同一套「择优晋升」哲学：配置每次再生成产生新版本，
发布（production）唯一，历史版本自动转 retired；支持 diff 与一键回滚。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent as AgentModel, AgentRelease, AgentVersion, User

logger = logging.getLogger("agent_factory_versioning")

_SPEC_FIELDS = (
    "name", "role", "goal", "backstory", "temperature", "max_iterations",
    "llm_provider", "llm_model", "tools_config", "skills_config", "memory_config",
)


def agent_spec(agent: AgentModel) -> dict[str, Any]:
    """提取智能体可编辑配置字段作为版本快照。"""
    spec = {f: getattr(agent, f, None) for f in _SPEC_FIELDS}
    spec["metadata_"] = dict(agent.metadata_ or {})
    return spec


def apply_spec(agent: AgentModel, spec: dict[str, Any]) -> None:
    """把版本快照写回智能体记录（完全兼容现有 Agent 体系）。"""
    for f in _SPEC_FIELDS:
        if f in spec and spec[f] is not None:
            setattr(agent, f, spec[f])
    if isinstance(spec.get("metadata_"), dict):
        agent.metadata_ = spec["metadata_"]


def _norm(value: Any) -> str:
    import json

    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def diff_specs(base: dict[str, Any] | None, target: dict[str, Any] | None) -> list[dict[str, Any]]:
    """逐字段 diff：返回 [{field, old, new, changed, old_preview, new_preview}]。"""
    base = base or {}
    target = target or {}
    fields = list(dict.fromkeys(list(base.keys()) + list(target.keys())))
    out: list[dict[str, Any]] = []
    for f in fields:
        old, new = base.get(f), target.get(f)
        changed = _norm(old) != _norm(new)
        out.append({
            "field": f,
            "changed": changed,
            "old": old,
            "new": new,
            "old_preview": _norm(old)[:300],
            "new_preview": _norm(new)[:300],
        })
    return out


async def next_version(db: AsyncSession, agent_id: str) -> int:
    res = await db.execute(
        select(AgentVersion.version)
        .where(AgentVersion.agent_id == str(agent_id))
        .order_by(AgentVersion.version.desc())
        .limit(1)
    )
    last = res.scalar_one_or_none()
    return (last + 1) if last else 1


async def list_versions(db: AsyncSession, agent_id: str) -> list[AgentVersion]:
    res = await db.execute(
        select(AgentVersion)
        .where(AgentVersion.agent_id == str(agent_id))
        .order_by(AgentVersion.version.desc())
    )
    return list(res.scalars().all())


async def active_version(db: AsyncSession, agent_id: str) -> AgentVersion | None:
    res = await db.execute(
        select(AgentVersion)
        .where(AgentVersion.agent_id == str(agent_id), AgentVersion.status == "production")
        .order_by(AgentVersion.version.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def find_version(db: AsyncSession, agent_id: str, version_id: int) -> AgentVersion | None:
    row = await db.get(AgentVersion, version_id)
    if not row or row.agent_id != str(agent_id):
        return None
    return row


async def snapshot(
    db: AsyncSession,
    agent: AgentModel,
    *,
    source: str = "factory",
    note: str | None = None,
    coach: dict[str, Any] | None = None,
    status: str = "candidate",
    spec: dict[str, Any] | None = None,
) -> AgentVersion:
    """为智能体配置创建新版本快照（不改变 production 状态）。

    spec 为空时快照智能体当前配置；传入 spec 则快照给定的候选配置（不改动智能体记录）。
    """
    version = await next_version(db, str(agent.id))
    row = AgentVersion(
        agent_id=str(agent.id),
        data_source_id=str((agent.metadata_ or {}).get("data_source_id") or "") or None,
        version=version,
        spec=spec if spec is not None else agent_spec(agent),
        coach=coach,
        source=source,
        note=(note or "")[:500] or None,
        status=status,
    )
    db.add(row)
    await db.flush()
    return row


async def promote(db: AsyncSession, agent: AgentModel, version_row: AgentVersion) -> AgentVersion:
    """把指定版本置为 production，同智能体其他版本转 retired。"""
    await db.execute(
        update(AgentVersion)
        .where(AgentVersion.agent_id == str(agent.id), AgentVersion.id != version_row.id)
        .values(status="retired")
    )
    version_row.status = "production"
    await db.flush()
    return version_row


async def rollback(
    db: AsyncSession,
    agent: AgentModel,
    version_row: AgentVersion,
    *,
    user: User,
    note: str | None = None,
) -> AgentVersion:
    """一键回滚：把目标版本 spec 写回智能体，并生成一条 rollback 来源的新 production 版本留痕。"""
    apply_spec(agent, dict(version_row.spec or {}))
    await db.flush()
    new_row = await snapshot(
        db, agent, source="rollback",
        note=note or f"回滚至 v{version_row.version}",
        coach=version_row.coach,
    )
    await promote(db, agent, new_row)
    await release(db, agent, new_row, scope="full", gray_users=[], user=user, note=f"回滚发布（源 v{version_row.version}）")
    return new_row


async def release(
    db: AsyncSession,
    agent: AgentModel,
    version_row: AgentVersion,
    *,
    scope: str = "full",
    gray_users: list[str] | None = None,
    user: User | None = None,
    note: str | None = None,
) -> AgentRelease:
    """发布某个版本（全量 / 灰度），旧的 active 发布记录自动下线。"""
    await db.execute(
        update(AgentRelease)
        .where(AgentRelease.agent_id == str(agent.id), AgentRelease.active.is_(True))
        .values(active=False)
    )
    row = AgentRelease(
        agent_id=str(agent.id),
        version_id=int(version_row.id),
        version=int(version_row.version),
        scope="gray" if scope == "gray" else "full",
        gray_users=[str(u) for u in (gray_users or [])][:200],
        active=True,
        released_by=str(user.id) if user else None,
        note=(note or "")[:500] or None,
    )
    db.add(row)
    await db.flush()
    return row


async def list_releases(db: AsyncSession, agent_id: str) -> list[AgentRelease]:
    res = await db.execute(
        select(AgentRelease)
        .where(AgentRelease.agent_id == str(agent_id))
        .order_by(AgentRelease.created_at.desc(), AgentRelease.id.desc())
    )
    return list(res.scalars().all())
