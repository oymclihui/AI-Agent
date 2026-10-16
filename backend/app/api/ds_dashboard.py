"""经营分析看板技能 API（P0）。

- POST /data-sources/{sid}/dashboards/generate   触发生成（Celery 异步，七阶段）
- GET  /dashboards/tasks/{tid}                   任务状态轮询（含阶段事件）
- GET  /data-ask/dashboard/events                看板生成 SSE（2s 快照流）
- GET  /dashboards/{id}/view                     自包含 HTML 看板（鉴权，新窗口打开）
写操作需数据源访问权限；view 复用同一套 assert_data_source_access。
"""
from __future__ import annotations

import asyncio
import json as _json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.core.auth.deps import get_current_user
from app.core.data_ask.govern.access import assert_data_source_access
from app.db.models import DashboardArtifact, DashboardEvent, DataSource, User
from app.db.session import get_db
from app.schemas.ds_dashboard import (
    DashboardEventOut,
    DashboardGenerateIn,
    DashboardGenerateOut,
    DashboardTaskOut,
)

router = APIRouter(tags=["DsDashboard"])
logger = logging.getLogger("ds_dashboard")


async def _get_source(db: AsyncSession, sid: str) -> DataSource:
    source = await db.get(DataSource, sid)
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return source


async def _get_artifact_with_access(
    db: AsyncSession, tid: str, user: User, *, with_html: bool = False
) -> tuple[DashboardArtifact, DataSource]:
    stmt = select(DashboardArtifact).where(DashboardArtifact.id == str(tid))
    if not with_html:
        stmt = stmt.options(defer(DashboardArtifact.html), defer(DashboardArtifact.snapshot))
    art = (await db.execute(stmt)).scalar_one_or_none()
    if not art:
        raise HTTPException(status_code=404, detail="看板任务不存在")
    source = await _get_source(db, str(art.data_source_id))
    await assert_data_source_access(db, source, user)
    return art, source


@router.post("/data-sources/{sid}/dashboards/generate", response_model=DashboardGenerateOut)
async def generate_dashboard(
    sid: str,
    payload: DashboardGenerateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """触发零售经营看板生成（异步）。可选 conversation_id：完成后向该会话写入 dashboard_card 消息。"""
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)

    from app.core.dashboard.template import TEMPLATE_ID

    if payload.template != TEMPLATE_ID:
        raise HTTPException(status_code=400, detail=f"P0 仅支持模板 {TEMPLATE_ID}")

    if payload.conversation_id:
        from app.db.models import Conversation

        conv = await db.get(Conversation, str(payload.conversation_id))
        if not conv or not conv.is_active:
            raise HTTPException(status_code=404, detail="会话不存在或已关闭")
        if str(conv.owner_id) != str(user.id) and not user.is_admin:
            raise HTTPException(status_code=403, detail="无权向该会话写入")

    title = (payload.title or "").strip()[:120] or f"{source.name} · 零售经营分析看板"
    art = DashboardArtifact(
        data_source_id=str(source.id),
        user_id=str(user.id),
        conversation_id=str(payload.conversation_id) if payload.conversation_id else None,
        template=TEMPLATE_ID,
        title=title,
        status="queued",
        stage="intent",
        progress=0,
    )
    db.add(art)
    await db.flush()
    try:
        from app.core.dashboard.tasks import dashboard_generate_task

        dashboard_generate_task.delay(str(art.id))
    except Exception as exc:
        art.status = "failed"
        art.error = str(exc)[:1000]
        await db.flush()
        raise HTTPException(status_code=500, detail=f"任务入队失败：{str(exc)[:300]}")
    return DashboardGenerateOut(task_id=str(art.id), status=art.status, message="看板生成任务已启动")


@router.get("/dashboards/tasks/{tid}", response_model=DashboardTaskOut)
async def dashboard_task(
    tid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    art, _ = await _get_artifact_with_access(db, tid, user)
    ev_rows = (
        await db.execute(
            select(DashboardEvent)
            .where(DashboardEvent.dashboard_id == str(art.id))
            .order_by(DashboardEvent.id.asc())
            .limit(60)
        )
    ).scalars().all()
    return DashboardTaskOut(
        id=str(art.id),
        data_source_id=str(art.data_source_id),
        template=str(art.template),
        title=art.title or "",
        status=art.status,
        stage=art.stage,
        progress=art.progress or 0,
        period_start=art.period_start,
        period_end=art.period_end,
        kpis=list(art.kpis or []),
        anchor_status=art.anchor_status,
        anchor_detail=dict(art.anchor_detail or {}),
        verify_report=dict(art.verify_report or {}),
        error=art.error,
        message_id=art.message_id,
        view_url=f"/api/v1/dashboards/{art.id}/view",
        created_at=art.created_at,
        events=[
            DashboardEventOut(
                id=int(e.id), stage=e.stage, status=e.status,
                detail=dict(e.detail or {}), created_at=e.created_at,
            )
            for e in ev_rows
        ],
    )


@router.get("/dashboards/{tid}/view")
async def view_dashboard(
    tid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """打开看板 HTML（鉴权；未完成/失败显式返回状态页）。"""
    art, _ = await _get_artifact_with_access(db, tid, user, with_html=True)
    if art.status != "done" or not art.html:
        detail = art.error or f"看板尚未生成完成（status={art.status}, stage={art.stage}）"
        raise HTTPException(status_code=409, detail=detail)
    return HTMLResponse(content=art.html, status_code=200)


@router.get("/data-ask/dashboard/events")
async def dashboard_events(
    request: Request,
    sid: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """看板生成 SSE：最近任务 + 阶段事件，2s 快照流（与 train/events 同模式）。"""
    source = await _get_source(db, sid)
    await assert_data_source_access(db, source, user)
    ds = str(source.id)

    async def _gen():
        last_sig: str | None = None
        tick = 0
        while True:
            try:
                if request is not None and await request.is_disconnected():
                    break
                db.expire_all()
                arts = (
                    await db.execute(
                        select(DashboardArtifact)
                        .where(DashboardArtifact.data_source_id == ds)
                        .options(defer(DashboardArtifact.html), defer(DashboardArtifact.snapshot))
                        .order_by(DashboardArtifact.created_at.desc())
                        .limit(5)
                    )
                ).scalars().all()
                art_ids = [str(a.id) for a in arts]
                events: list[DashboardEvent] = []
                if art_ids:
                    events = list((
                        await db.execute(
                            select(DashboardEvent)
                            .where(DashboardEvent.dashboard_id.in_(art_ids))
                            .order_by(DashboardEvent.id.desc())
                            .limit(40)
                        )
                    ).scalars().all())
                snap = {
                    "event": "snapshot",
                    "data_source_id": ds,
                    "dashboards": [
                        {
                            "id": a.id, "title": a.title, "status": a.status,
                            "stage": a.stage, "progress": a.progress or 0,
                            "period_start": a.period_start, "period_end": a.period_end,
                            "kpis": a.kpis or [], "anchor_status": a.anchor_status,
                            "error": a.error, "message_id": a.message_id,
                            "view_url": f"/api/v1/dashboards/{a.id}/view",
                            "created_at": a.created_at.isoformat() if a.created_at else None,
                        }
                        for a in arts
                    ],
                    "events": [
                        {
                            "id": e.id, "dashboard_id": e.dashboard_id,
                            "stage": e.stage, "status": e.status, "detail": e.detail,
                            "created_at": e.created_at.isoformat() if e.created_at else None,
                        }
                        for e in events
                    ],
                }
                sig = _json.dumps(snap, sort_keys=True, ensure_ascii=False, default=str)
                if sig != last_sig:
                    last_sig = sig
                    yield f"data: {_json.dumps(snap, ensure_ascii=False, default=str)}\n\n"
                elif tick % 10 == 0:
                    yield ": ping\n\n"
                tick += 1
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("dashboard_events_snapshot_failed")
                yield ": err\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        _gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
