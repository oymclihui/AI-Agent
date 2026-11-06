"""P6 API：预聚合注册管理 + 查询缓存运维（限管理员）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.analysis.preagg import (
    preagg_table_name,
    refresh_preagg,
    validate_preagg_def,
)
from app.core.auth.deps import get_current_admin_user, get_current_user
from app.db.models import DataSource, DataSourceTable, DataSourceTableRole, PreAggregate, User
from app.db.session import get_db

router = APIRouter(prefix="/studio", tags=["DashboardStudioP6"])


def _pa_out(pa: PreAggregate) -> dict[str, Any]:
    return {
        "id": str(pa.id),
        "data_source_id": pa.data_source_id,
        "name": pa.name,
        "source_table": pa.source_table,
        "dimensions": list(pa.dimensions or []),
        "metrics": list(pa.metrics or []),
        "time_field": pa.time_field,
        "granularity": pa.granularity,
        "refresh_interval_min": pa.refresh_interval_min,
        "active": pa.active,
        "last_refresh_at": str(pa.last_refresh_at or "") or None,
        "last_status": pa.last_status,
        "last_rows": pa.last_rows,
        "local_table": preagg_table_name(str(pa.id)),
    }


@router.get("/preaggs")
async def list_preaggs(
    data_source_id: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    stmt = select(PreAggregate).order_by(PreAggregate.created_at.desc()).limit(200)
    if data_source_id:
        stmt = stmt.where(PreAggregate.data_source_id == data_source_id)
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_pa_out(p) for p in rows], "cache_ttl": _cache_ttl()}


def _cache_ttl() -> int:
    from app.core.analysis.operators import ANALYSIS_CACHE_TTL
    return int(ANALYSIS_CACHE_TTL)


@router.post("/preaggs")
async def create_preagg(
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    sid = str(payload.get("data_source_id") or "").strip()
    source = await db.get(DataSource, sid)
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")
    name = str(payload.get("name") or "").strip()[:120]
    if not name:
        raise HTTPException(status_code=422, detail="name 必填")
    dims = payload.get("dimensions")
    if not isinstance(dims, list) or any(not isinstance(d, str) for d in dims):
        raise HTTPException(status_code=422, detail="dimensions 必须是字符串数组")
    dims = list(dict.fromkeys(dims))
    metrics = payload.get("metrics")
    if not isinstance(metrics, list) or not all(isinstance(m, dict) for m in metrics):
        raise HTTPException(status_code=422, detail="metrics 必须是对象数组")
    time_field = str(payload.get("time_field") or "").strip()
    granularity = str(payload.get("granularity") or "").strip()
    err = validate_preagg_def(dims, metrics, time_field, granularity)
    if err:
        raise HTTPException(status_code=422, detail=err)
    try:
        interval = int(payload.get("refresh_interval_min") or 60)
    except (TypeError, ValueError):
        interval = 60
    interval = max(5, min(interval, 1440))

    table = str(payload.get("source_table") or "").strip()
    if not table:
        table = (
            await db.execute(
                select(DataSourceTable.table_name)
                .where(
                    DataSourceTable.data_source_id == sid,
                    DataSourceTable.role == DataSourceTableRole.data,
                )
                .order_by(DataSourceTable.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=422, detail="该数据源没有可用的数据表")

    pa = PreAggregate(
        data_source_id=sid,
        name=name,
        source_table=str(table),
        dimensions=dims,
        metrics=[{"name": str(m.get("name") or m.get("alias")), "expr": str(m["expr"]), "alias": str(m["alias"])} for m in metrics],
        time_field=time_field,
        granularity=granularity,
        refresh_interval_min=interval,
        active=True,
    )
    db.add(pa)
    await db.commit()
    await db.refresh(pa)
    # 立即做首次刷新
    try:
        await refresh_preagg(db, pa)
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        pa.last_status = str(exc)[:255]
        await db.commit()
        await db.refresh(pa)
    return _pa_out(pa)


@router.post("/preaggs/{pid}/refresh")
async def refresh_preagg_now(
    pid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    pa = await db.get(PreAggregate, str(pid))
    if not pa:
        raise HTTPException(status_code=404, detail="预聚合不存在")
    try:
        rows = await refresh_preagg(db, pa)
        await db.commit()
        return {"ok": True, "rows": rows, "item": _pa_out(pa)}
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        pa.last_status = str(exc)[:255]
        await db.commit()
        await db.refresh(pa)
        return {"ok": False, "error": str(exc)[:255], "item": _pa_out(pa)}


@router.patch("/preaggs/{pid}")
async def patch_preagg(
    pid: str,
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    pa = await db.get(PreAggregate, str(pid))
    if not pa:
        raise HTTPException(status_code=404, detail="预聚合不存在")
    if "active" in payload:
        pa.active = bool(payload["active"])
    if "refresh_interval_min" in payload:
        try:
            pa.refresh_interval_min = max(5, min(int(payload["refresh_interval_min"]), 1440))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="refresh_interval_min 必须是数字")
    if "name" in payload:
        pa.name = str(payload["name"] or "").strip()[:120] or pa.name
    await db.commit()
    await db.refresh(pa)
    return _pa_out(pa)


@router.delete("/preaggs/{pid}")
async def delete_preagg(
    pid: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    pa = await db.get(PreAggregate, str(pid))
    if not pa:
        raise HTTPException(status_code=404, detail="预聚合不存在")
    tname = preagg_table_name(str(pa.id))
    await db.delete(pa)
    await db.commit()
    try:
        await db.execute(text(f"DROP TABLE IF EXISTS {tname}"))
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
    return {"deleted": True, "table": tname}


@router.post("/cache/clear")
async def clear_analysis_cache(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin_user),
):
    from app.core.cache.redis_cache import cache_delete_prefix

    deleted = await cache_delete_prefix("analysis:cache:")
    return {"deleted": deleted, "ttl": _cache_ttl()}


@router.get("/cache/info")
async def cache_info(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"ttl": _cache_ttl()}
