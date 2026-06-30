"""Batch parse orchestration and data-source integration."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.data_ask.excel.session_cache import invalidate_excel_cache
from app.core.data_ask.excel.storage import (
    ensure_excel_folder,
    excel_folder,
    excel_input_folder,
    is_excel_template_driver,
)
from app.core.data_ask.schema.introspect import introspect_tables
from app.core.data_ask.experience.employee_factory import ensure_semantic_model
from app.core.excel_parser.exporter import Exporter
from app.core.excel_parser.parser import ExcelParser
from app.core.excel_parser.scanner import scan_excel_files
from app.db.base import generate_uuid
from app.db.models import DataSource, DataSourceTable, DataSourceTableRole, ExcelParseJob, ExcelParseTemplate
from app.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)

_RUNNING_TASKS: set[str] = set()


def template_to_parser_config(template: ExcelParseTemplate | dict) -> dict:
    if isinstance(template, ExcelParseTemplate):
        return {
            "id": template.id,
            "name": template.name,
            "type": template.type,
            "sheet_mappings": template.sheet_mappings or [],
        }
    return template


def _collect_template_columns(template: dict) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for sheet_config in template.get("sheet_mappings") or []:
        field_mapping = sheet_config.get("field_mapping") or {}
        if isinstance(field_mapping, list):
            for item in field_mapping:
                name = item.get("field_name", "")
                if name and name not in seen:
                    columns.append(name)
                    seen.add(name)
        else:
            for name in field_mapping:
                if name not in seen:
                    columns.append(name)
                    seen.add(name)
    for field in ("source_file", "file_name", "sheet_name", "load_time"):
        if field not in seen:
            columns.append(field)
    return columns


def _sanitize_records(records: list[dict]) -> list[dict]:
    for record in records:
        for key, value in list(record.items()):
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                record[key] = None
    return records


def run_batch_parse_sync(
    *,
    template: dict,
    folder_path: str,
    recursive: bool,
    output_dir: str,
    output_filename: str | None = None,
) -> dict[str, Any]:
    """Synchronous batch parse — safe to run in a thread pool."""
    parser = ExcelParser(template)
    excel_files = scan_excel_files(folder_path, recursive=recursive)
    results: list[dict] = []
    error_logs: list[dict] = []
    success_count = 0
    failed_count = 0

    for i, file_path in enumerate(excel_files):
        try:
            file_results = parser.parse(file_path)
            results.extend(file_results)
            success_count += 1
        except Exception as exc:
            failed_count += 1
            error_logs.append(
                {
                    "file": Path(file_path).name,
                    "file_path": file_path,
                    "error": str(exc),
                    "time": datetime.now(timezone.utc).isoformat(),
                }
            )

    columns = _collect_template_columns(template)
    output_file = ""
    row_count = 0

    if results:
        df = pd.DataFrame(results)
        records = _sanitize_records(df.to_dict(orient="records"))
        row_count = len(records)
        for col in df.columns:
            if col not in columns:
                columns.append(col)
        output_file = Exporter.export_excel(df, output_dir, output_filename)
    else:
        records = []

    return {
        "columns": columns,
        "data": records,
        "row_count": row_count,
        "success_count": success_count,
        "failed_count": failed_count,
        "error_logs": error_logs,
        "output_file": output_file,
        "output_filename": Path(output_file).name if output_file else "",
        "total_files": len(excel_files),
    }


def resolve_parse_folder(
    *,
    data_source_id: str | None,
    folder_path: str | None,
) -> str:
    if data_source_id:
        input_dir = excel_input_folder(data_source_id)
        if any(input_dir.iterdir()):
            return str(input_dir)
    if folder_path:
        path = Path(folder_path).resolve()
        if not path.is_dir():
            raise ValueError(f"Directory not found: {folder_path}")
        return str(path)
    if data_source_id:
        folder = excel_folder(data_source_id)
        if any(p.is_file() for p in folder.iterdir() if p.suffix.lower() in {".xlsx", ".xls", ".xlsm"}):
            return str(folder)
    raise ValueError("No Excel files found. Upload files or provide folder_path.")


async def register_parsed_table(
    db: AsyncSession,
    source: DataSource,
    output_filename: str,
) -> None:
    existing = await db.execute(
        select(DataSourceTable).where(DataSourceTable.data_source_id == source.id)
    )
    for old in existing.scalars().all():
        await db.delete(old)
    await db.flush()

    meta_list = await introspect_tables(source, [output_filename])
    meta = meta_list[0] if meta_list else {}
    db.add(
        DataSourceTable(
            id=generate_uuid(),
            data_source_id=source.id,
            table_name=output_filename,
            role=DataSourceTableRole.data,
            column_meta={"columns": meta.get("columns", []), "partition_columns": meta.get("partition_columns", [])},
            join_keys={"edges": []},
            sample_rows=meta.get("sample_rows") or [],
        )
    )
    meta_dict = dict(source.metadata_ or {})
    meta_dict["registered_tables"] = [output_filename]
    meta_dict["parse_status"] = "ready"
    meta_dict["last_output_file"] = output_filename
    source.metadata_ = meta_dict
    flag_modified(source, "metadata_")
    await ensure_semantic_model(source)
    invalidate_excel_cache(source.id)


async def execute_parse_job(job_id: str) -> None:
    if job_id in _RUNNING_TASKS:
        return
    _RUNNING_TASKS.add(job_id)

    parse_params: dict[str, Any] | None = None
    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(ExcelParseJob, job_id)
            if not job or job.status not in ("pending", "running"):
                return

            template = await db.get(ExcelParseTemplate, job.template_id)
            if not template:
                job.status = "failed"
                job.error_message = f"Template not found: {job.template_id}"
                await db.commit()
                return

            job.status = "running"
            job.progress = 0
            await db.commit()

            try:
                folder = resolve_parse_folder(
                    data_source_id=job.data_source_id,
                    folder_path=job.folder_path,
                )
            except ValueError as exc:
                job.status = "failed"
                job.error_message = str(exc)
                await db.commit()
                return

            output_dir = str(ensure_excel_folder(job.data_source_id)) if job.data_source_id else str(
                Path(folder).parent / "output"
            )
            parse_params = {
                "template": template_to_parser_config(template),
                "folder_path": folder,
                "recursive": bool(job.recursive),
                "output_dir": output_dir,
                "output_filename": job.output_filename,
                "data_source_id": job.data_source_id,
            }

        result = await asyncio.to_thread(
            run_batch_parse_sync,
            template=parse_params["template"],
            folder_path=parse_params["folder_path"],
            recursive=parse_params["recursive"],
            output_dir=parse_params["output_dir"],
            output_filename=parse_params["output_filename"],
        )

        async with AsyncSessionLocal() as db:
            job = await db.get(ExcelParseJob, job_id)
            if not job:
                return

            job.columns = result["columns"]
            job.result_preview = (result["data"] or [])[:50]
            job.row_count = result["row_count"]
            job.success_count = result["success_count"]
            job.failed_count = result["failed_count"]
            job.error_logs = result["error_logs"]
            job.output_file = result["output_filename"]
            job.progress = 100
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)

            data_source_id = job.data_source_id
            output_filename = result.get("output_filename")
            if data_source_id and output_filename:
                source = await db.get(DataSource, data_source_id)
                if source and is_excel_template_driver(str(source.driver)):
                    await register_parsed_table(db, source, output_filename)
                    meta_patch = {
                        **(source.metadata_ or {}),
                        "parse_status": "ready",
                        "last_output_file": output_filename,
                        "registered_tables": [output_filename],
                    }
                    await db.execute(
                        update(DataSource)
                        .where(DataSource.id == data_source_id)
                        .values(metadata_=meta_patch)
                    )

            await db.commit()
            logger.info(
                "excel_parse_job_completed",
                job_id=job_id,
                success=result["success_count"],
                failed=result["failed_count"],
            )
    except Exception as exc:
        logger.exception("excel_parse_job_failed", job_id=job_id)
        async with AsyncSessionLocal() as db:
            job = await db.get(ExcelParseJob, job_id)
            if job:
                job.status = "failed"
                job.error_message = str(exc)[:500]
                await db.commit()
    finally:
        _RUNNING_TASKS.discard(job_id)


async def create_parse_job(
    db: AsyncSession,
    *,
    owner_id: str | None,
    template_id: str,
    data_source_id: str | None = None,
    folder_path: str | None = None,
    recursive: bool = True,
    output_filename: str | None = None,
) -> ExcelParseJob:
    template = await db.get(ExcelParseTemplate, template_id)
    if not template:
        raise ValueError(f"Template not found: {template_id}")

    if data_source_id:
        source = await db.get(DataSource, data_source_id)
        if not source:
            raise ValueError(f"Data source not found: {data_source_id}")
        if not is_excel_template_driver(source.driver):
            raise ValueError("Data source must use excel_template driver")

    job = ExcelParseJob(
        id=generate_uuid(),
        owner_id=owner_id,
        template_id=template_id,
        data_source_id=data_source_id,
        folder_path=folder_path,
        recursive=recursive,
        output_filename=output_filename,
        status="pending",
        progress=0,
    )
    db.add(job)
    await db.flush()

    if data_source_id:
        source = await db.get(DataSource, data_source_id)
        if source:
            meta = dict(source.metadata_ or {})
            meta["parse_status"] = "running"
            meta["last_job_id"] = job.id
            source.metadata_ = meta
            flag_modified(source, "metadata_")

    await db.commit()
    await db.refresh(job)
    asyncio.create_task(execute_parse_job(job.id))
    return job


def resolve_job_output_path(job: ExcelParseJob) -> Path | None:
    if not job.output_file:
        return None
    if job.data_source_id:
        path = excel_folder(job.data_source_id) / job.output_file
        return path if path.is_file() else None
    if job.folder_path:
        path = Path(job.folder_path).resolve().parent / "output" / job.output_file
        return path if path.is_file() else None
    return None


def read_job_result_sync(job: ExcelParseJob) -> dict[str, Any]:
    path = resolve_job_output_path(job)
    if path:
        df = pd.read_excel(path, engine="openpyxl")
        records = _sanitize_records(df.to_dict(orient="records"))
        return {
            "columns": list(df.columns),
            "data": records,
            "total": len(records),
        }
    preview = job.result_preview or []
    columns = job.columns or []
    if preview and not columns:
        columns = list(preview[0].keys())
    return {"columns": columns, "data": preview, "total": len(preview)}


async def list_templates_for_user(db: AsyncSession, user_id: str | None) -> list[ExcelParseTemplate]:
    q = select(ExcelParseTemplate).order_by(ExcelParseTemplate.updated_at.desc())
    if user_id:
        q = q.where((ExcelParseTemplate.owner_id == user_id) | (ExcelParseTemplate.is_global == True))  # noqa: E712
    result = await db.execute(q)
    return list(result.scalars().all())
