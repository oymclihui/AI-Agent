"""高级分析接口：执行 AnalysisSpec、保存与查询分析定义。"""
from __future__ import annotations

import datetime
import decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.analysis.operators import AnalysisError, execute_spec
from app.core.analysis.spec import SpecError, normalize_spec, quote_literal, spec_hash
from app.core.auth.deps import get_current_user
from app.core.data_ask.connectors.factory import build_connector_from_source
from app.core.data_ask.govern.access import assert_data_source_access
from app.core.data_ask.govern.sql_guard import validate_select_sql
from app.db.models import AnalysisRun, AnalysisSpec, DataSource, DataSourceTable, DataSourceTableRole, MetricDimension, User
from app.db.session import get_db
from app.schemas.analysis import (
    AnalysisRunOut,
    AnalysisSpecListOut,
    AnalysisSpecOut,
    AnalysisSpecRunIn,
)

router = APIRouter(prefix="/analysis", tags=["Analysis"])

_STATUS = {"column_denied": 403, "data_source_forbidden": 403, "no_table": 422,
           "unknown_dimension": 422, "derived_failed": 422, "no_data": 422}


def _json_safe(value: Any) -> Any:
    """落库前把 Decimal / 日期转成 JSON 原生类型。"""
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


def _http_error(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", "spec_invalid")
    return HTTPException(status_code=_STATUS.get(code, 400), detail={"code": code, "message": str(exc)})


@router.post("/spec", response_model=AnalysisRunOut)
async def run_analysis_spec(
    payload: AnalysisSpecRunIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按规格执行一次分析；save=true 时同时保存为可复用定义。"""
    raw = payload.spec.model_dump()
    source = await db.get(DataSource, raw["data_source_id"])
    if not source:
        raise HTTPException(status_code=404, detail={"code": "data_source_not_found", "message": "数据源不存在"})
    await assert_data_source_access(db, source, user, require_chat=True)

    run = AnalysisRun(data_source_id=source.id, status="ok")
    db.add(run)
    try:
        result = await execute_spec(db, source, raw, user=user)
    except (SpecError, AnalysisError) as exc:
        run.status = "failed"
        run.error = str(exc)
        await db.commit()
        raise _http_error(exc) from exc

    run.status = "ok"
    run.row_count = result["row_count"]
    run.elapsed_ms = result["query"]["elapsed_ms"]
    run.result_snapshot = _json_safe({"columns": result["columns"], "rows": result["rows"][:200]})
    run.facts_json = _json_safe(result["facts"])

    if payload.save:
        spec = normalize_spec(raw)
        spec["name"] = payload.name or spec["name"]
        row = AnalysisSpec(
            data_source_id=source.id,
            owner_id=user.id,
            name=spec["name"],
            spec_json=spec,
            spec_hash=spec_hash(spec),
        )
        db.add(row)
        await db.flush()
        run.spec_id = row.id

    await db.commit()
    return AnalysisRunOut(
        run_id=run.id,
        spec_hash=result["spec_hash"],
        columns=result["columns"],
        rows=result["rows"],
        row_count=result["row_count"],
        facts=result["facts"],
        chart=result["chart"],
        query=result["query"],
        error=None,
    )


@router.get("/specs", response_model=AnalysisSpecListOut)
async def list_analysis_specs(
    data_source_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await db.get(DataSource, data_source_id)
    if not source:
        raise HTTPException(status_code=404, detail={"code": "data_source_not_found", "message": "数据源不存在"})
    await assert_data_source_access(db, source, user, require_chat=True)

    stmt = select(AnalysisSpec).where(AnalysisSpec.data_source_id == data_source_id)
    if not getattr(user, "is_admin", False):
        stmt = stmt.where(AnalysisSpec.owner_id == user.id)
    stmt = stmt.order_by(AnalysisSpec.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return AnalysisSpecListOut(items=[
        AnalysisSpecOut(
            id=r.id,
            data_source_id=r.data_source_id,
            name=r.name,
            spec=r.spec_json or {},
            spec_hash=r.spec_hash or "",
            version=r.version or 1,
            created_at=r.created_at,
        )
        for r in rows
    ])


@router.get("/specs/{spec_id}", response_model=AnalysisSpecOut)
async def get_analysis_spec(
    spec_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await db.get(AnalysisSpec, spec_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "spec_not_found", "message": "分析定义不存在"})
    if not getattr(user, "is_admin", False) and row.owner_id != user.id:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "无权访问该分析定义"})
    return AnalysisSpecOut(
        id=row.id,
        data_source_id=row.data_source_id,
        name=row.name,
        spec=row.spec_json or {},
        spec_hash=row.spec_hash or "",
        version=row.version or 1,
        created_at=row.created_at,
    )


async def _primary_table(db: AsyncSession, data_source_id: str) -> str:
    result = await db.execute(
        select(DataSourceTable.table_name)
        .where(
            DataSourceTable.data_source_id == data_source_id,
            DataSourceTable.role == DataSourceTableRole.data,
        )
        .order_by(DataSourceTable.created_at.asc())
        .limit(1)
    )
    table = result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=422, detail={"code": "no_table", "message": "该数据源未配置可查询的数据表"})
    return str(table)


async def _dimension(db: AsyncSession, data_source_id: str, field: str) -> MetricDimension:
    rows = (
        await db.execute(
            select(MetricDimension).where(MetricDimension.data_source_id == data_source_id)
        )
    ).scalars().all()
    for dim in rows:
        if field in (dim.name, dim.column_name):
            return dim
    raise HTTPException(status_code=422, detail={"code": "unknown_dimension", "message": f"未注册的维度: {field}"})


@router.get("/dimensions")
async def list_dimensions(
    data_source_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """筛选器/下钻可用的维度白名单（来自语义层物化表）。"""
    source = await db.get(DataSource, data_source_id)
    if not source:
        raise HTTPException(status_code=404, detail={"code": "data_source_not_found", "message": "数据源不存在"})
    await assert_data_source_access(db, source, user, require_chat=True)
    rows = (
        await db.execute(
            select(MetricDimension)
            .where(MetricDimension.data_source_id == data_source_id)
            .order_by(MetricDimension.hierarchy_level.asc(), MetricDimension.name.asc())
        )
    ).scalars().all()
    return {
        "items": [
            {"name": d.name, "field": d.column_name, "type": d.data_type, "level": d.hierarchy_level}
            for d in rows
        ]
    }


@router.get("/dimension-values")
async def list_dimension_values(
    data_source_id: str = Query(...),
    field: str = Query(...),
    q: str | None = Query(None, max_length=64),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """维度取值（仅限已注册维度，走只读治理）；供筛选器下拉使用。"""
    source = await db.get(DataSource, data_source_id)
    if not source:
        raise HTTPException(status_code=404, detail={"code": "data_source_not_found", "message": "数据源不存在"})
    await assert_data_source_access(db, source, user, require_chat=True)
    dim = await _dimension(db, data_source_id, field)
    col = dim.column_name
    table = await _primary_table(db, data_source_id)
    driver = str(getattr(source, "driver", "") or "")
    sql = f"SELECT DISTINCT {col} AS v FROM {table} WHERE {col} IS NOT NULL"
    if q:
        sql += f" AND {col} LIKE {quote_literal('%' + q + '%', driver)}"
    sql += f" ORDER BY {col} LIMIT {int(limit)}"
    ok, msg = validate_select_sql(sql, allowed_tables={table}, dialect=driver)
    if not ok:
        raise HTTPException(status_code=422, detail={"code": "sql_rejected", "message": msg})
    connector = build_connector_from_source(source)
    try:
        qr = await connector.execute_select(sql, limit=limit, timeout_s=30)
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "execution_failed", "message": str(exc)}) from exc
    finally:
        await connector.close()
    values = sorted(str(r[0]) for r in qr.rows if r and r[0] is not None)
    return {"field": col, "name": dim.name, "values": values}
