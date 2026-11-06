"""主动工作引擎（蓝图阶段三试点）：规则 → 评估 → observe 记录 / auto 推送。

试点规则 sales_drop：最新营业日销售额较上一营业日跌超阈值即触发。
- observe：只落 tasks 记录（report.stage=observe，管理台可评审准确率）
- auto：走 Outbox 推送给 targets，并落 tasks 记录（stage=alert）

规则配置存 SystemSetting「proactive.rules」（缺省用 DEFAULT_RULES）；
运行状态（每日一次去重）存 SystemSetting「proactive.state」。
"""
from __future__ import annotations

import asyncio
import datetime
from typing import Any

import structlog

from app.core.tasks import DONE, create_task, finish_task
from app.core.tasks.outbox import send_now
from app.db.models import DataSource, SystemSetting
from app.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)

RULES_KEY = "proactive.rules"
STATE_KEY = "proactive.state"
_TICK = 60.0

DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "id": "sales-drop-daily",
        "name": "销售额日环比预警",
        "kind": "sales_drop",
        "enabled": True,
        "time": "08:30",
        "mode": "observe",
        "targets": [],
        "params": {
            "data_source_id": "cd3e8625-06b8-4cae-a94d-e26432680c39",
            "table": "SR_CS_SPJXCPCRBB",
            "date_col": "RQ",
            "amount_col": "XSJE",
            "threshold_pct": 10,
        },
    }
]

_engine_task: asyncio.Task | None = None


async def _load_rules(db) -> list[dict[str, Any]]:
    row = await db.get(SystemSetting, RULES_KEY)
    if row and isinstance(row.value, list) and row.value:
        return list(row.value)
    return list(DEFAULT_RULES)


async def _load_state(db) -> dict[str, str]:
    row = await db.get(SystemSetting, STATE_KEY)
    return dict(row.value) if row and isinstance(row.value, dict) else {}


async def _save_state(state: dict[str, str]) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(SystemSetting, STATE_KEY)
        if row:
            row.value = state
        else:
            db.add(SystemSetting(key=STATE_KEY, value=state))
        await db.commit()


async def _eval_sales_drop(params: dict[str, Any]) -> str | None:
    """返回触发文案；未触发或数据不足返回 None。"""
    from app.core.data_ask.connectors.factory import build_connector_from_source

    async with AsyncSessionLocal() as db:
        source = await db.get(DataSource, str(params.get("data_source_id") or ""))
    if source is None:
        logger.warning("proactive_source_missing", source_id=params.get("data_source_id"))
        return None
    table = str(params.get("table") or "")
    date_col = str(params.get("date_col") or "")
    amount_col = str(params.get("amount_col") or "")
    if not (table and date_col and amount_col):
        return None
    conn = build_connector_from_source(source)
    try:
        qr = await conn.execute_select(
            f"SELECT {date_col}, SUM({amount_col}) FROM {table} "
            f"GROUP BY {date_col} ORDER BY {date_col} DESC LIMIT 2",
            limit=2,
        )
    except Exception as exc:
        logger.warning("proactive_query_failed", error=str(exc)[:200])
        return None
    finally:
        await conn.close()
    rows = list(qr.rows or [])
    if len(rows) < 2:
        return None
    (d0, v0), (d1, v1) = rows[0], rows[1]
    try:
        v0, v1 = float(v0 or 0), float(v1 or 0)
    except (TypeError, ValueError):
        return None
    if v1 <= 0:
        return None
    drop = (v1 - v0) / v1 * 100
    threshold = float(params.get("threshold_pct") or 10)
    if drop < threshold:
        return None
    return (
        f"销售额日环比下降 {drop:.1f}%（{d0}：{v0:.2f} 元，{d1}：{v1:.2f} 元，"
        f"阈值 {threshold:.0f}%）"
    )


async def run_rule(rule: dict[str, Any]) -> None:
    kind = str(rule.get("kind") or "")
    text: str | None = None
    if kind == "sales_drop":
        text = await _eval_sales_drop(rule.get("params") or {})
    if not text:
        logger.info("proactive_rule_silent", rule_id=rule.get("id"))
        return
    rid = str(rule.get("id") or "")
    mode = str(rule.get("mode") or "observe")
    targets = [str(t) for t in (rule.get("targets") or []) if t]
    body = f"【{rule.get('name') or '预警'}】{text}"
    task_id = await create_task(
        user_id="proactive",
        question=body,
        target=targets,
        mandate={
            "basis": "proactive",
            "via": rid,
            "policy_version": None,
            "accept_mode": mode,
            "scope": {"rule": rid, "kind": kind},
            "decided_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    )
    if mode == "auto" and targets:
        # auto：走 Outbox 推送（落库可补发），任务记 stage=alert
        ok = await send_now(task_id=task_id, target=targets, content=body)
        await finish_task(
            task_id, status=DONE,
            report={"stage": "alert", "reply": body, "rule_id": rid, "pushed": ok},
        )
        logger.info("proactive_rule_pushed", rule_id=rid, ok=ok)
    else:
        # observe：只记录「本会做什么」，供评审准确率达标后再开 auto
        await finish_task(
            task_id, status=DONE,
            report={"stage": "observe", "would_do": body, "rule_id": rid},
        )
        logger.info("proactive_rule_observed", rule_id=rid)


async def _tick() -> None:
    now = datetime.datetime.now()
    hhmm = now.strftime("%H:%M")
    today = now.date().isoformat()
    async with AsyncSessionLocal() as db:
        rules = await _load_rules(db)
        state = await _load_state(db)
    dirty = False
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        if str(rule.get("time") or "") != hhmm:
            continue
        rid = str(rule.get("id") or "")
        if not rid or state.get(rid) == today:
            continue
        try:
            await run_rule(rule)
        except Exception as exc:
            logger.warning("proactive_rule_failed", rule_id=rid, error=str(exc)[:200])
        state[rid] = today
        dirty = True
    if dirty:
        await _save_state(state)


async def _loop() -> None:
    while True:
        try:
            await _tick()
        except Exception:
            pass
        await asyncio.sleep(_TICK)


def start_proactive_engine() -> None:
    """启动规则循环（幂等）。每 60s 检查一次到点规则。"""
    global _engine_task
    if _engine_task and not _engine_task.done():
        return
    _engine_task = asyncio.create_task(_loop(), name="proactive-engine")
    logger.info("proactive_engine_started")


async def stop_proactive_engine() -> None:
    global _engine_task
    if _engine_task:
        _engine_task.cancel()
        try:
            await _engine_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        _engine_task = None
