"""P2 自助看板：看板/卡片 CRUD、执行、发布快照与 HTML 分享。"""
from __future__ import annotations

import datetime
import decimal
import html as _html
import json as _json
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.analysis.operators import AnalysisError, execute_spec
from app.core.analysis.spec import SpecError, chart_hint, normalize_spec, spec_hash
from app.core.auth.deps import get_current_user
from app.core.data_ask.govern.access import assert_data_source_access
from app.db.models import (
    AnalysisSpec,
    Dashboard,
    DashboardSnapshot,
    DashboardWidget,
    DataSource,
    User,
)
from app.db.session import get_db

router = APIRouter(prefix="/studio", tags=["DashboardStudio"])

_TYPE_MAP = {
    "timeseries": "trend_line",
    "distribution": "share_pie",
    "topn": "rank_bar",
    "detail": "detail_table",
    "aggregate": "kpi_card",
    "contribution": "pareto_bar",
    "pareto": "pareto_bar",
    "breakdown": "bar",
    "outlier": "anomaly_scatter",
    "forecast": "forecast_line",
    "correlation": "scatter",
    "cluster": "scatter",
    "cohort": "heatmap",
    "funnel": "funnel_bar",
    "period_compare": "bar",
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


async def _load_source(db: AsyncSession, sid: str, user: User) -> DataSource:
    source = await db.get(DataSource, sid)
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    await assert_data_source_access(db, source, user, require_chat=True)
    return source


async def _load_dashboard(db: AsyncSession, did: str, user: User) -> tuple[Dashboard, DataSource]:
    row = await db.get(Dashboard, str(did))
    if not row:
        raise HTTPException(status_code=404, detail="看板不存在")
    if str(row.owner_id or "") != str(user.id) and not user.is_admin and row.status != "published":
        raise HTTPException(status_code=403, detail="无权访问该看板")
    source = await _load_source(db, str(row.data_source_id), user)
    return row, source


async def _widget_items(db: AsyncSession, rows: list[DashboardWidget], source: DataSource, user: User) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for w in rows:
        item: dict[str, Any] = {
            "id": w.id,
            "widget_type": w.widget_type,
            "title": w.title or "",
            "layout": dict(w.layout_json or {}),
            "options": dict(w.options_json or {}),
            "drill": dict(w.drill_json or {}),
            "sort_order": w.sort_order or 0,
            "spec_id": w.spec_id,
        }
        spec_row = await db.get(AnalysisSpec, str(w.spec_id)) if w.spec_id else None
        if not spec_row:
            item["error"] = "分析定义不存在"
            items.append(item)
            continue
        item["spec"] = spec_row.spec_json
        try:
            result = await execute_spec(db, source, spec_row.spec_json or {}, user=user)
        except AnalysisError as exc:
            item["error"] = str(exc)
            items.append(item)
            continue
        except SpecError as exc:
            item["error"] = str(exc)
            items.append(item)
            continue
        item["columns"] = result["columns"]
        item["rows"] = _jsonable(result["rows"])[:500]
        item["facts"] = result["facts"]
        item["chart"] = result["chart"]
        item["spec_hash"] = result["spec_hash"]
        item["query_ms"] = result["query"]["elapsed_ms"]
        if w.widget_type == "kpi_card" and result["rows"]:
            options = dict(item["options"])
            options["value"] = _jsonable(result["rows"][0][0])
            item["options"] = options
        items.append(item)
    return items


def _auto_options(spec: dict[str, Any]) -> dict[str, Any]:
    chart = chart_hint(spec)
    options: dict[str, Any] = {"series": chart.get("series") or [], "chart": chart}
    if spec.get("dimensions"):
        options["dimension"] = spec["dimensions"][0]
    if spec.get("metrics"):
        options["metric"] = spec["metrics"][0]["name"]
    return options


def _html_escape(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return _html.escape(str(value))


def build_studio_html(name: str, version: int, widgets: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for w in widgets:
        title = _html.escape(str(w.get("title") or w.get("widget_type") or "卡片"))
        if w.get("error"):
            cards.append(
                f'<section class="card"><h3>{title}</h3><p class="err">{_html.escape(str(w["error"]))}</p></section>'
            )
            continue
        if w.get("widget_type") == "kpi_card":
            value = (w.get("options") or {}).get("value")
            cards.append(f'<section class="card kpi"><div class="t">{title}</div><div class="v">{_html_escape(value)}</div></section>')
            continue
        columns = [str(c) for c in (w.get("columns") or [])]
        rows = (w.get("rows") or [])[:40]
        head = "".join(f"<th>{_html.escape(c)}</th>" for c in columns)
        body = "".join(
            "<tr>" + "".join(f"<td>{_html_escape(cell)}</td>" for cell in r) + "</tr>" for r in rows
        )
        facts = "".join(f"<li>{_html.escape(str(f.get('text', '')))}</li>" for f in (w.get("facts") or [])[:4])
        cards.append(
            f'<section class="card"><h3>{title}</h3>'
            f'<div class="meta">{_html.escape(str(w.get("widget_type")))} · {len(w.get("rows") or [])} 行</div>'
            f'<div class="tw"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
            f'<ul class="facts">{facts}</ul></section>'
        )
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html.escape(name)} · v{version}</title>
<style>
body{{font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:#f5f7fa;color:#17202e;margin:0;padding:24px}}
.wrap{{max-width:1280px;margin:0 auto}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#64748b;font-size:12px;margin-bottom:16px}}
.grid{{display:grid;grid-template-columns:repeat(12,1fr);gap:12px}}
.card{{grid-column:span 6;background:#fff;border:1px solid #e3e9f2;border-radius:12px;padding:12px;box-shadow:0 1px 2px rgba(15,23,42,.04)}}
.card.kpi{{grid-column:span 3;background:linear-gradient(135deg,#fff,#eff6ff)}}
.card.kpi .t{{font-size:12px;color:#64748b}} .card.kpi .v{{font-size:24px;font-weight:600;margin-top:4px}}
h3{{font-size:13px;margin:0 0 8px}} .meta{{font-size:11px;color:#94a3b8;margin-bottom:6px}}
.tw{{max-height:360px;overflow:auto}} table{{width:100%;border-collapse:collapse;font-size:12px}}
th,td{{border-bottom:1px solid #eef2f7;padding:4px 6px;text-align:left;white-space:nowrap}}
th{{background:#f8fafc;color:#475569;position:sticky;top:0}}
.facts{{font-size:11px;color:#475569;margin:8px 0 0 16px}} .err{{color:#dc2626;font-size:12px}}
@media(max-width:900px){{.card,.card.kpi{{grid-column:span 12}}}}
</style></head><body><div class="wrap">
<h1>{_html.escape(name)}</h1><div class="sub">发布版本 v{version} · {len(widgets)} 个组件 · 数字均由数据库实时计算</div>
<div class="grid">{''.join(cards)}</div></div></body></html>"""


@router.get("/dashboards")
async def list_dashboards(
    data_source_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Dashboard).where(
        or_(Dashboard.owner_id == str(user.id), Dashboard.status == "published")
    )
    if data_source_id:
        stmt = stmt.where(Dashboard.data_source_id == data_source_id)
    rows = (await db.execute(stmt.order_by(Dashboard.updated_at.desc()).limit(100))).scalars().all()
    items = []
    for d in rows:
        count = (
            await db.execute(select(DashboardWidget.id).where(DashboardWidget.dashboard_id == d.id))
        ).scalars().all()
        items.append({
            "id": d.id,
            "name": d.name,
            "data_source_id": d.data_source_id,
            "status": d.status,
            "version": d.version,
            "widget_count": len(count),
            "updated_at": d.updated_at,
        })
    return {"items": items}


@router.post("/dashboards")
async def create_dashboard(
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sid = str(payload.get("data_source_id") or "").strip()
    if not sid:
        raise HTTPException(status_code=422, detail="data_source_id 必填")
    await _load_source(db, sid, user)
    name = str(payload.get("name") or "").strip()[:120] or "自助分析看板"
    row = Dashboard(
        data_source_id=sid,
        owner_id=str(user.id),
        name=name,
        status="draft",
        version=1,
        layout_json={"cols": 12},
        filters_json=payload.get("filters") or [],
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "name": row.name, "status": row.status, "version": row.version}


@router.get("/dashboards/{did}")
async def get_dashboard(
    did: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row, source = await _load_dashboard(db, did, user)
    widget_rows = (
        await db.execute(
            select(DashboardWidget)
            .where(DashboardWidget.dashboard_id == row.id)
            .order_by(DashboardWidget.sort_order.asc(), DashboardWidget.created_at.asc())
        )
    ).scalars().all()
    items = await _widget_items(db, list(widget_rows), source, user)
    return {
        "id": row.id,
        "name": row.name,
        "data_source_id": row.data_source_id,
        "status": row.status,
        "version": row.version,
        "filters": row.filters_json or [],
        "widgets": items,
    }


@router.patch("/dashboards/{did}")
async def patch_dashboard(
    did: str,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row, _ = await _load_dashboard(db, did, user)
    if str(row.owner_id or "") != str(user.id) and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有创建者可修改")
    if "name" in payload:
        row.name = str(payload.get("name") or "").strip()[:120] or row.name
    if "filters" in payload and isinstance(payload["filters"], list):
        row.filters_json = payload["filters"]
    if row.status == "published":
        row.status = "draft"
    await db.commit()
    return {"id": row.id, "name": row.name, "status": row.status}


@router.delete("/dashboards/{did}")
async def delete_dashboard(
    did: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row, _ = await _load_dashboard(db, did, user)
    if str(row.owner_id or "") != str(user.id) and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有创建者可删除")
    await db.execute(delete(DashboardWidget).where(DashboardWidget.dashboard_id == row.id))
    await db.execute(delete(DashboardSnapshot).where(DashboardSnapshot.dashboard_id == row.id))
    await db.delete(row)
    await db.commit()
    return {"deleted": True}


@router.post("/dashboards/{did}/widgets")
async def add_widget(
    did: str,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row, _ = await _load_dashboard(db, did, user)
    if str(row.owner_id or "") != str(user.id) and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有创建者可添加卡片")
    raw_spec = payload.get("spec")
    if not isinstance(raw_spec, dict):
        raise HTTPException(status_code=422, detail="spec 必填")
    raw_spec = {**raw_spec, "data_source_id": row.data_source_id}
    try:
        spec = normalize_spec(raw_spec)
    except SpecError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc

    title = str(payload.get("title") or spec["name"])[:120]
    widget_type = str(payload.get("widget_type") or _TYPE_MAP.get(spec["type"], "detail_table"))
    if widget_type not in _TYPE_MAP.values():
        raise HTTPException(status_code=422, detail=f"不支持的组件类型: {widget_type}")
    spec_row = AnalysisSpec(
        data_source_id=row.data_source_id,
        owner_id=str(user.id),
        name=title,
        spec_json=spec,
        spec_hash=spec_hash(spec),
        version=1,
    )
    db.add(spec_row)
    await db.flush()

    existing = (
        await db.execute(select(DashboardWidget).where(DashboardWidget.dashboard_id == row.id))
    ).scalars().all()
    order = len(existing)
    layout = payload.get("layout") if isinstance(payload.get("layout"), dict) else {}
    layout = {
        "x": int(layout.get("x", 0)),
        "y": int(layout.get("y", (order // 2) * 4)),
        "w": max(3, min(int(layout.get("w", 6)), 12)),
        "h": max(3, min(int(layout.get("h", 4)), 12)),
    }
    widget = DashboardWidget(
        dashboard_id=row.id,
        spec_id=spec_row.id,
        widget_type=widget_type,
        title=title,
        layout_json=layout,
        binding_json=[],
        drill_json=payload.get("drill") or {},
        options_json={**_auto_options(spec), **(payload.get("options") or {})},
        sort_order=order,
    )
    db.add(widget)
    row.status = "draft"
    await db.commit()
    await db.refresh(widget)
    return {"id": widget.id, "widget_type": widget.widget_type, "title": widget.title, "layout": layout, "spec_id": spec_row.id}


@router.patch("/dashboards/{did}/widgets/{wid}")
async def patch_widget(
    did: str,
    wid: str,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row, _ = await _load_dashboard(db, did, user)
    if str(row.owner_id or "") != str(user.id) and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有创建者可修改卡片")
    widget = await db.get(DashboardWidget, str(wid))
    if not widget or str(widget.dashboard_id) != str(row.id):
        raise HTTPException(status_code=404, detail="卡片不存在")
    if "title" in payload:
        widget.title = str(payload.get("title") or "").strip()[:120] or widget.title
    if "widget_type" in payload:
        widget.widget_type = str(payload["widget_type"])
    if isinstance(payload.get("layout"), dict):
        layout = payload["layout"]
        widget.layout_json = {
            "x": int(layout.get("x", 0)),
            "y": int(layout.get("y", 0)),
            "w": max(3, min(int(layout.get("w", 6)), 12)),
            "h": max(3, min(int(layout.get("h", 4)), 12)),
        }
    if isinstance(payload.get("options"), dict):
        widget.options_json = {**(widget.options_json or {}), **payload["options"]}
    if "sort_order" in payload:
        widget.sort_order = int(payload["sort_order"])
    if isinstance(payload.get("spec"), dict):
        raw = {**payload["spec"], "data_source_id": row.data_source_id}
        try:
            spec = normalize_spec(raw)
        except SpecError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc
        spec_row = AnalysisSpec(
            data_source_id=row.data_source_id,
            owner_id=str(user.id),
            name=widget.title or spec["name"],
            spec_json=spec,
            spec_hash=spec_hash(spec),
            version=1,
        )
        db.add(spec_row)
        await db.flush()
        widget.spec_id = spec_row.id
        widget.options_json = {**_auto_options(spec), **(widget.options_json or {})}
    row.status = "draft"
    await db.commit()
    return {"id": widget.id, "title": widget.title, "layout": widget.layout_json, "sort_order": widget.sort_order}


@router.delete("/dashboards/{did}/widgets/{wid}")
async def delete_widget(
    did: str,
    wid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row, _ = await _load_dashboard(db, did, user)
    if str(row.owner_id or "") != str(user.id) and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有创建者可删除卡片")
    widget = await db.get(DashboardWidget, str(wid))
    if not widget or str(widget.dashboard_id) != str(row.id):
        raise HTTPException(status_code=404, detail="卡片不存在")
    await db.delete(widget)
    row.status = "draft"
    await db.commit()
    return {"deleted": True}


@router.post("/dashboards/{did}/publish")
async def publish_dashboard(
    did: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row, source = await _load_dashboard(db, did, user)
    if str(row.owner_id or "") != str(user.id) and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有创建者可发布")
    widget_rows = (
        await db.execute(
            select(DashboardWidget)
            .where(DashboardWidget.dashboard_id == row.id)
            .order_by(DashboardWidget.sort_order.asc(), DashboardWidget.created_at.asc())
        )
    ).scalars().all()
    if not widget_rows:
        raise HTTPException(status_code=422, detail="看板还没有卡片")
    items = await _widget_items(db, list(widget_rows), source, user)
    version = int(row.version or 1)
    snapshot = {
        "dashboard_id": row.id,
        "name": row.name,
        "version": version,
        "published_at": datetime.datetime.utcnow().isoformat(),
        "data_source_id": row.data_source_id,
        "widgets": items,
    }
    errors = sum(1 for x in items if x.get("error"))
    html = build_studio_html(row.name or "自助分析看板", version, items)
    snap = DashboardSnapshot(
        dashboard_id=row.id,
        version=version,
        snapshot_json=_jsonable(snapshot),
        html=html,
        anchor_status="warn" if errors else "pass",
    )
    db.add(snap)
    row.version = version + 1
    row.status = "published"
    await db.commit()
    await db.refresh(snap)
    return {
        "snapshot_id": snap.id,
        "version": version,
        "widgets": len(items),
        "errors": errors,
        "html_url": f"/api/v1/studio/dashboards/{row.id}/html?version={version}",
    }


@router.get("/dashboards/{did}/versions")
async def list_versions(
    did: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row, _ = await _load_dashboard(db, did, user)
    rows = (
        await db.execute(
            select(DashboardSnapshot)
            .where(DashboardSnapshot.dashboard_id == row.id)
            .order_by(DashboardSnapshot.version.desc())
            .limit(30)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": s.id,
                "version": s.version,
                "anchor_status": s.anchor_status,
                "created_at": s.created_at,
                "widget_count": len((s.snapshot_json or {}).get("widgets") or []),
                "html_url": f"/api/v1/studio/dashboards/{row.id}/html?version={s.version}",
            }
            for s in rows
        ]
    }


@router.get("/dashboards/{did}/versions/{version}")
async def get_version(
    did: str,
    version: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row, _ = await _load_dashboard(db, did, user)
    snap = (
        await db.execute(
            select(DashboardSnapshot).where(
                DashboardSnapshot.dashboard_id == row.id,
                DashboardSnapshot.version == version,
            )
        )
    ).scalar_one_or_none()
    if not snap:
        raise HTTPException(status_code=404, detail="快照不存在")
    return {"version": snap.version, "anchor_status": snap.anchor_status, "snapshot": snap.snapshot_json}


@router.get("/dashboards/{did}/html")
async def studio_html(
    did: str,
    version: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row, _ = await _load_dashboard(db, did, user)
    stmt = select(DashboardSnapshot).where(DashboardSnapshot.dashboard_id == row.id)
    if version is not None:
        stmt = stmt.where(DashboardSnapshot.version == version)
    snap = (await db.execute(stmt.order_by(DashboardSnapshot.version.desc()).limit(1))).scalar_one_or_none()
    if not snap or not snap.html:
        raise HTTPException(status_code=409, detail="尚未发布")
    return HTMLResponse(content=snap.html, status_code=200)
