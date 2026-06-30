"""Excel batch parse templates and jobs."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import get_current_user
from app.core.excel_parser.access import assert_template_edit, assert_template_use, can_edit_template
from app.core.excel_parser.exporter import Exporter
from app.core.excel_parser.service import (
    create_parse_job,
    list_templates_for_user,
    read_job_result_sync,
    resolve_job_output_path,
)
from app.core.data_ask.govern.access import assert_data_source_access, can_access_data_source
from app.db.base import generate_uuid
from app.db.models import DataSource, ExcelParseJob, ExcelParseTemplate, User
from app.db.session import get_db
from app.schemas.excel_parser import (
    ExcelParseGlobalStatsOut,
    ExcelParseJobCreate,
    ExcelParseJobListOut,
    ExcelParseJobOut,
    ExcelParseResultOut,
    ExcelParseTemplateCreate,
    ExcelParseTemplateListOut,
    ExcelParseTemplateOut,
    ExcelParseTemplateUpdate,
)

router = APIRouter(prefix="/excel-parser", tags=["ExcelParser"])


def _template_out(t: ExcelParseTemplate) -> ExcelParseTemplateOut:
    return ExcelParseTemplateOut(
        id=t.id,
        name=t.name,
        type=t.type,
        sheet_mappings=t.sheet_mappings or [],
        description=t.description,
        is_global=bool(t.is_global),
        owner_id=t.owner_id,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def _job_out(j: ExcelParseJob) -> ExcelParseJobOut:
    return ExcelParseJobOut(
        id=j.id,
        template_id=j.template_id,
        data_source_id=j.data_source_id,
        folder_path=j.folder_path,
        recursive=bool(j.recursive),
        status=j.status,
        progress=j.progress or 0,
        row_count=j.row_count or 0,
        success_count=j.success_count or 0,
        failed_count=j.failed_count or 0,
        output_file=j.output_file,
        columns=j.columns or [],
        error_message=j.error_message,
        error_logs=j.error_logs or [],
        result_preview=j.result_preview or [],
        created_at=j.created_at,
        completed_at=j.completed_at,
    )


@router.get("/templates", response_model=ExcelParseTemplateListOut)
async def list_templates(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items = [_template_out(t) for t in await list_templates_for_user(db, user.id)]
    return ExcelParseTemplateListOut(items=items)


@router.post("/templates", response_model=ExcelParseTemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: ExcelParseTemplateCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.sheet_mappings:
        raise HTTPException(status_code=400, detail="sheet_mappings required")
    tpl_id = payload.id or generate_uuid()
    existing = await db.get(ExcelParseTemplate, tpl_id)
    if existing:
        raise HTTPException(status_code=400, detail=f"Template id already exists: {tpl_id}")
    template = ExcelParseTemplate(
        id=tpl_id,
        owner_id=user.id,
        name=payload.name.strip(),
        type=payload.type.strip(),
        sheet_mappings=[m.model_dump() for m in payload.sheet_mappings],
        description=payload.description,
        is_global=bool(payload.is_global),
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return _template_out(template)


@router.get("/templates/{template_id}", response_model=ExcelParseTemplateOut)
async def get_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    template = await db.get(ExcelParseTemplate, template_id)
    await assert_template_use(template, user)
    return _template_out(template)


@router.put("/templates/{template_id}", response_model=ExcelParseTemplateOut)
async def update_template(
    template_id: str,
    payload: ExcelParseTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    template = await db.get(ExcelParseTemplate, template_id)
    await assert_template_edit(template, user)
    data = payload.model_dump(exclude_unset=True)
    if "is_global" in data and not user.is_admin and template.owner_id != user.id:
        data.pop("is_global")
    if "sheet_mappings" in data and data["sheet_mappings"] is not None:
        data["sheet_mappings"] = [m.model_dump() if hasattr(m, "model_dump") else m for m in data["sheet_mappings"]]
    for key, value in data.items():
        setattr(template, key, value)
    await db.commit()
    await db.refresh(template)
    return _template_out(template)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    template = await db.get(ExcelParseTemplate, template_id)
    await assert_template_edit(template, user)
    jobs = (
        await db.execute(select(ExcelParseJob).where(ExcelParseJob.template_id == template_id))
    ).scalars().all()
    for job in jobs:
        await db.delete(job)
    await db.delete(template)
    await db.commit()


@router.post("/jobs", response_model=ExcelParseJobOut, status_code=status.HTTP_201_CREATED)
async def start_parse_job(
    payload: ExcelParseJobCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        template = await db.get(ExcelParseTemplate, payload.template_id)
        await assert_template_use(template, user)
        if payload.data_source_id:
            source = await db.get(DataSource, payload.data_source_id)
            if not source:
                raise HTTPException(status_code=404, detail="Data source not found")
            if not await can_access_data_source(db, source, user, require_ask=True):
                raise HTTPException(status_code=403, detail="Forbidden")
        job = await create_parse_job(
            db,
            owner_id=user.id,
            template_id=payload.template_id,
            data_source_id=payload.data_source_id,
            folder_path=payload.folder_path,
            recursive=payload.recursive,
            output_filename=payload.output_filename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _job_out(job)


@router.get("/jobs/{job_id}", response_model=ExcelParseJobOut)
async def get_parse_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = await db.get(ExcelParseJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _assert_job_access_async(db, job, user)
    return _job_out(job)


@router.get("/jobs", response_model=ExcelParseJobListOut)
async def list_parse_jobs(
    data_source_id: str | None = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if data_source_id:
        source = await db.get(DataSource, data_source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Data source not found")
        if not await can_access_data_source(db, source, user, require_ask=True):
            raise HTTPException(status_code=403, detail="Forbidden")
    q = select(ExcelParseJob).order_by(ExcelParseJob.created_at.desc()).limit(max(1, min(limit, 100)))
    if data_source_id:
        q = q.where(ExcelParseJob.data_source_id == data_source_id)
    elif not user.is_admin:
        from app.core.data_ask.govern.access import list_granted_source_ids

        granted = await list_granted_source_ids(db, user.id)
        if granted:
            from sqlalchemy import or_

            q = q.where(or_(ExcelParseJob.owner_id == user.id, ExcelParseJob.data_source_id.in_(list(granted))))
        else:
            q = q.where(ExcelParseJob.owner_id == user.id)
    result = await db.execute(q)
    return ExcelParseJobListOut(items=[_job_out(j) for j in result.scalars().all()])


async def _assert_job_access_async(db: AsyncSession, job: ExcelParseJob, user: User) -> None:
    if user.is_admin:
        return
    if job.owner_id == user.id:
        return
    if job.data_source_id:
        source = await db.get(DataSource, job.data_source_id)
        if source and await can_access_data_source(db, source, user, require_ask=True):
            return
    raise HTTPException(status_code=403, detail="Access denied")


@router.get("/stats/global", response_model=ExcelParseGlobalStatsOut)
async def global_parse_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(
        func.coalesce(func.sum(ExcelParseJob.success_count), 0),
        func.coalesce(func.sum(ExcelParseJob.failed_count), 0),
        func.max(ExcelParseJob.completed_at),
    ).where(ExcelParseJob.status.in_(("completed", "failed")))
    if not user.is_admin:
        q = q.where(ExcelParseJob.owner_id == user.id)
    success, failed, last_at = (await db.execute(q)).one()
    last_parse_time = None
    if last_at:
        last_parse_time = last_at.strftime("%Y-%m-%d %H:%M:%S")
    total = int(success or 0) + int(failed or 0)
    return ExcelParseGlobalStatsOut(
        total=total,
        success=int(success or 0),
        failed=int(failed or 0),
        last_parse_time=last_parse_time,
    )


@router.get("/jobs/{job_id}/result", response_model=ExcelParseResultOut)
async def get_parse_job_result(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = await db.get(ExcelParseJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _assert_job_access_async(db, job, user)
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job not completed")
    payload = await asyncio.to_thread(read_job_result_sync, job)
    return ExcelParseResultOut(**payload)


@router.get("/jobs/{job_id}/export")
async def export_parse_job(
    job_id: str,
    format: str = Query("excel", pattern="^(excel|csv)$"),
    filename: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = await db.get(ExcelParseJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _assert_job_access_async(db, job, user)
    if job.status != "completed" or not job.output_file:
        raise HTTPException(status_code=400, detail="Job output not ready")

    source_path = resolve_job_output_path(job)
    base_name = (filename or Path(job.output_file).stem).strip() or "parsed_wide"

    if format == "excel" and source_path:
        return FileResponse(
            source_path,
            filename=f"{base_name}.xlsx" if not base_name.endswith(".xlsx") else base_name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    result = await asyncio.to_thread(read_job_result_sync, job)
    if not result["data"]:
        raise HTTPException(status_code=400, detail="No data to export")

    df = pd.DataFrame(result["data"])
    tmp_dir = Path(tempfile.gettempdir()) / "aiagnet_excel_export"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    if format == "csv":
        out_path = Exporter.export_csv(df, str(tmp_dir), base_name)
        return FileResponse(
            out_path,
            filename=Path(out_path).name,
            media_type="text/csv; charset=utf-8",
        )
    out_path = Exporter.export_excel(df, str(tmp_dir), base_name)
    return FileResponse(
        out_path,
        filename=Path(out_path).name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
