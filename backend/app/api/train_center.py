"""训练中心 P1 API：统一训练工单 —— 五步向导（选对象 → 喂料 → 训练 → 验证 → 上线）。

- POST /train/jobs              创建训练工单（distill/eval/full，Celery 异步）
- GET  /train/jobs              工单列表（按训练对象过滤）
- GET  /train/jobs/{job_id}     工单详情（阶段 / 进度 / 各阶段产物）
- POST /train/jobs/{job_id}/retry  失败按阶段重试（保留已完成产物）
- GET  /train/events            SSE 实时快照（阶段进度、评测分数、晋升结果）
写操作需数据源 manage 权限（agent 目标需智能体 manage 权限）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_user
from app.core.data_ask.govern.access import assert_data_source_access
from app.db.models import Agent as AgentModel
from app.db.models import DataSource, PromptCandidate, TrainJob, TrainRlExport, TrainTrajectory, User
from app.db.session import get_db
from app.schemas.train_center import (
    PromptCandidateOut,
    RlExportIn,
    RlExportOut,
    TrainJobCreateIn,
    TrainJobOut,
    TrainJobRetryIn,
    TrainStageOut,
    TrainTrajectoryOut,
)

logger = logging.getLogger("train_center")

router = APIRouter(tags=["TrainCenter"])

# 五步向导 → 阶段序列（P1 开放 distill/eval/full，P2 新增 prompt 提示词优化）
STAGE_SEQUENCE: dict[str, list[tuple[str, str]]] = {
    "distill": [("collect", "采集训练信号"), ("distill", "知识蒸馏")],
    "eval": [
        ("collect", "采集训练信号"),
        ("build_eval", "构建考题"),
        ("eval", "回归评测"),
        ("promote", "上线判定"),
    ],
    "full": [
        ("collect", "采集训练信号"),
        ("distill", "知识蒸馏"),
        ("build_eval", "构建考题"),
        ("candidate", "生成候选配置"),
        ("eval", "回归评测"),
        ("promote", "上线判定"),
    ],
    "prompt": [
        ("collect", "采集失败信号"),
        ("prompt", "反思改写提示词"),
        ("build_eval", "构建考题"),
        ("eval", "回归评测"),
        ("promote", "上线判定"),
    ],
    "trajectory": [
        ("collect", "采集轨迹信号"),
        ("normalize", "轨迹标准化"),
        ("metrics", "多轮指标"),
        ("replay", "沙箱回放对比"),
        ("traj_promote", "配置上线判定"),
    ],
}


def _job_out(row: TrainJob) -> TrainJobOut:
    stages = [TrainStageOut(**s) for s in (row.stages or []) if isinstance(s, dict)]
    return TrainJobOut(
        id=row.id, target_type=row.target_type, target_id=row.target_id,
        kind=row.kind, status=row.status, stage=row.stage,
        progress=int(row.progress or 0), stages=stages,
        detail=row.detail if isinstance(row.detail, dict) else {},
        error=row.error, note=row.note, created_by=row.created_by,
        created_at=row.created_at, updated_at=row.updated_at,
    )


async def _resolve_target(
    db: AsyncSession, target_type: str, target_id: str, user: User,
    *, require_manage: bool = True,
) -> tuple[DataSource, AgentModel | None]:
    """解析训练对象：ds 直接取数据源；agent 取其绑定的数据源并校验智能体权限。"""
    if target_type == "agent":
        agent = await db.get(AgentModel, str(target_id))
        if not agent:
            raise HTTPException(status_code=404, detail="智能体不存在")
        from app.core.auth.agent_access import require_agent_manage

        await require_agent_manage(db, agent, user)
        source = (
            await db.execute(select(DataSource).where(DataSource.agent_id == str(agent.id)).limit(1))
        ).scalar_one_or_none()
        if source is None:
            ds_id = str((agent.metadata_ or {}).get("data_source_id") or "")
            source = await db.get(DataSource, ds_id) if ds_id else None
        if source is None:
            raise HTTPException(status_code=400, detail="该智能体未绑定数据源，无法训练")
        return source, agent

    source = await db.get(DataSource, str(target_id))
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    await assert_data_source_access(db, source, user, require_manage=require_manage)
    agent = await db.get(AgentModel, str(source.agent_id)) if source.agent_id else None
    return source, agent


async def _assert_job_access(db: AsyncSession, job: TrainJob, user: User) -> None:
    if job.target_type == "agent":
        agent = await db.get(AgentModel, str(job.target_id))
        if not agent:
            raise HTTPException(status_code=404, detail="智能体不存在")
        from app.core.auth.agent_access import require_agent_manage

        await require_agent_manage(db, agent, user)
        return
    source = await db.get(DataSource, str(job.target_id))
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    await assert_data_source_access(db, source, user)


def _initial_stages(kind: str) -> list[dict]:
    return [
        {
            "key": key, "label": label, "status": "pending", "progress": 0,
            "message": None, "detail": None, "started_at": None, "finished_at": None,
        }
        for key, label in STAGE_SEQUENCE[kind]
    ]


# ────────────────────── 工单创建 / 列表 / 详情 ──────────────────────

@router.post("/train/jobs", response_model=TrainJobOut)
async def create_train_job(
    payload: TrainJobCreateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source, _agent = await _resolve_target(db, payload.target_type, payload.target_id, user)

    # P2 prompt kind 必须绑定智能体（要改写 role/goal/backstory）
    if payload.kind == "prompt":
        agent = await db.get(AgentModel, str(source.agent_id)) if source.agent_id else None
        if agent is None:
            raise HTTPException(status_code=400, detail="提示词优化需要智能体，请先在「智能体工厂」发布再训练")

    job = TrainJob(
        target_type=payload.target_type,
        target_id=str(source.id) if payload.target_type == "ds" else payload.target_id,
        kind=payload.kind,
        status="queued",
        stage="queued",
        progress=0,
        stages=_initial_stages(payload.kind),
        detail={},
        note=(payload.note or "")[:500] or None,
        created_by=str(user.id),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    try:
        from app.worker import celery_app

        celery_app.send_task("train_center.run_job", args=[str(job.id)])
    except Exception as exc:
        logger.exception("train_job_dispatch_failed job=%s", job.id)
        job.status = "failed"
        job.error = f"任务投递失败：{str(exc)[:800]}"
        await db.commit()
        await db.refresh(job)
    return _job_out(job)


@router.get("/train/jobs", response_model=list[TrainJobOut])
async def list_train_jobs(
    target_id: str = Query(...),
    target_type: str = Query(default="ds"),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _resolve_target(db, target_type, target_id, user, require_manage=False)
    rows = (
        await db.execute(
            select(TrainJob)
            .where(TrainJob.target_type == target_type, TrainJob.target_id == str(target_id))
            .order_by(TrainJob.created_at.desc(), TrainJob.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_job_out(r) for r in rows]


@router.get("/train/jobs/{job_id}", response_model=TrainJobOut)
async def get_train_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = await db.get(TrainJob, str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="训练工单不存在")
    await _assert_job_access(db, job, user)
    return _job_out(job)


@router.post("/train/jobs/{job_id}/retry", response_model=TrainJobOut)
async def retry_train_job(
    job_id: str,
    payload: TrainJobRetryIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = await db.get(TrainJob, str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="训练工单不存在")
    await _assert_job_access(db, job, user)
    if job.status in ("queued", "running"):
        raise HTTPException(status_code=400, detail="工单正在执行中，无法重试")
    stages = list(job.stages or [])
    keys = [s.get("key") for s in stages]
    if payload.from_stage not in keys:
        raise HTTPException(status_code=400, detail="from_stage 不属于该工单的阶段序列")
    idx = keys.index(payload.from_stage)
    for st in stages[idx:]:
        st.update({"status": "pending", "progress": 0, "message": None, "detail": None,
                   "started_at": None, "finished_at": None})
    job.stages = stages
    job.status = "queued"
    job.stage = payload.from_stage
    job.error = None
    await db.commit()
    await db.refresh(job)

    try:
        from app.worker import celery_app

        celery_app.send_task("train_center.run_job", args=[str(job.id), payload.from_stage])
    except Exception as exc:
        job.status = "failed"
        job.error = f"任务投递失败：{str(exc)[:800]}"
        await db.commit()
        await db.refresh(job)
    return _job_out(job)


# ────────────────────── P2: PromptCandidate 列表 ──────────────────────


def _pc_out(row: PromptCandidate) -> PromptCandidateOut:
    return PromptCandidateOut(
        id=row.id,
        agent_id=row.agent_id,
        data_source_id=row.data_source_id,
        base_version_id=row.base_version_id,
        field=row.field,
        before=row.before,
        after=row.after,
        reason=row.reason,
        failure_clusters=list(row.failure_clusters or []),
        score_delta=row.score_delta,
        status=row.status,
        eval_run_id=row.eval_run_id,
        train_job_id=row.train_job_id,
        model=row.model,
        created_by=row.created_by,
        created_at=row.created_at,
    )


@router.get("/train/prompt-candidates", response_model=list[PromptCandidateOut])
async def list_prompt_candidates(
    agent_id: str = Query(...),
    train_job_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = await db.get(AgentModel, str(agent_id))
    if not agent:
        raise HTTPException(status_code=404, detail="智能体不存在")
    from app.core.auth.agent_access import require_agent_manage

    await require_agent_manage(db, agent, user)
    stmt = select(PromptCandidate).where(PromptCandidate.agent_id == str(agent.id))
    if train_job_id:
        stmt = stmt.where(PromptCandidate.train_job_id == str(train_job_id))
    rows = (
        await db.execute(
            stmt.order_by(PromptCandidate.created_at.desc(), PromptCandidate.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_pc_out(r) for r in rows]


# ────────────────────── P3: 标准化训练轨迹 ──────────────────────


def _traj_out(row: TrainTrajectory) -> TrainTrajectoryOut:
    return TrainTrajectoryOut(
        id=row.id,
        data_source_id=row.data_source_id,
        agent_id=row.agent_id,
        trace_id=row.trace_id,
        run_id=row.run_id,
        question=row.question,
        standalone_question=row.standalone_question,
        mode=row.mode,
        plan=row.plan if isinstance(row.plan, dict) else None,
        tool_calls=list(row.tool_calls or []),
        observation=row.observation if isinstance(row.observation, dict) else None,
        result=row.result if isinstance(row.result, dict) else None,
        reward=float(row.reward or 0.0),
        success=bool(row.success),
        n_candidates=int(row.n_candidates or 0),
        n_invalid_calls=int(row.n_invalid_calls or 0),
        n_rounds=int(row.n_rounds or 1),
        source=row.source or "tree",
        train_job_id=row.train_job_id,
        created_at=row.created_at,
    )


@router.get("/train/trajectories", response_model=list[TrainTrajectoryOut])
async def list_train_trajectories(
    data_source_id: str = Query(...),
    only_failed: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """P3：查看已标准化的训练轨迹（失败优先用于回放/复盘）。"""
    source = await db.get(DataSource, str(data_source_id))
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    await assert_data_source_access(db, source, user)
    stmt = select(TrainTrajectory).where(TrainTrajectory.data_source_id == str(source.id))
    if only_failed:
        stmt = stmt.where(TrainTrajectory.success.is_(False))
    rows = (
        await db.execute(
            stmt.order_by(TrainTrajectory.created_at.desc(), TrainTrajectory.id.desc()).limit(limit)
        )
    ).scalars().all()
    return [_traj_out(r) for r in rows]


# ────────────────────── P4: RL 训练数据导出 ──────────────────────

_RL_EXPORT_DIR = os.environ.get("RL_EXPORT_DIR") or "/app/uploads/rl_exports"
_DEFAULT_REWARD_RULE = "success=+1.0;invalid=-0.5;clarify=+0.2"


def _parse_reward_rule(rule: str) -> dict[str, float]:
    """解析 'success=+1.0;invalid=-0.5;clarify=+0.2' 为 dict。"""
    out = {"success": 1.0, "invalid": -0.5, "clarify": 0.2}
    for part in (rule or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, _, v = part.partition("=")
        k = k.strip().lower()
        try:
            out[k] = float(v.strip())
        except (TypeError, ValueError):
            continue
    return out


def _reward_by_rule(traj: TrainTrajectory, rule: dict[str, float]) -> float:
    """按规则重算奖励：成功 + success；每次无效调用 + invalid；多轮澄清后收敛 + clarify。"""
    r = 0.0
    if traj.success:
        r += float(rule.get("success", 1.0))
        if int(traj.n_rounds or 1) > 1:  # 澄清后收敛
            r += float(rule.get("clarify", 0.2))
    r += float(rule.get("invalid", -0.5)) * int(traj.n_invalid_calls or 0)
    return round(r, 4)


def _rl_export_out(row: TrainRlExport) -> RlExportOut:
    return RlExportOut(
        id=row.id,
        data_source_id=row.data_source_id,
        agent_id=row.agent_id,
        range=row.range or "all",
        format=row.format or "jsonl",
        reward_rule=row.reward_rule or "",
        row_count=int(row.row_count or 0),
        uri=row.uri,
        train_job_id=row.train_job_id,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def _trajectory_to_rl_row(traj: TrainTrajectory, reward: float) -> dict:
    return {
        "run_id": traj.run_id,
        "trace_id": traj.trace_id,
        "question": traj.question,
        "standalone_question": traj.standalone_question,
        "mode": traj.mode,
        "plan": traj.plan,
        "tool_calls": list(traj.tool_calls or []),
        "observation": traj.observation,
        "result": traj.result,
        "reward": reward,
        "success": bool(traj.success),
        "n_candidates": int(traj.n_candidates or 0),
        "n_invalid_calls": int(traj.n_invalid_calls or 0),
        "n_rounds": int(traj.n_rounds or 1),
        "data_source_id": traj.data_source_id,
        "agent_id": traj.agent_id,
        "source": traj.source or "tree",
    }


@router.post("/train/export/rl", response_model=RlExportOut)
async def export_rl_dataset(
    payload: RlExportIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """P4：把标准化轨迹按规则奖励打成 JSONL，供 ART/verl 等外部 RL 训练使用。"""
    source = await db.get(DataSource, str(payload.data_source_id))
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    await assert_data_source_access(db, source, user)

    rng = (payload.range or "all").strip().lower()
    stmt = select(TrainTrajectory).where(TrainTrajectory.data_source_id == str(source.id))
    limit: int | None = None
    if rng == "failed":
        stmt = stmt.where(TrainTrajectory.success.is_(False))
    elif rng == "success":
        stmt = stmt.where(TrainTrajectory.success.is_(True))
    elif rng.startswith("last:"):
        try:
            limit = max(1, min(int(rng.split(":", 1)[1]), 10000))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="range 格式非法，应为 all/failed/success/last:N")
    elif rng != "all":
        raise HTTPException(status_code=400, detail="range 格式非法，应为 all/failed/success/last:N")
    stmt = stmt.order_by(TrainTrajectory.created_at.asc(), TrainTrajectory.id.asc())
    if limit is not None:
        # 取最近 N 条：先按 desc 取再反转回 asc
        recent = (
            await db.execute(
                select(TrainTrajectory)
                .where(TrainTrajectory.data_source_id == str(source.id))
                .order_by(TrainTrajectory.created_at.desc(), TrainTrajectory.id.desc())
                .limit(limit)
            )
        ).scalars().all()
        rows = list(reversed(recent))
    else:
        rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        raise HTTPException(status_code=400, detail="该数据源暂无标准化轨迹，请先运行轨迹训练")

    rule = _parse_reward_rule(payload.reward_rule or _DEFAULT_REWARD_RULE)

    rec = TrainRlExport(
        data_source_id=str(source.id),
        agent_id=str(source.agent_id) if source.agent_id else None,
        range=rng,
        format="jsonl",
        reward_rule=payload.reward_rule or _DEFAULT_REWARD_RULE,
        row_count=0,
        created_by=str(user.id),
    )
    db.add(rec)
    await db.flush()  # 拿 id

    os.makedirs(_RL_EXPORT_DIR, exist_ok=True)
    filename = f"{rec.id}.jsonl"
    path = os.path.join(_RL_EXPORT_DIR, filename)
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for traj in rows:
            reward = _reward_by_rule(traj, rule)
            fh.write(json.dumps(_trajectory_to_rl_row(traj, reward), ensure_ascii=False) + "\n")
            n += 1
    rec.row_count = n
    rec.uri = path
    await db.commit()
    await db.refresh(rec)
    return _rl_export_out(rec)


@router.get("/train/exports", response_model=list[RlExportOut])
async def list_rl_exports(
    data_source_id: str = Query(...),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await db.get(DataSource, str(data_source_id))
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    await assert_data_source_access(db, source, user, require_manage=False)
    rows = (
        await db.execute(
            select(TrainRlExport)
            .where(TrainRlExport.data_source_id == str(source.id))
            .order_by(TrainRlExport.created_at.desc(), TrainRlExport.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_rl_export_out(r) for r in rows]


@router.get("/train/exports/{export_id}/download")
async def download_rl_export(
    export_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rec = await db.get(TrainRlExport, str(export_id))
    if not rec:
        raise HTTPException(status_code=404, detail="导出记录不存在")
    source = await db.get(DataSource, str(rec.data_source_id))
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    await assert_data_source_access(db, source, user, require_manage=False)
    if not rec.uri or not os.path.exists(rec.uri):
        raise HTTPException(status_code=404, detail="导出文件已被清理，请重新导出")
    return FileResponse(
        rec.uri,
        media_type="application/x-ndjson",
        filename=f"rl_export_{rec.id}.jsonl",
    )


# ────────────────────── SSE 实时快照 ──────────────────────

@router.get("/train/events")
async def train_events(
    request: Request,
    job_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """单工单训练快照流：阶段进度 / 评测分数 / 晋升结果，1.5s 一帧。"""
    job = await db.get(TrainJob, str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="训练工单不存在")
    await _assert_job_access(db, job, user)

    from fastapi.responses import StreamingResponse

    async def _gen():
        last_sig: str | None = None
        tick = 0
        while True:
            try:
                if await request.is_disconnected():
                    break
                db.expire_all()
                row = await db.get(TrainJob, str(job_id))
                if not row:
                    break
                snap = {
                    "event": "snapshot",
                    "job": {
                        "id": row.id, "target_type": row.target_type,
                        "target_id": row.target_id, "kind": row.kind,
                        "status": row.status, "stage": row.stage,
                        "progress": int(row.progress or 0),
                        "stages": list(row.stages or []),
                        "detail": row.detail if isinstance(row.detail, dict) else {},
                        "error": row.error,
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    },
                }
                sig = json.dumps(snap, sort_keys=True, ensure_ascii=False, default=str)
                if sig != last_sig:
                    last_sig = sig
                    yield f"data: {json.dumps(snap, ensure_ascii=False, default=str)}\n\n"
                elif tick % 10 == 0:
                    yield ": ping\n\n"
                tick += 1
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("train_events_snapshot_failed job=%s", job_id)
                yield ": err\n\n"
            await asyncio.sleep(1.5)

    return StreamingResponse(
        _gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
