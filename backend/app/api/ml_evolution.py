"""ML Evolution API - 模型进化管理（阶段四）

4 个端点：
- GET  /ml-evolution/models          各数据源现役模型版本、指标、历史版本列表
- GET  /ml-evolution/logs            训练日志（前端进化曲线数据源）
- POST /ml-evolution/retrain         手动触发全量重训（慢进化·网格搜索）
- POST /ml-evolution/rollback/{mid}  一键回滚到指定历史版本
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_user
from app.core.data_ask.ml_evolution import registry
from app.db.models import DataSource, User
from app.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/ml-evolution", tags=["MLEvolution"])


# ────────────────────── GET /models ──────────────────────

@router.get("/models")
async def list_models(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """各数据源现役模型版本、指标、历史版本列表"""
    models = await registry.list_all_models()

    # 关联数据源名称
    ds_ids = {m["data_source_id"] for m in models}
    ds_names: dict[str, str] = {}
    if ds_ids:
        res = await db.execute(
            select(DataSource.id, DataSource.name).where(DataSource.id.in_(list(ds_ids)))
        )
        for row in res:
            ds_names[str(row[0])] = row[1]

    for m in models:
        m["data_source_name"] = ds_names.get(m["data_source_id"], m["data_source_id"])
    return {"items": models}


# ────────────────────── GET /logs ──────────────────────

@router.get("/logs")
async def list_logs(
    data_source_id: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """训练日志（进化曲线数据源）"""
    logs = await registry.get_logs(data_source_id=data_source_id, limit=limit)
    return {"items": logs}


# ────────────────────── POST /retrain ──────────────────────

class RetrainIn(BaseModel):
    data_source_id: str
    table_name: str | None = None


@router.post("/retrain")
async def trigger_retrain(
    payload: RetrainIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """手动触发全量重训（慢进化）- 网格搜索 LSTM + CNN 常规进化

    从数据源拉取全表数据（最多5000行），传入 Celery 后台任务执行网格搜索。
    """
    from app.core.data_ask.connectors.factory import build_connector_from_source

    # 获取数据源
    res = await db.execute(
        select(DataSource).where(DataSource.id == payload.data_source_id)
    )
    source = res.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="数据源不存在")

    # 连接并取数
    conn = build_connector_from_source(source)
    try:
        if payload.table_name:
            table = payload.table_name
        else:
            tables = await conn.list_tables()
            if not tables:
                raise HTTPException(status_code=400, detail="数据源无可用表")
            table = tables[0]

        result = await conn.execute_select(
            f"SELECT * FROM {table}", limit=5000, timeout_s=60
        )
    finally:
        await conn.close()

    if not result.rows or len(result.rows) < 60:
        return JSONResponse(
            status_code=200,
            content={
                "triggered": False,
                "reason": f"数据量不足（{len(result.rows)} 行 < 60 行），未触发网格搜索",
                "table": table,
                "row_count": len(result.rows),
            },
        )

    # Celery 异步执行网格搜索
    from app.core.data_ask.ml_evolution.tasks import nightly_retrain
    from app.core.data_ask.utils.json_safe import json_safe_value

    _rows = [
        [json_safe_value(v) for v in r] if isinstance(r, (list, tuple)) else json_safe_value(r)
        for r in result.rows[:5000]
    ]
    nightly_retrain.delay(
        data_source_id=str(payload.data_source_id),
        columns=[str(c) for c in result.columns],
        rows=_rows,
        question=f"手动全量重训 table={table}",
    )

    return {
        "triggered": True,
        "table": table,
        "row_count": len(result.rows),
        "message": "网格搜索已在后台启动，请稍后查看训练日志",
    }


# ────────────────────── POST /rollback/{model_id} ──────────────────────

@router.post("/rollback/{model_id}")
async def rollback_model(
    model_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """一键回滚到指定历史版本

    registry.promote() 会将指定版本设为 production，同类型其他版本自动转 retired。
    """
    model = await registry.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"模型 {model_id} 不存在")

    result = await registry.promote(model_id)
    return {
        "rolled_back": True,
        "model": result,
        "message": f"已回滚到 {result['model_type']} v{result['version']}",
    }
