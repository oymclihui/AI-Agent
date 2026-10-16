"""Agent Evolution 阶段三 L3 API：智能体工厂 —— 四步养成向导 + 配置版本化。

- GET    /data-sources/{sid}/factory/coach            养成画像（第②步：就绪度/能力/缺口）
- POST   /data-sources/{sid}/factory/generate         生成配置草案（第③步，不落库）
- POST   /data-sources/{sid}/factory/publish          发布为标准 Agent + 版本快照 + 发布记录
- POST   /data-sources/{sid}/factory/trial            试跑（第④步，真实问数链路验证）
- POST   /data-sources/{sid}/factory/regenerate       蒸馏后再生成候选版本（Celery 异步）
- GET    /agents/{aid}/versions                      版本列表
- GET    /agents/{aid}/versions/{vid}/diff            配置 diff（相对现役或指定基线）
- POST   /agents/{aid}/versions/{vid}/rollback        一键回滚
- GET    /agents/{aid}/releases                       发布记录
- POST   /agents/{aid}/releases                       发布 / 灰度白名单
写操作需数据源或智能体 manage 权限。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.agent_access import require_agent_manage
from app.core.auth.deps import get_current_user
from app.core.data_ask.govern.access import assert_data_source_access
from app.db.models import Agent as AgentModel, AgentRelease, AgentVersion, DataSource, User
from app.db.session import get_db
from app.schemas.ds_factory import (
    CoachOut,
    DiffItemOut,
    DiffOut,
    GenerateSpecIn,
    GenerateSpecOut,
    PublishIn,
    PublishOut,
    ReleaseIn,
    ReleaseOut,
    RollbackIn,
    SpecOut,
    TrialIn,
    TrialOut,
    VersionOut,
)

router = APIRouter(tags=["DsFactory"])


async def _get_source(db: AsyncSession, sid: str) -> DataSource:
    source = await db.get(DataSource, sid)
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return source


async def _get_agent(db: AsyncSession, aid: str) -> AgentModel:
    agent = await db.get(AgentModel, aid)
    if not agent:
        raise HTTPException(status_code=404, detail="智能体不存在")
    return agent


def _version_out(row: AgentVersion) -> VersionOut:
    return VersionOut(
        id=row.id, agent_id=row.agent_id, data_source_id=row.data_source_id,
        version=row.version, source=row.source, note=row.note, status=row.status,
        spec=row.spec or {}, coach=row.coach, created_at=row.created_at,
    )


def _release_out(row: AgentRelease) -> ReleaseOut:
    return ReleaseOut(
        id=row.id, agent_id=row.agent_id, version_id=row.version_id, version=row.version,
        scope=row.scope, gray_users=[str(u) for u in (row.gray_users or [])],
        active=bool(row.active), released_by=row.released_by, note=row.note,
        created_at=row.created_at,
    )


# ────────────────────── 四步向导：画像 / 生成 / 试跑 / 发布 ──────────────────────

@router.get("/data-sources/{sid}/factory/coach", response_model=CoachOut)
async def factory_coach(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    from app.core.data_ask.factory.coach import build_coach_profile

    return CoachOut(**await build_coach_profile(db, source))


@router.post("/data-sources/{sid}/factory/generate", response_model=GenerateSpecOut)
async def factory_generate(
    sid: str,
    payload: GenerateSpecIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    from app.core.data_ask.factory.coach import build_coach_profile
    from app.core.data_ask.factory.generator import generate_factory_spec

    coach = await build_coach_profile(db, source)
    spec = await generate_factory_spec(
        db, source, coach, nl_prompt=payload.nl_prompt, name=payload.name,
    )
    return GenerateSpecOut(spec=SpecOut(**spec), coach=CoachOut(**coach))


@router.post("/data-sources/{sid}/factory/publish", response_model=PublishOut)
async def factory_publish(
    sid: str,
    payload: PublishIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    if source.agent_id:
        agent = await db.get(AgentModel, str(source.agent_id))
        if agent:
            await require_agent_manage(db, agent, user)
    from app.core.data_ask.factory.service import publish_agent

    spec = payload.spec.model_dump()
    agent, version_row, rel = await publish_agent(
        db, source, user, spec, coach=payload.coach, note=payload.note,
    )
    return PublishOut(
        agent_id=agent.id, version=version_row.version, version_id=version_row.id,
        release_id=rel.id, message="智能体已发布",
    )


@router.post("/data-sources/{sid}/factory/regenerate")
async def factory_regenerate(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_manage=True)
    if not source.agent_id:
        raise HTTPException(status_code=400, detail="该数据源尚未绑定智能体，请先完成向导发布")
    from app.core.data_ask.factory_tasks import regenerate_candidate_task

    regenerate_candidate_task.delay(str(sid))
    return {"message": "候选版本生成任务已启动，稍后刷新版本列表查看"}


@router.post("/data-sources/{sid}/factory/trial", response_model=TrialOut)
async def factory_trial(
    sid: str,
    payload: TrialIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user, require_chat=True)
    from app.core.data_ask.service import run_data_ask

    try:
        result = await run_data_ask(
            db, data_source_id=str(sid), question=payload.question.strip(), user=user, execute=True,
        )
    except Exception as exc:
        return TrialOut(success=False, error=str(exc)[:500])
    answer = str(result.get("answer") or "")
    return TrialOut(
        success=True,
        sql=str(result.get("sql") or ""),
        row_count=int(result.get("row_count") or 0),
        analysis_mode=str(result.get("analysis_mode") or "sql"),
        answer_excerpt=answer[:1200],
        chart=result.get("chart"),
        trace_id=result.get("trace_id"),
    )


# ────────────────────── 版本化：列表 / diff / 回滚 ──────────────────────

@router.get("/agents/{aid}/versions", response_model=list[VersionOut])
async def list_agent_versions(
    aid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = await _get_agent(db, aid)
    await require_agent_manage(db, agent, user)
    from app.core.data_ask.factory import versioning

    return [_version_out(r) for r in await versioning.list_versions(db, aid)]


@router.get("/agents/{aid}/versions/{vid}/diff", response_model=DiffOut)
async def diff_agent_version(
    aid: str,
    vid: int,
    base: int | None = Query(None, description="基线版本号；缺省则与现役 production 版本对比"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = await _get_agent(db, aid)
    await require_agent_manage(db, agent, user)
    from app.core.data_ask.factory import versioning

    target = await versioning.find_version(db, aid, vid)
    if not target:
        raise HTTPException(status_code=404, detail="版本不存在")
    if base is not None:
        base_row = next(
            (v for v in await versioning.list_versions(db, aid) if v.version == base), None
        )
    else:
        base_row = await versioning.active_version(db, aid)
    items = versioning.diff_specs(
        base_row.spec if base_row else {}, target.spec,
    )
    return DiffOut(
        agent_id=aid,
        base_version=base_row.version if base_row else None,
        target_version=target.version,
        items=[DiffItemOut(**i) for i in items],
    )


@router.post("/agents/{aid}/versions/{vid}/rollback", response_model=VersionOut)
async def rollback_agent_version(
    aid: str,
    vid: int,
    payload: RollbackIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = await _get_agent(db, aid)
    await require_agent_manage(db, agent, user)
    from app.core.data_ask.factory import versioning

    target = await versioning.find_version(db, aid, vid)
    if not target:
        raise HTTPException(status_code=404, detail="版本不存在")
    new_row = await versioning.rollback(db, agent, target, user=user, note=payload.note)
    return _version_out(new_row)


# ────────────────────── 发布与灰度 ──────────────────────

@router.get("/agents/{aid}/releases", response_model=list[ReleaseOut])
async def list_agent_releases(
    aid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = await _get_agent(db, aid)
    await require_agent_manage(db, agent, user)
    from app.core.data_ask.factory import versioning

    return [_release_out(r) for r in await versioning.list_releases(db, aid)]


@router.post("/agents/{aid}/releases", response_model=ReleaseOut)
async def release_agent_version(
    aid: str,
    payload: ReleaseIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = await _get_agent(db, aid)
    await require_agent_manage(db, agent, user)
    if payload.scope not in ("full", "gray"):
        raise HTTPException(status_code=400, detail="scope 必须是 full/gray")
    from app.core.data_ask.factory import versioning

    target = await versioning.find_version(db, aid, payload.version_id)
    if not target:
        raise HTTPException(status_code=404, detail="版本不存在")
    versioning.apply_spec(agent, dict(target.spec or {}))
    await db.flush()
    await versioning.promote(db, agent, target)
    rel = await versioning.release(
        db, agent, target, scope=payload.scope,
        gray_users=payload.gray_users, user=user, note=payload.note,
    )
    return _release_out(rel)
