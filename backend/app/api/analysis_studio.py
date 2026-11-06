"""一句话分析工作台 API：模板管理 + 一句话运行。"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_admin_user, get_current_user
from app.core.data_ask.studio_core import list_templates, run_analysis_studio
from app.core.data_ask.studio_models import AnalysisTemplate
from app.db.models import DataSource, User
from app.db.session import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/analysis-studio", tags=["AnalysisStudio"])


def _tpl_out(row: AnalysisTemplate) -> dict[str, Any]:
    return {
        "id": row.id,
        "data_source_id": row.data_source_id,
        "name": row.name,
        "keywords": row.keywords or [],
        "sections": row.sections or [],
        "enabled": bool(row.enabled),
        "sort_order": row.sort_order or 0,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


class SectionIn(BaseModel):
    title: str = ""
    question: str = ""
    chart: str = "auto"
    role: str = "auto"  # auto / kpi / detail；auto 首节自动 kpi


class TemplateIn(BaseModel):
    data_source_id: str
    name: str = ""
    keywords: list[str] = Field(default_factory=list)
    sections: list[SectionIn] = Field(default_factory=list)
    enabled: bool = True
    sort_order: int = 0


class TemplateUpdate(BaseModel):
    name: str | None = None
    keywords: list[str] | None = None
    sections: list[SectionIn] | None = None
    enabled: bool | None = None
    sort_order: int | None = None


class RunIn(BaseModel):
    data_source_id: str
    question: str
    template_id: str | None = None


@router.get("/presets")
async def presets(
    data_source_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """供界面做 chips：语义模型里的指标/维度 + 常用问法。"""
    src = await db.get(DataSource, data_source_id)
    if not src:
        raise HTTPException(status_code=404, detail="数据源不存在")
    sm = src.semantic_model if isinstance(src.semantic_model, dict) else {}
    metrics = [str(m.get("name") or "").strip() for m in (sm.get("metrics") or []) if isinstance(m, dict)]
    dims = [str(d.get("name") or "").strip() for d in (sm.get("dimensions") or []) if isinstance(d, dict)]
    metrics = [m for m in metrics if m][:20]
    dims = [d for d in dims if d][:15]
    samples = [
        f"按{dims[0]}看{metrics[0]}" if dims and metrics else "",
        "分析最近一周的销售、毛利和客流趋势",
        "按门店对比销售额、毛利额和客单价",
        "本月销售情况总体分析",
    ]
    return {"metrics": metrics, "dimensions": dims, "samples": [s for s in samples if s]}


@router.get("/templates")
async def get_templates(
    data_source_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    rows = await list_templates(db, data_source_id)
    return {"items": [_tpl_out(r) for r in rows]}


@router.post("/templates", status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    if not body.sections:
        raise HTTPException(status_code=400, detail="至少需要一个分析节")
    row = AnalysisTemplate(
        data_source_id=body.data_source_id,
        name=body.name or (body.keywords[0] if body.keywords else "未命名模板"),
        keywords=body.keywords,
        sections=[s.model_dump() for s in body.sections],
        enabled=body.enabled,
        sort_order=body.sort_order,
        created_by=admin.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _tpl_out(row)


@router.put("/templates/{template_id}")
async def update_template(
    template_id: str,
    body: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    row = await db.get(AnalysisTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="模板不存在")
    if body.name is not None:
        row.name = body.name
    if body.keywords is not None:
        row.keywords = body.keywords
    if body.sections is not None:
        row.sections = [s.model_dump() for s in body.sections]
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.sort_order is not None:
        row.sort_order = body.sort_order
    await db.commit()
    await db.refresh(row)
    return _tpl_out(row)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user),
) -> None:
    row = await db.get(AnalysisTemplate, template_id)
    if not row:
        raise HTTPException(status_code=404, detail="模板不存在")
    await db.delete(row)
    await db.commit()


@router.post("/run")
async def run(
    body: RunIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if not (body.question or "").strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    src = await db.get(DataSource, body.data_source_id)
    if not src:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return await run_analysis_studio(
        db,
        data_source_id=body.data_source_id,
        question=body.question.strip(),
        user=user,
        template_id=body.template_id,
    )
