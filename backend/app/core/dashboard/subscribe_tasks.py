"""P3 订阅推送与阈值告警：周期任务、渠道投递、嵌入签名。

- dispatch_subscriptions：每分钟由 beat 触发，投递到期的看板订阅；
- check_alerts：每分钟由 beat 触发，评估到期的告警规则；
- 嵌入分享：HMAC 签名的只读链接（sign_embed / verify_embed）。
所有数字仍由 execute_spec 实时计算，任务只负责编排与投递。
"""
from __future__ import annotations

import asyncio
import base64
import datetime
import hashlib
import hmac
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.tasks_runtime import run_in_persistent_loop
from app.db.models import (
    AlertEvent,
    AlertRule,
    Conversation,
    Dashboard,
    DashboardSubscription,
    DashboardWidget,
    DataSource,
    Message,
    MessageRole,
    SubscriptionRun,
    User,
)
from app.worker import celery_app

logger = logging.getLogger("studio_p3")

_sub_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
SubSessionLocal = async_sessionmaker(_sub_engine, expire_on_commit=False)

CN_TZ = datetime.timezone(datetime.timedelta(hours=8))

CHANNELS = ("message", "webhook", "feishu", "email")
OPS = (">", ">=", "<", "<=", "==", "!=")


# ── 嵌入签名 ──────────────────────────────────────────────

def sign_embed(payload: dict[str, Any]) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{raw}.{sig}"


def verify_embed(token: str) -> dict[str, Any]:
    try:
        raw, sig = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("签名格式错误") from exc
    expect = hmac.new(settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(expect, sig):
        raise ValueError("签名无效")
    pad = "=" * (-len(raw) % 4)
    payload = json.loads(base64.urlsafe_b64decode(raw + pad).decode())
    exp = int(payload.get("exp") or 0)
    if exp < int(datetime.datetime.now(datetime.timezone.utc).timestamp()):
        raise ValueError("链接已过期")
    return payload


# ── 订阅周期计算（按北京时间） ──────────────────────────────

def compute_next_run(sub: DashboardSubscription, now: datetime.datetime | None = None) -> datetime.datetime:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    local = now.astimezone(CN_TZ)
    hour = max(0, min(int(sub.hour or 8), 23))
    minute = max(0, min(int(sub.minute or 0), 59))
    if sub.period == "hourly":
        cand = local.replace(minute=minute, second=0, microsecond=0)
        if cand <= local:
            cand += datetime.timedelta(hours=1)
    elif sub.period == "weekly":
        weekday = max(0, min(int(sub.weekday or 0), 6))
        cand = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days = (weekday - cand.weekday()) % 7
        cand += datetime.timedelta(days=days)
        if cand <= local:
            cand += datetime.timedelta(days=7)
    else:  # daily
        cand = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if cand <= local:
            cand += datetime.timedelta(days=1)
    return cand.astimezone(datetime.timezone.utc)


# ── 渠道投递 ──────────────────────────────────────────────

async def _push_conversation(db: AsyncSession, owner_id: str, target: str) -> Conversation:
    conv = None
    if target:
        conv = await db.get(Conversation, target)
        if conv and str(conv.owner_id or "") != str(owner_id):
            conv = None
    if not conv:
        conv = (
            await db.execute(
                select(Conversation)
                .where(Conversation.owner_id == str(owner_id), Conversation.title == "看板订阅推送")
                .order_by(Conversation.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if not conv:
        conv = Conversation(owner_id=str(owner_id), title="看板订阅推送", is_active=True)
        db.add(conv)
        await db.flush()
    return conv


async def deliver(
    db: AsyncSession,
    *,
    channel: str,
    target: str,
    owner: User,
    title: str,
    text: str,
) -> tuple[bool, str | None]:
    """按渠道投递文本；返回 (是否成功, 错误信息)。"""
    try:
        if channel == "webhook":
            import httpx

            if "oapi.dingtalk.com" in target:
                body: dict[str, Any] = {"msgtype": "text", "text": {"content": f"{title}\n{text}"}}
            else:
                body = {"title": title, "text": text}
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(target, json=body)
            if resp.status_code >= 400:
                return False, f"webhook 返回 {resp.status_code}"
            return True, None
        if channel == "feishu":
            from app.integrations.feishu import send_feishu_text

            await send_feishu_text(target, f"{title}\n{text}")
            return True, None
        if channel == "email":
            from app.core.email.smtp_client import send_email

            await asyncio.to_thread(
                send_email,
                to=target,
                subject=title,
                html_body=f"<p>{text.replace(chr(10), '<br>')}</p>",
                text_body=text,
            )
            return True, None
        # 默认：站内会话消息
        conv = await _push_conversation(db, str(owner.id), target)
        db.add(Message(
            conversation_id=conv.id,
            role=MessageRole.assistant,
            content=f"**{title}**\n\n{text}",
            metadata_={"type": "studio_push"},
        ))
        return True, None
    except Exception as exc:  # noqa: BLE001 - 投递失败需记录而不是中断任务
        logger.warning("deliver failed channel=%s err=%s", channel, exc)
        return False, str(exc)[:500]


# ── 订阅执行 ──────────────────────────────────────────────

async def run_subscription(db: AsyncSession, sub: DashboardSubscription) -> SubscriptionRun:
    """生成当次快照并投递；供周期任务与「立即投递」共用。"""
    from app.api.studio import _jsonable, _widget_items, build_studio_html

    dash = await db.get(Dashboard, str(sub.dashboard_id))
    if not dash:
        raise ValueError("看板不存在")
    source = await db.get(DataSource, str(dash.data_source_id))
    owner = await db.get(User, str(sub.owner_id))
    if not source or not owner:
        raise ValueError("数据源或用户不存在")

    widget_rows = (
        await db.execute(
            select(DashboardWidget)
            .where(DashboardWidget.dashboard_id == dash.id)
            .order_by(DashboardWidget.sort_order.asc(), DashboardWidget.created_at.asc())
        )
    ).scalars().all()
    items = await _widget_items(db, list(widget_rows), source, owner)
    version = max(int(dash.version or 1) - 1, 1) if dash.status == "published" else int(dash.version or 1)
    html = build_studio_html(dash.name or "自助分析看板", version, items)
    summary = [
        {"label": w.get("title") or "", "value": (w.get("options") or {}).get("value")}
        for w in items if w.get("widget_type") == "kpi_card" and not w.get("error")
    ]
    run = SubscriptionRun(
        subscription_id=sub.id,
        dashboard_id=dash.id,
        status="ok",
        summary_json=_jsonable(summary),
        html=html,
        channel=sub.channel,
        target=sub.target or "",
    )
    db.add(run)
    await db.flush()

    token = sign_embed({
        "did": dash.id,
        "rid": run.id,
        "exp": int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)).timestamp()),
    })
    base = str(getattr(sub, "link_base", "") or "").rstrip("/")
    link = f"{base}/api/v1/studio/embed/{token}" if base else f"/api/v1/studio/embed/{token}"
    kpi_text = "；".join(f"{s['label']} {s['value']:,.2f}" if isinstance(s["value"], (int, float)) else f"{s['label']} {s['value']}" for s in summary) or "无 KPI 卡片"
    errors = [w for w in items if w.get("error")]
    text = (
        f"看板「{dash.name}」订阅快照（{len(items)} 个组件"
        f"{f'，{len(errors)} 个计算失败' if errors else ''}）。\n"
        f"KPI：{kpi_text}\n查看完整快照：{link}"
    )
    ok, err = await deliver(db, channel=sub.channel, target=sub.target or "", owner=owner,
                            title=f"看板订阅 · {dash.name}", text=text)
    run.delivered = ok
    run.error = err
    sub.last_run_at = datetime.datetime.now(datetime.timezone.utc)
    sub.next_run_at = compute_next_run(sub)
    return run


@celery_app.task(name="studio.dispatch_subscriptions")
def dispatch_subscriptions() -> None:
    async def _run() -> None:
        async with SubSessionLocal() as db:
            now = datetime.datetime.now(datetime.timezone.utc)
            subs = (
                await db.execute(
                    select(DashboardSubscription).where(
                        DashboardSubscription.active.is_(True),
                        DashboardSubscription.next_run_at.isnot(None),
                        DashboardSubscription.next_run_at <= now,
                    ).limit(50)
                )
            ).scalars().all()
            for sub in subs:
                try:
                    await run_subscription(db, sub)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("subscription %s failed: %s", sub.id, exc)
                    sub.last_run_at = now
                    sub.next_run_at = compute_next_run(sub, now)
                    db.add(SubscriptionRun(
                        subscription_id=sub.id, dashboard_id=sub.dashboard_id,
                        status="failed", channel=sub.channel, target=sub.target or "",
                        delivered=False, error=str(exc)[:1000],
                    ))
            await db.commit()

    run_in_persistent_loop(_run())


# ── 告警评估 ──────────────────────────────────────────────

def lookback_range(lookback: str) -> tuple[str, str]:
    today = datetime.datetime.now(CN_TZ).date()
    if lookback == "yesterday":
        d = today - datetime.timedelta(days=1)
        return d.isoformat(), d.isoformat()
    if lookback == "this_month":
        return today.replace(day=1).isoformat(), today.isoformat()
    if lookback == "last_7d":
        return (today - datetime.timedelta(days=6)).isoformat(), today.isoformat()
    return today.isoformat(), today.isoformat()


def compare(value: float, op: str, threshold: float) -> bool:
    return {
        ">": value > threshold,
        ">=": value >= threshold,
        "<": value < threshold,
        "<=": value <= threshold,
        "==": value == threshold,
        "!=": value != threshold,
    }[op]


async def evaluate_alert(
    db: AsyncSession, rule: AlertRule, source: DataSource, user: User
) -> tuple[float | None, bool, dict[str, Any] | None]:
    """执行聚合指标并判断是否越界；供周期任务与「立即检查」共用。

    P3-2：detect=zscore 时做异常检测——当前值 vs 过去 zscore_window 天日序列基线，
    |z| >= zscore_sigma 判异常（双向：暴涨暴跌都算）；返回 detail 供事件消息展示。
    """
    from app.core.analysis.operators import execute_spec

    start, end = lookback_range(rule.lookback or "today")
    spec = {
        "type": "aggregate",
        "data_source_id": str(source.id),
        "metrics": [{"name": rule.metric_name or "指标", "expr": rule.metric_expr, "alias": "m0"}],
        "time_range": {"field": rule.time_field or "RQ", "start": start, "end": end},
        "limit": 1,
    }
    result = await execute_spec(db, source, spec, user=user)
    value = None
    if result["rows"] and result["rows"][0]:
        try:
            value = float(result["rows"][0][0])
        except (TypeError, ValueError):
            value = None
    if (getattr(rule, "detect", "") or "threshold") != "zscore":
        violated = value is not None and compare(value, rule.op or "<", float(rule.threshold or 0))
        return value, violated, None

    # ── z-score 异常检测 ──
    if value is None:
        return None, False, None
    window = max(7, min(int(rule.zscore_window or 28), 180))
    sigma = max(0.5, min(float(rule.zscore_sigma or 3.0), 10.0))
    base_end = datetime.date.fromisoformat(end) - datetime.timedelta(days=1)
    base_start = base_end - datetime.timedelta(days=window - 1)
    ts_spec = {
        "type": "timeseries",
        "data_source_id": str(source.id),
        "metrics": [{"name": rule.metric_name or "指标", "expr": rule.metric_expr, "alias": "m0"}],
        "time_range": {
            "field": rule.time_field or "RQ",
            "start": base_start.isoformat(),
            "end": base_end.isoformat(),
            "granularity": "day",
        },
        "limit": window + 5,
    }
    try:
        ts = await execute_spec(db, source, ts_spec, user=user)
    except Exception as exc:  # noqa: BLE001 - 基线取数失败按未越界处理并留痕
        logger.warning("zscore baseline failed rule=%s err=%s", rule.id, exc)
        return value, False, {"error": f"基线取数失败：{str(exc)[:200]}"}
    series: list[float] = []
    for row in ts.get("rows") or []:
        try:
            series.append(float(row[1]))
        except (TypeError, ValueError, IndexError):
            continue
    if len(series) < 5:
        return value, False, {"error": f"基线样本不足（{len(series)} 天 < 5 天）"}
    mean = sum(series) / len(series)
    var = sum((x - mean) ** 2 for x in series) / len(series)
    std = var ** 0.5
    if std <= 0:
        return value, False, {"error": "基线波动为零，无法计算偏离度"}
    z = (value - mean) / std
    violated = abs(z) >= sigma
    detail = {
        "mean": round(mean, 4),
        "std": round(std, 4),
        "z": round(z, 4),
        "sigma": sigma,
        "window": window,
        "series_days": len(series),
        "base_start": base_start.isoformat(),
        "base_end": base_end.isoformat(),
    }
    return value, violated, detail


async def check_rule(db: AsyncSession, rule: AlertRule) -> AlertEvent | None:
    """评估单条规则，越界则记录事件并按冷却窗口通知。"""
    source = await db.get(DataSource, str(rule.data_source_id))
    owner = await db.get(User, str(rule.owner_id))
    now = datetime.datetime.now(datetime.timezone.utc)
    if not source or not owner:
        rule.last_checked_at = now
        return None
    value, violated, detail = await evaluate_alert(db, rule, source, owner)
    rule.last_checked_at = now
    rule.last_value = value
    if not violated:
        return None

    if detail is not None:  # z-score 异常检测口径
        message = (
            f"【异常告警】{rule.name}：{rule.metric_name} = {value:,.2f}，"
            f"偏离基线 {detail['z']:+.1f}σ（阈值 ±{detail['sigma']}σ，"
            f"基线均值 {detail['mean']:,.2f}，σ {detail['std']:,.2f}，"
            f"窗口 {detail['series_days']} 天，数据源 {source.name}）"
        )
    else:
        message = (
            f"【告警】{rule.name}：{rule.metric_name} = {value:,.2f}，"
            f"触发条件 {rule.op} {rule.threshold:,.2f}（口径 {rule.lookback}，数据源 {source.name}）"
        )
    cooldown_ok = (
        rule.last_triggered_at is None
        or (now - rule.last_triggered_at) > datetime.timedelta(hours=int(rule.cooldown_hours or 24))
    )
    notified = False
    if cooldown_ok:
        ok, _err = await deliver(
            db, channel=rule.channel, target=rule.target or "", owner=owner,
            title=f"异常告警 · {rule.name}" if detail is not None else f"阈值告警 · {rule.name}",
            text=message,
        )
        notified = ok
        if ok:
            rule.last_triggered_at = now
    event = AlertEvent(
        rule_id=rule.id, value=value, threshold=float(rule.threshold or 0),
        message=message, notified=notified,
    )
    db.add(event)
    return event


@celery_app.task(name="studio.check_alerts")
def check_alerts() -> None:
    async def _run() -> None:
        async with SubSessionLocal() as db:
            now = datetime.datetime.now(datetime.timezone.utc)
            rules = (
                await db.execute(
                    select(AlertRule).where(AlertRule.active.is_(True)).limit(200)
                )
            ).scalars().all()
            for rule in rules:
                if rule.last_checked_at and (
                    now - rule.last_checked_at
                ) < datetime.timedelta(minutes=int(rule.interval_minutes or 60)):
                    continue
                try:
                    await check_rule(db, rule)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("alert rule %s failed: %s", rule.id, exc)
                    rule.last_checked_at = now
            await db.commit()

    run_in_persistent_loop(_run())
