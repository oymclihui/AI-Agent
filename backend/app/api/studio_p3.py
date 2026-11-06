"""P3 API：看板订阅、阈值告警、嵌入分享（签名只读链接）。"""
from __future__ import annotations

import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_user
from app.core.dashboard.subscribe_tasks import (
    CHANNELS,
    OPS,
    check_rule,
    compute_next_run,
    evaluate_alert,
    run_subscription,
    sign_embed,
    verify_embed,
)
from app.db.models import (
    AlertEvent,
    AlertRule,
    Dashboard,
    DashboardSnapshot,
    DashboardSubscription,
    DataSource,
    SubscriptionRun,
    User,
)
from app.db.session import get_db

router = APIRouter(prefix="/studio", tags=["DashboardStudioP3"])


def _origin(request: Request) -> str:
    host = request.headers.get("host") or ""
    scheme = request.url.scheme or "http"
    return f"{scheme}://{host}" if host else ""


async def _own_dashboard(db: AsyncSession, did: str, user: User) -> Dashboard:
    row = await db.get(Dashboard, str(did))
    if not row:
        raise HTTPException(status_code=404, detail="看板不存在")
    if str(row.owner_id or "") != str(user.id) and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有创建者可操作")
    return row


async def _own_subscription(db: AsyncSession, sid: str, user: User) -> DashboardSubscription:
    row = await db.get(DashboardSubscription, str(sid))
    if not row:
        raise HTTPException(status_code=404, detail="订阅不存在")
    if str(row.owner_id or "") != str(user.id) and not user.is_admin:
        raise HTTPException(status_code=403, detail="无权操作该订阅")
    return row


def _sub_out(s: DashboardSubscription) -> dict[str, Any]:
    return {
        "id": s.id,
        "dashboard_id": s.dashboard_id,
        "period": s.period,
        "hour": s.hour,
        "minute": s.minute,
        "weekday": s.weekday,
        "channel": s.channel,
        "target": s.target,
        "active": s.active,
        "last_run_at": s.last_run_at,
        "next_run_at": s.next_run_at,
    }


# ── 订阅 CRUD ─────────────────────────────────────────────

@router.get("/dashboards/{did}/subscriptions")
async def list_subscriptions(
    did: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _own_dashboard(db, did, user)
    rows = (
        await db.execute(
            select(DashboardSubscription)
            .where(DashboardSubscription.dashboard_id == did)
            .order_by(DashboardSubscription.created_at.desc())
        )
    ).scalars().all()
    return {"items": [_sub_out(s) for s in rows]}


@router.post("/dashboards/{did}/subscriptions")
async def create_subscription(
    did: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _own_dashboard(db, did, user)
    period = str(payload.get("period") or "daily")
    if period not in ("hourly", "daily", "weekly"):
        raise HTTPException(status_code=422, detail="period 仅支持 hourly/daily/weekly")
    channel = str(payload.get("channel") or "message")
    if channel not in CHANNELS:
        raise HTTPException(status_code=422, detail=f"channel 仅支持 {'/'.join(CHANNELS)}")
    sub = DashboardSubscription(
        dashboard_id=did,
        owner_id=str(user.id),
        period=period,
        hour=max(0, min(int(payload.get("hour", 8)), 23)),
        minute=max(0, min(int(payload.get("minute", 0)), 59)),
        weekday=max(0, min(int(payload.get("weekday", 0)), 6)),
        channel=channel,
        target=str(payload.get("target") or "")[:512],
        link_base=_origin(request),
        active=True,
    )
    sub.next_run_at = compute_next_run(sub)
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return _sub_out(sub)


@router.patch("/subscriptions/{sid}")
async def patch_subscription(
    sid: str,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sub = await _own_subscription(db, sid, user)
    if "active" in payload:
        sub.active = bool(payload["active"])
    if "period" in payload:
        period = str(payload["period"])
        if period not in ("hourly", "daily", "weekly"):
            raise HTTPException(status_code=422, detail="period 仅支持 hourly/daily/weekly")
        sub.period = period
    for key, lo, hi in (("hour", 0, 23), ("minute", 0, 59), ("weekday", 0, 6)):
        if key in payload:
            setattr(sub, key, max(lo, min(int(payload[key]), hi)))
    if "channel" in payload:
        channel = str(payload["channel"])
        if channel not in CHANNELS:
            raise HTTPException(status_code=422, detail=f"channel 仅支持 {'/'.join(CHANNELS)}")
        sub.channel = channel
    if "target" in payload:
        sub.target = str(payload["target"] or "")[:512]
    sub.next_run_at = compute_next_run(sub)
    await db.commit()
    return _sub_out(sub)


@router.delete("/subscriptions/{sid}")
async def delete_subscription(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sub = await _own_subscription(db, sid, user)
    await db.delete(sub)
    await db.commit()
    return {"deleted": True}


@router.post("/subscriptions/{sid}/run")
async def run_subscription_now(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """立即投递一次（验证渠道与快照内容）。"""
    sub = await _own_subscription(db, sid, user)
    try:
        run = await run_subscription(db, sub)
        await db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"run_id": run.id, "status": run.status, "delivered": run.delivered, "error": run.error}


@router.get("/subscriptions/{sid}/runs")
async def list_runs(
    sid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _own_subscription(db, sid, user)
    rows = (
        await db.execute(
            select(SubscriptionRun)
            .where(SubscriptionRun.subscription_id == sid)
            .order_by(SubscriptionRun.created_at.desc())
            .limit(20)
        )
    ).scalars().all()
    delivered = [r for r in rows if r.delivered]
    opened = [r for r in delivered if getattr(r, "opened", False)]
    return {
        "items": [
            {
                "id": r.id,
                "status": r.status,
                "delivered": r.delivered,
                "opened": bool(getattr(r, "opened", False)),
                "opened_at": getattr(r, "opened_at", None),
                "channel": r.channel,
                "summary": r.summary_json or [],
                "error": r.error,
                "created_at": r.created_at,
                "html_url": f"/api/v1/studio/runs/{r.id}/html",
            }
            for r in rows
        ],
        "stats": {
            "total": len(rows),
            "delivered": len(delivered),
            "opened": len(opened),
            "open_rate": round(len(opened) / len(delivered), 4) if delivered else None,
        },
    }


@router.get("/runs/{rid}/html")
async def run_html(
    rid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    run = await db.get(SubscriptionRun, str(rid))
    if not run or not run.html:
        raise HTTPException(status_code=404, detail="快照不存在")
    sub = await db.get(DashboardSubscription, str(run.subscription_id))
    if not sub or (str(sub.owner_id or "") != str(user.id) and not user.is_admin):
        raise HTTPException(status_code=403, detail="无权查看该快照")
    # 打开率追踪（p2-4）：登录态查看同样计入打开
    if not getattr(run, "opened", False):
        try:
            run.opened = True
            run.opened_at = datetime.datetime.now(datetime.timezone.utc)
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
    return HTMLResponse(content=run.html, status_code=200)


# ── 嵌入分享 ──────────────────────────────────────────────

@router.post("/dashboards/{did}/embed-link")
async def create_embed_link(
    did: str,
    request: Request,
    payload: dict[str, Any] = Body(default={}),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await _own_dashboard(db, did, user)
    if row.status != "published":
        raise HTTPException(status_code=422, detail="请先发布看板再生成嵌入链接")
    days = max(1, min(int(payload.get("days", 30)), 365))
    exp = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)).timestamp())
    token = sign_embed({"did": row.id, "rid": None, "exp": exp})
    return {"url": f"{_origin(request)}/api/v1/studio/embed/{token}", "expires_days": days}


@router.get("/embed/{token}")
async def embed_html(token: str, db: AsyncSession = Depends(get_db)):
    """签名只读链接：无需登录，供外部系统 iframe 嵌入。"""
    try:
        payload = verify_embed(token)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    rid = payload.get("rid")
    if rid:
        run = await db.get(SubscriptionRun, str(rid))
        if not run or not run.html or str(run.dashboard_id) != str(payload.get("did")):
            raise HTTPException(status_code=404, detail="快照不存在")
        # 打开率追踪（p2-4）：首次打开回写，幂等
        if not getattr(run, "opened", False):
            try:
                run.opened = True
                run.opened_at = datetime.datetime.now(datetime.timezone.utc)
                await db.commit()
            except Exception:  # noqa: BLE001 - 追踪失败不影响展示
                await db.rollback()
        return HTMLResponse(content=run.html, status_code=200)
    did = str(payload.get("did") or "")
    snap = (
        await db.execute(
            select(DashboardSnapshot)
            .where(DashboardSnapshot.dashboard_id == did)
            .order_by(DashboardSnapshot.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not snap or not snap.html:
        raise HTTPException(status_code=404, detail="看板尚未发布")
    return HTMLResponse(content=snap.html, status_code=200)


# ── 阈值告警 ──────────────────────────────────────────────

def _rule_out(r: AlertRule) -> dict[str, Any]:
    return {
        "id": r.id,
        "data_source_id": r.data_source_id,
        "name": r.name,
        "metric_name": r.metric_name,
        "metric_expr": r.metric_expr,
        "time_field": r.time_field,
        "lookback": r.lookback,
        "op": r.op,
        "threshold": r.threshold,
        "detect": getattr(r, "detect", "threshold") or "threshold",
        "zscore_window": getattr(r, "zscore_window", 28),
        "zscore_sigma": getattr(r, "zscore_sigma", 3.0),
        "interval_minutes": r.interval_minutes,
        "cooldown_hours": r.cooldown_hours,
        "channel": r.channel,
        "target": r.target,
        "active": r.active,
        "last_checked_at": r.last_checked_at,
        "last_value": r.last_value,
        "last_triggered_at": r.last_triggered_at,
    }


async def _own_rule(db: AsyncSession, rid: str, user: User) -> AlertRule:
    row = await db.get(AlertRule, str(rid))
    if not row:
        raise HTTPException(status_code=404, detail="告警规则不存在")
    if str(row.owner_id or "") != str(user.id) and not user.is_admin:
        raise HTTPException(status_code=403, detail="无权操作该规则")
    return row


def _fill_rule(rule: AlertRule, payload: dict[str, Any], partial: bool = False) -> None:
    if "name" in payload or not partial:
        rule.name = str(payload.get("name") or "").strip()[:120] or rule.name or "阈值告警"
    if "metric_name" in payload or not partial:
        rule.metric_name = str(payload.get("metric_name") or "").strip()[:64] or "指标"
    if "metric_expr" in payload or not partial:
        rule.metric_expr = str(payload.get("metric_expr") or "").strip()[:255]
    if "time_field" in payload or not partial:
        rule.time_field = str(payload.get("time_field") or "RQ").strip()[:64]
    if "lookback" in payload or not partial:
        lookback = str(payload.get("lookback") or "today")
        if lookback not in ("today", "yesterday", "this_month", "last_7d"):
            raise HTTPException(status_code=422, detail="lookback 仅支持 today/yesterday/this_month/last_7d")
        rule.lookback = lookback
    if "op" in payload or not partial:
        op = str(payload.get("op") or "<")
        if op not in OPS:
            raise HTTPException(status_code=422, detail=f"op 仅支持 {' '.join(OPS)}")
        rule.op = op
    if "threshold" in payload or not partial:
        rule.threshold = float(payload.get("threshold", 0) or 0)
    if "detect" in payload or not partial:
        detect = str(payload.get("detect") or "threshold")
        if detect not in ("threshold", "zscore"):
            raise HTTPException(status_code=422, detail="detect 仅支持 threshold/zscore")
        rule.detect = detect
    if "zscore_window" in payload:
        rule.zscore_window = max(7, min(int(payload["zscore_window"] or 28), 180))
    if "zscore_sigma" in payload:
        rule.zscore_sigma = max(0.5, min(float(payload["zscore_sigma"] or 3.0), 10.0))
    if "interval_minutes" in payload:
        rule.interval_minutes = max(5, min(int(payload["interval_minutes"]), 24 * 60))
    if "cooldown_hours" in payload:
        rule.cooldown_hours = max(1, min(int(payload["cooldown_hours"]), 24 * 30))
    if "channel" in payload or not partial:
        channel = str(payload.get("channel") or "message")
        if channel not in CHANNELS:
            raise HTTPException(status_code=422, detail=f"channel 仅支持 {'/'.join(CHANNELS)}")
        rule.channel = channel
    if "target" in payload or not partial:
        rule.target = str(payload.get("target") or "")[:512]


@router.get("/alerts")
async def list_alerts(
    data_source_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        await db.execute(
            select(AlertRule)
            .where(AlertRule.data_source_id == data_source_id, AlertRule.owner_id == str(user.id))
            .order_by(AlertRule.created_at.desc())
            .limit(100)
        )
    ).scalars().all()
    return {"items": [_rule_out(r) for r in rows]}


@router.post("/alerts")
async def create_alert(
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sid = str(payload.get("data_source_id") or "").strip()
    source = await db.get(DataSource, sid)
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    from app.core.data_ask.govern.access import assert_data_source_access

    await assert_data_source_access(db, source, user, require_chat=True)
    if not str(payload.get("metric_expr") or "").strip():
        raise HTTPException(status_code=422, detail="metric_expr 必填")
    rule = AlertRule(data_source_id=sid, owner_id=str(user.id))
    _fill_rule(rule, payload)
    rule.active = bool(payload.get("active", True))
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _rule_out(rule)


@router.patch("/alerts/{rid}")
async def patch_alert(
    rid: str,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rule = await _own_rule(db, rid, user)
    _fill_rule(rule, payload, partial=True)
    if "active" in payload:
        rule.active = bool(payload["active"])
    await db.commit()
    return _rule_out(rule)


@router.delete("/alerts/{rid}")
async def delete_alert(
    rid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rule = await _own_rule(db, rid, user)
    await db.execute(delete(AlertEvent).where(AlertEvent.rule_id == rule.id))
    await db.delete(rule)
    await db.commit()
    return {"deleted": True}


@router.post("/alerts/{rid}/check")
async def check_alert_now(
    rid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """立即评估一次：返回当前值与是否越界；越界会记录事件并按冷却通知。"""
    rule = await _own_rule(db, rid, user)
    source = await db.get(DataSource, str(rule.data_source_id))
    value, violated, detail = await evaluate_alert(db, rule, source, user)
    rule.last_checked_at = datetime.datetime.now(datetime.timezone.utc)
    rule.last_value = value
    event_id = None
    notified = False
    if violated:
        event = await check_rule(db, rule)
        if event:
            await db.flush()
            event_id = event.id
            notified = event.notified
    await db.commit()
    return {"value": value, "violated": violated, "detail": detail, "event_id": event_id, "notified": notified}


@router.get("/alerts/{rid}/events")
async def list_alert_events(
    rid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _own_rule(db, rid, user)
    rows = (
        await db.execute(
            select(AlertEvent)
            .where(AlertEvent.rule_id == rid)
            .order_by(AlertEvent.created_at.desc())
            .limit(20)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": e.id,
                "value": e.value,
                "threshold": e.threshold,
                "message": e.message,
                "notified": e.notified,
                "created_at": e.created_at,
            }
            for e in rows
        ]
    }
