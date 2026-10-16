"""看板生成 Celery 任务：七阶段编排，全程事件留痕。

intent → schema_probe → metric_fetch → anchor_check → render → verify → done
任一阶段失败：artifact.status=failed + error + DashboardEvent(fail)，显式不静默。
与 distill_tasks 同模式：NullPool 独立引擎 + run_in_persistent_loop。
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.tasks_runtime import run_in_persistent_loop
from app.worker import celery_app

logger = logging.getLogger("dashboard.tasks")

_dash_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
DashSessionLocal = async_sessionmaker(_dash_engine, expire_on_commit=False)

STAGES = ["intent", "schema_probe", "metric_fetch", "anchor_check", "render", "verify", "done"]
_STAGE_PROGRESS = {
    "intent": 5, "schema_probe": 15, "metric_fetch": 30,
    "anchor_check": 70, "render": 82, "verify": 92, "done": 100,
}


@celery_app.task(name="dashboard.generate", ignore_result=True, max_retries=0)
def dashboard_generate_task(artifact_id: str) -> None:
    from app.db.models import DashboardArtifact, DashboardEvent

    async def _emit(db, art, stage: str, status: str, detail: dict | None = None) -> None:
        art.stage = stage
        art.progress = _STAGE_PROGRESS.get(stage, art.progress)
        if stage != "done" and status == "start":
            art.status = "running"
        db.add(DashboardEvent(dashboard_id=str(art.id), stage=stage, status=status, detail=detail or {}))
        await db.commit()

    async def _run() -> None:
        from app.db.models import Conversation, DataSource, Message, MessageRole, User

        async with DashSessionLocal() as db:
            art = await db.get(DashboardArtifact, str(artifact_id))
            if not art:
                logger.error("dashboard artifact missing: %s", artifact_id)
                return
            await _emit(db, art, "intent", "start")
            source = await db.get(DataSource, str(art.data_source_id))
            user = await db.get(User, str(art.user_id)) if art.user_id else None
            if not source or not user:
                raise RuntimeError("数据源或用户不存在")
            from app.core.dashboard.template import TEMPLATE_ID, TEMPLATE_NAME

            if art.template != TEMPLATE_ID:
                raise RuntimeError(f"未知看板模板：{art.template}")
            await _emit(db, art, "intent", "ok", {"template": TEMPLATE_ID, "name": TEMPLATE_NAME})

            # ── schema_probe + metric_fetch（治理链取数）──
            await _emit(db, art, "schema_probe", "start")
            from app.core.dashboard.builder import fetch_snapshot

            await _emit(db, art, "metric_fetch", "start")
            snap = await fetch_snapshot(db, source, user)
            art.snapshot = snap
            anchor = snap.get("anchor") or {}
            art.period_start = anchor.get("min_rq")
            art.period_end = anchor.get("max_rq")
            kpi_rows = len(snap.get("daily") or [])
            await _emit(db, art, "metric_fetch", "ok", {
                "table": snap.get("_table"), "daily_days": kpi_rows,
                "row_permission": (snap.get("_govern") or {}).get("row_permission"),
                "period": f"{art.period_start} ~ {art.period_end}",
            })

            # ── anchor_check ──
            await _emit(db, art, "anchor_check", "start")
            from app.core.dashboard.builder import check_anchor

            anchor_detail = check_anchor(snap)
            art.anchor_status = anchor_detail["status"]
            art.anchor_detail = anchor_detail
            await _emit(db, art, "anchor_check",
                        "ok" if anchor_detail["status"] == "pass" else "warn",
                        anchor_detail)

            # ── render ──
            await _emit(db, art, "render", "start")
            from app.core.dashboard.renderer import card_kpis, render_retail_dashboard

            title = art.title or f"{source.name} · 零售经营分析看板"
            html_text = render_retail_dashboard(
                snap, title=title, source_name=str(source.name),
                anchor_detail=anchor_detail, generated_at=datetime.now(),
            )
            art.html = html_text
            art.kpis = card_kpis(snap)
            await _emit(db, art, "render", "ok", {"html_bytes": len(html_text)})

            # ── verify（无头浏览器，通过才置 done）──
            await _emit(db, art, "verify", "start")
            from app.core.dashboard.verifier import verify_dashboard

            report = await verify_dashboard(html_text)
            art.verify_report = report
            await _emit(db, art, "verify", "ok", {
                "svg_count": (report.get("browser") or {}).get("svg_count"),
                "table_rows": (report.get("browser") or {}).get("table_rows"),
            })

            # ── done：状态 + 会话卡片消息 ──
            art.status = "done"
            card = {
                "event": "dashboard_card",
                "artifact_id": str(art.id),
                "title": title,
                "period": f"{art.period_start} ~ {art.period_end}",
                "kpis": art.kpis,
                "anchor_status": art.anchor_status,
                "view_url": f"/api/v1/dashboards/{art.id}/view",
                "stages": STAGES,
            }
            if art.conversation_id:
                conv = await db.get(Conversation, str(art.conversation_id))
                if conv and conv.is_active:
                    kpi_txt = "；".join(f"{k['label']} {k['value']}" for k in (art.kpis or []))
                    content = (
                        f"经营分析看板已生成：**{title}**（{card['period']}）。\n\n"
                        f"{kpi_txt}。点击卡片在新窗口查看完整看板。"
                    )
                    msg = Message(
                        conversation_id=str(conv.id), role=MessageRole.assistant,
                        content=content,
                        metadata_={"dashboard_card": card, "data_source_id": str(source.id)},
                    )
                    db.add(msg)
                    await db.flush()
                    art.message_id = str(msg.id)
            await _emit(db, art, "done", "ok", {"card": bool(art.conversation_id)})

    async def _fail(exc: Exception) -> None:
        async with DashSessionLocal() as db:
            art = await db.get(DashboardArtifact, str(artifact_id))
            if not art:
                return
            art.status = "failed"
            art.error = str(exc)[:2000]
            db.add(DashboardEvent(
                dashboard_id=str(art.id), stage=art.stage or "unknown",
                status="fail", detail={"error": str(exc)[:1000]},
            ))
            await db.commit()

    try:
        run_in_persistent_loop(_run())
    except Exception as exc:
        logger.exception("dashboard_generate_task failed artifact=%s", artifact_id)
        try:
            run_in_persistent_loop(_fail(exc))
        except Exception:
            pass
