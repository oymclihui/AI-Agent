"""
ML 进化引擎 · 模型注册表（阶段二修订：data_source_id 为字符串UUID；支持独立 session 工厂）

- 模型仓库文件：/app/models/{data_source_id}/{model_type}_v{version}.pt（宿主机卷挂载，容器重建不丢）
- 版本与训练日志：PostgreSQL ml_model_registry / ml_training_logs（ORM 定义在 app/db/models.py）
- set_session_factory: Celery 任务传入 NullPool 工厂（跨事件循环安全）；FastAPI 进程用全局默认
- 本模块不依赖 torch
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update

from app.db.models import MLModelRegistry, MLTrainingLog
from app.db.session import AsyncSessionLocal

# 模型文件根目录（容器内），对应宿主机 /opt/AI-Agent/models
MODEL_DIR = os.environ.get("ML_MODEL_DIR", "/app/models")

_SESSION_FACTORY = None


def set_session_factory(factory) -> None:
    """Celery 等独立事件循环环境注入 NullPool session 工厂"""
    global _SESSION_FACTORY
    _SESSION_FACTORY = factory


def _sf():
    return _SESSION_FACTORY or AsyncSessionLocal


def model_file_path(data_source_id: str, model_type: str, version: int) -> str:
    """生成模型文件绝对路径（目录自动创建）"""
    d = os.path.join(MODEL_DIR, str(data_source_id))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{model_type}_v{version}.pt")


def _model_to_dict(row: MLModelRegistry) -> Dict[str, Any]:
    return {
        "id": row.id,
        "data_source_id": row.data_source_id,
        "model_type": row.model_type,
        "version": row.version,
        "file_path": row.file_path,
        "metrics": row.metrics,
        "status": row.status,
        "trained_rows": row.trained_rows,
        "created_at": str(row.created_at) if row.created_at else None,
    }


def _log_to_dict(row: MLTrainingLog) -> Dict[str, Any]:
    return {
        "id": row.id,
        "model_id": row.model_id,
        "data_source_id": row.data_source_id,
        "trigger_query": row.trigger_query,
        "sample_rows": row.sample_rows,
        "val_mae": row.val_mae,
        "val_r2": row.val_r2,
        "promoted": row.promoted,
        "duration_ms": row.duration_ms,
        "note": row.note,
        "created_at": str(row.created_at) if row.created_at else None,
    }


async def get_production(data_source_id: str, model_type: str) -> Optional[Dict[str, Any]]:
    """当前现役（production）模型；无则返回 None"""
    async with _sf()() as db:
        res = await db.execute(
            select(MLModelRegistry)
            .where(
                MLModelRegistry.data_source_id == str(data_source_id),
                MLModelRegistry.model_type == model_type,
                MLModelRegistry.status == "production",
            )
            .order_by(MLModelRegistry.version.desc())
            .limit(1)
        )
        row = res.scalar_one_or_none()
        return _model_to_dict(row) if row else None


async def next_version(data_source_id: str, model_type: str) -> int:
    """下一个版本号（从 v1 开始）"""
    async with _sf()() as db:
        res = await db.execute(
            select(MLModelRegistry.version)
            .where(
                MLModelRegistry.data_source_id == str(data_source_id),
                MLModelRegistry.model_type == model_type,
            )
            .order_by(MLModelRegistry.version.desc())
            .limit(1)
        )
        cur = res.scalar_one_or_none()
        return (cur or 0) + 1


async def save_new_version(
    data_source_id: str,
    model_type: str,
    metrics: Optional[Dict[str, Any]] = None,
    trained_rows: Optional[int] = None,
    file_path: Optional[str] = None,
) -> Dict[str, Any]:
    """保存新版本（candidate 状态）；调用方负责把模型权重写入返回的 file_path"""
    version = await next_version(data_source_id, model_type)
    fp = file_path or model_file_path(str(data_source_id), model_type, version)
    async with _sf()() as db:
        row = MLModelRegistry(
            data_source_id=str(data_source_id),
            model_type=model_type,
            version=version,
            file_path=fp,
            metrics=metrics,
            status="candidate",
            trained_rows=trained_rows,
        )
        db.add(row)
        await db.commit()
        return {
            "id": row.id,
            "data_source_id": str(data_source_id),
            "model_type": model_type,
            "version": version,
            "file_path": fp,
            "metrics": metrics,
            "status": "candidate",
            "trained_rows": trained_rows,
        }


async def promote(model_id: int) -> Dict[str, Any]:
    """晋升指定版本为 production，同类型其余版本全部转 retired（择优上线与一键回滚共用此入口）"""
    async with _sf()() as db:
        res = await db.execute(select(MLModelRegistry).where(MLModelRegistry.id == model_id))
        row = res.scalar_one_or_none()
        if row is None:
            raise ValueError(f"model_id={model_id} not found")
        await db.execute(
            update(MLModelRegistry)
            .where(
                MLModelRegistry.data_source_id == row.data_source_id,
                MLModelRegistry.model_type == row.model_type,
            )
            .execution_options(synchronize_session=False)
            .values(status="retired")
        )
        row.status = "production"
        await db.commit()
        return _model_to_dict(row)


async def log_training(
    data_source_id: str,
    model_id: Optional[int] = None,
    trigger_query: Optional[str] = None,
    sample_rows: Optional[int] = None,
    val_mae: Optional[float] = None,
    val_r2: Optional[float] = None,
    promoted: bool = False,
    duration_ms: Optional[int] = None,
    note: Optional[str] = None,
) -> int:
    """训练留痕：进化曲线数据源"""
    async with _sf()() as db:
        row = MLTrainingLog(
            data_source_id=str(data_source_id),
            model_id=model_id,
            trigger_query=(trigger_query or "")[:200],
            sample_rows=sample_rows,
            val_mae=val_mae,
            val_r2=val_r2,
            promoted=bool(promoted),
            duration_ms=duration_ms,
            note=note,
        )
        db.add(row)
        await db.commit()
        return row.id


async def log_skipped(data_source_id: str, trigger_query: Optional[str], note: str) -> int:
    """未触发训练（如数据量不足）也留痕，保证"没进化"可解释"""
    return await log_training(data_source_id, trigger_query=trigger_query, promoted=False, note=note)


async def get_logs(data_source_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """训练日志（倒序）；进化曲线前端可按 created_at 正序绘制"""
    async with _sf()() as db:
        q = select(MLTrainingLog)
        if data_source_id is not None:
            q = q.where(MLTrainingLog.data_source_id == str(data_source_id))
        q = q.order_by(MLTrainingLog.id.desc()).limit(limit)
        res = await db.execute(q)
        return [_log_to_dict(r) for r in res.scalars()]


async def list_versions(
    data_source_id: str, model_type: Optional[str] = None, limit: int = 50
) -> List[Dict[str, Any]]:
    async with _sf()() as db:
        q = select(MLModelRegistry).where(MLModelRegistry.data_source_id == str(data_source_id))
        if model_type:
            q = q.where(MLModelRegistry.model_type == model_type)
        q = q.order_by(MLModelRegistry.id.desc()).limit(limit)
        res = await db.execute(q)
        return [_model_to_dict(r) for r in res.scalars()]


async def get_model(model_id: int) -> Optional[Dict[str, Any]]:
    async with _sf()() as db:
        res = await db.execute(select(MLModelRegistry).where(MLModelRegistry.id == model_id))
        row = res.scalar_one_or_none()
        return _model_to_dict(row) if row else None


async def list_all_models() -> List[Dict[str, Any]]:
    """列出所有有模型记录的数据源及其版本信息（供 GET /ml-evolution/models）

    返回结构：[{data_source_id, production: {lstm: {}, cnn: {}}, versions: [...]}]
    """
    from collections import OrderedDict

    async with _sf()() as db:
        res = await db.execute(
            select(MLModelRegistry)
            .order_by(
                MLModelRegistry.data_source_id,
                MLModelRegistry.model_type,
                MLModelRegistry.version.desc(),
            )
        )
        all_rows = res.scalars().all()

    grouped: "OrderedDict[str, list]" = OrderedDict()
    for row in all_rows:
        ds = row.data_source_id
        if ds not in grouped:
            grouped[ds] = []
        grouped[ds].append(_model_to_dict(row))

    result = []
    for ds_id, models in grouped.items():
        production: Dict[str, Any] = {}
        for m in models:
            if m["status"] == "production":
                production[m["model_type"]] = m
        result.append({
            "data_source_id": ds_id,
            "production": production,
            "versions": models,
        })
    return result
