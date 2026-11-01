"""策略加载与（版本化）更新。

当前策略 = version 最大的一条。更新总是**新增一个版本**（不可变），并把各来源部分
前滚复制，再应用变更，这样每个 Mandate 记录的 policy_version 始终指向确定的规则组合。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sources.registry import SOURCE_KINDS
from app.db.models import SuperagentPolicy, SuperagentPolicySource

ACCEPT_MODES = ("off", "observe", "auto")

# 参与 Gate 的「人来源」（schedule 为系统触发，不过 Gate）
PERSON_SOURCE_KINDS = ("feishu", "dingtalk")


async def ensure_default_policy() -> None:
    """幂等地确保存在一个默认策略（observe 模式、空允许名单）。

    使用独立会话提交，避免在调用方（如入库）的事务里创建，防止竞态污染。
    """
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        exists = (
            await db.execute(select(SuperagentPolicy.id).limit(1))
        ).scalar_one_or_none()
        if exists is not None:
            return
        policy = SuperagentPolicy(version=1, accept_mode="observe", rules=[], note="default")
        db.add(policy)
        try:
            await db.flush()
            for kind in PERSON_SOURCE_KINDS:
                db.add(
                    SuperagentPolicySource(
                        policy_id=policy.id, source_kind=kind, allowlist=[], bot_list=[]
                    )
                )
            await db.commit()
        except IntegrityError:
            await db.rollback()  # 并发下已被别人创建


async def get_current_policy(db: AsyncSession) -> SuperagentPolicy:
    """返回当前策略（version 最大的一条）。若不存在会先幂等创建默认策略。"""
    result = await db.execute(
        select(SuperagentPolicy).order_by(SuperagentPolicy.version.desc()).limit(1)
    )
    policy = result.scalar_one_or_none()
    if policy is not None:
        return policy
    await ensure_default_policy()
    result = await db.execute(
        select(SuperagentPolicy).order_by(SuperagentPolicy.version.desc()).limit(1)
    )
    return result.scalar_one()


async def _sources_for(db: AsyncSession, policy_id: str) -> list[SuperagentPolicySource]:
    result = await db.execute(
        select(SuperagentPolicySource).where(SuperagentPolicySource.policy_id == policy_id)
    )
    return list(result.scalars().all())


async def get_policy_source(
    db: AsyncSession, policy: SuperagentPolicy, source_kind: str
) -> SuperagentPolicySource | None:
    result = await db.execute(
        select(SuperagentPolicySource).where(
            SuperagentPolicySource.policy_id == policy.id,
            SuperagentPolicySource.source_kind == source_kind,
        )
    )
    return result.scalar_one_or_none()


async def get_policy_view(db: AsyncSession) -> dict[str, Any]:
    policy = await get_current_policy(db)
    sources = await _sources_for(db, policy.id)
    by_kind = {s.source_kind: s for s in sources}
    return {
        "version": policy.version,
        "accept_mode": policy.accept_mode,
        "rules": policy.rules or [],
        "note": policy.note,
        "sources": [
            {
                "source_kind": kind,
                "label": SOURCE_KINDS.get(kind, kind),
                "allowlist": (by_kind[kind].allowlist if kind in by_kind else []),
                "bot_list": (by_kind[kind].bot_list if kind in by_kind else []),
            }
            for kind in PERSON_SOURCE_KINDS
        ],
    }


async def update_policy(
    db: AsyncSession,
    *,
    accept_mode: str | None = None,
    rules: list[dict] | None = None,
    note: str | None = None,
    sources: dict[str, dict] | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """创建一个新策略版本，前滚复制未变更的部分。返回新版本视图。"""
    current = await get_current_policy(db)
    current_sources = {s.source_kind: s for s in await _sources_for(db, current.id)}

    if accept_mode is not None and accept_mode not in ACCEPT_MODES:
        raise ValueError(f"accept_mode must be one of {ACCEPT_MODES}")

    new_version = current.version + 1
    new_policy = SuperagentPolicy(
        version=new_version,
        accept_mode=accept_mode if accept_mode is not None else current.accept_mode,
        rules=rules if rules is not None else (current.rules or []),
        note=note if note is not None else current.note,
        created_by=created_by,
    )
    db.add(new_policy)
    await db.flush()

    sources = sources or {}
    for kind in PERSON_SOURCE_KINDS:
        prev = current_sources.get(kind)
        incoming = sources.get(kind) or {}
        allowlist = incoming.get("allowlist")
        bot_list = incoming.get("bot_list")
        db.add(
            SuperagentPolicySource(
                policy_id=new_policy.id,
                source_kind=kind,
                allowlist=allowlist if allowlist is not None else (prev.allowlist if prev else []),
                bot_list=bot_list if bot_list is not None else (prev.bot_list if prev else []),
            )
        )
    await db.commit()
    return await get_policy_view(db)
