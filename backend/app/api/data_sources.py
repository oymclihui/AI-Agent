"""Data source management and data ask APIs."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth.deps import get_current_user
from app.core.data_ask.connectors.base import RelationInfo
from app.core.data_ask.excel.storage import (
    EXCEL_EXTENSIONS,
    ensure_excel_folder,
    excel_folder,
    excel_input_folder,
    folder_total_bytes,
    is_excel_driver,
    is_excel_template_driver,
    list_excel_files,
    list_excel_input_files,
    remove_excel_folder,
)
from app.core.data_ask.excel.retention import RETENTION_EPHEMERAL
from app.core.data_ask.excel.session_cache import (
    get_load_status,
    invalidate_excel_cache,
    preload_excel_source,
)
from app.config import settings
from app.core.data_ask.connectors.factory import build_connector_from_source
from app.core.data_ask.credentials import encrypt_secret
from app.core.data_ask.experience.employee_factory import (
    create_agent_for_source,
    create_employee_for_source,
    ensure_semantic_model,
    generate_agent_blueprint,
)
from app.core.data_ask.govern.access import (
    assert_data_source_access,
    can_manage_all_data_sources,
    data_source_list_filter,
    user_can_manage_data_source,
)
from app.core.auth.permissions import resolve_data_scope
from app.core.data_ask.intelligence.query_memory import save_golden_query
from app.core.data_ask.schema.drift import detect_schema_drift
from app.core.data_ask.schema.introspect import infer_join_graph, introspect_tables
from app.core.data_ask.semantic.mdl import default_semantic_model, validate_semantic_model
from app.core.data_ask.service import run_data_ask, stream_data_ask
from app.core.excel_parser.service import create_parse_job
from app.core.excel_parser.access import assert_template_use
from app.db.models import ExcelParseTemplate
from app.db.base import generate_uuid
from app.db.models import (
    Conversation,
    DataAskAuditLog,
    DataAskGoldenQuery,
    DataSource,
    DataSourceGrant,
    DataSourceStatus,
    DataSourceTable,
    DataSourceTableRole,
    User,
)
from app.db.session import get_db
from app.schemas.data_source import (
    CreateEmployeeFromSourceIn,
    CreateEmployeeFromSourceOut,
    DataAskQueryIn,
    DataAskQueryOut,
    DataAskAuditListOut,
    DataAskAuditLogOut,
    ExcelFileListOut,
    ExcelFileOut,
    ExcelLoadStatusOut,
    ExcelUploadOut,
    DataSourceCreate,
    DataSourceGrantItemIn,
    DataSourceGrantListOut,
    DataSourceGrantSetIn,
    DataSourceGrantItemOut,
    DataSourceListOut,
    DataSourceObjectType,
    DataSourceOut,
    DataSourceTableOut,
    DataSourceTablesSetIn,
    DataSourceTestIn,
    DataSourceTestOut,
    DataSourceUpdate,
    GenerateBlueprintIn,
    GenerateBlueprintOut,
    GoldenQueryIn,
    GoldenQueryListOut,
    GoldenQueryOut,
    RemoteRelationOut,
    SchemaDriftOut,
    SchemaGraphOut,
    SemanticModelUpdateIn,
)
from app.schemas.excel_parser import ExcelParseJobOut, ExcelTemplateParseIn, ExcelTemplateStatusOut

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/data-sources", tags=["DataSources"])


async def _fetch_remote_relations(
    conn,
    *,
    search: str = "",
    object_type: str | None = None,
    limit: int = 120,
) -> tuple[list[str], list[RemoteRelationOut], int, bool]:
    from app.core.data_ask.connectors.relations import DEFAULT_RELATION_LIMIT, SEARCH_RELATION_LIMIT

    cap = SEARCH_RELATION_LIMIT if search.strip() else (limit or DEFAULT_RELATION_LIMIT)
    rels: list[RelationInfo] = await conn.list_relations(
        search=search.strip(),
        object_type=object_type,
        limit=cap,
    )
    if search.strip() or object_type:
        total = len(rels)
        truncated = total >= cap
    else:
        all_rels = await conn.list_relations(search="", object_type=None, limit=10000)
        total = len(all_rels)
        truncated = total > len(rels)
    relations = [RemoteRelationOut(name=r.name, object_type=r.object_type) for r in rels]
    tables = [r.name for r in rels]
    return tables, relations, total, truncated


def _object_type_value(value) -> str:
    if hasattr(value, "value"):
        return value.value
    return str(value or "table")


def _source_out(source: DataSource, *, can_manage: bool = False) -> DataSourceOut:
    tables = [
        DataSourceTableOut(
            id=t.id,
            table_name=t.table_name,
            role=t.role.value if hasattr(t.role, "value") else str(t.role),
            object_type=_object_type_value(getattr(t, "object_type", "table")),
            column_meta=t.column_meta or {},
            join_keys=t.join_keys or {},
            sample_rows=t.sample_rows or [],
        )
        for t in (source.tables or [])
    ]
    return DataSourceOut(
        id=source.id,
        name=source.name,
        driver=source.driver,
        host=source.host,
        port=source.port,
        username=source.username,
        password_set=bool(source.password_enc),
        database=source.database,
        db_schema=source.db_schema,
        ssl=source.ssl,
        permission_rules=source.permission_rules or {},
        permission_source_id=source.permission_source_id,
        semantic_model=source.semantic_model or {},
        agent_id=source.agent_id,
        employee_id=source.employee_id,
        chat_enabled=source.chat_enabled,
        report_enabled=source.report_enabled,
        status=source.status.value if hasattr(source.status, "value") else str(source.status),
        tables=tables,
        can_manage=can_manage,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


@router.get("/", response_model=DataSourceListOut)
async def list_data_sources(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(DataSource).options(selectinload(DataSource.tables)).order_by(DataSource.updated_at.desc())
    scope = await resolve_data_scope(db, user)
    filt = await data_source_list_filter(db, user, scope)
    if filt is not None:
        q = q.where(filt)
    result = await db.execute(q)
    items = []
    for s in result.scalars().all():
        manage = await user_can_manage_data_source(db, s, user)
        items.append(_source_out(s, can_manage=manage))
    return DataSourceListOut(items=items)


@router.post("/", response_model=DataSourceOut, status_code=status.HTTP_201_CREATED)
async def create_data_source(
    payload: DataSourceCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = DataSource(
        id=generate_uuid(),
        owner_id=user.id,
        name=payload.name.strip(),
        driver=payload.driver.value,
        host=payload.host.strip(),
        port=payload.port,
        username=payload.username.strip(),
        password_enc=encrypt_secret(payload.password),
        database=payload.database.strip(),
        db_schema=payload.db_schema.strip() or "public",
        ssl=payload.ssl,
        permission_rules=payload.permission_rules.model_dump(),
        permission_source_id=payload.permission_source_id,
        semantic_model=payload.semantic_model or default_semantic_model(),
        chat_enabled=payload.chat_enabled,
        report_enabled=payload.report_enabled,
        status=DataSourceStatus.active,
    )
    db.add(source)
    await db.flush()
    if payload.driver.value in ("excel_folder", "excel_template"):
        ensure_excel_folder(source.id)
        if payload.driver.value == "excel_template":
            excel_input_folder(source.id)
        source.metadata_ = {
            **(source.metadata_ or {}),
            "excel_retention": RETENTION_EPHEMERAL,
        }
        if payload.driver.value == "excel_template":
            source.metadata_["excel_template"] = True
            source.metadata_["template_id"] = payload.template_id or ""
            source.metadata_["parse_status"] = "idle"
        source.report_enabled = False
    await db.commit()
    await db.refresh(source, ["tables"])
    return _source_out(source)


@router.get("/{source_id}", response_model=DataSourceOut)
async def get_data_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    manage = await user_can_manage_data_source(db, source, user)
    return _source_out(source, can_manage=manage)


@router.patch("/{source_id}", response_model=DataSourceOut)
async def update_data_source(
    source_id: str,
    payload: DataSourceUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    await assert_data_source_access(db, source, user, require_manage=True)
    data = payload.model_dump(exclude_unset=True)
    if "password" in data:
        pw = data.pop("password")
        if pw:
            source.password_enc = encrypt_secret(pw)
    if "permission_rules" in data and data["permission_rules"] is not None:
        pr = data.pop("permission_rules")
        source.permission_rules = pr.model_dump() if hasattr(pr, "model_dump") else pr
    for k, v in data.items():
        setattr(source, k, v)
    await db.commit()
    await db.refresh(source, ["tables"])
    return _source_out(source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_data_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    await assert_data_source_access(db, source, user, require_manage=True)
    if is_excel_driver(str(source.driver)):
        remove_excel_folder(source.id)
    await db.delete(source)
    await db.commit()


@router.post("/test", response_model=DataSourceTestOut)
async def test_connection(
    payload: DataSourceTestIn,
    user: User = Depends(get_current_user),
):
    if payload.driver.value in ("excel_folder", "excel_template"):
        msg = (
            "Excel template — create source, upload raw files to input/, run parse, then ask questions"
            if payload.driver.value == "excel_template"
            else "Excel folder — create source first, then upload files"
        )
        return DataSourceTestOut(
            ok=True,
            message=msg,
            tables=[],
            relations=[],
            total_count=0,
            truncated=False,
        )
    conn = build_connector_from_source(
        {
            "driver": payload.driver.value,
            "host": payload.host,
            "port": payload.port,
            "username": payload.username,
            "password": payload.password,
            "database": payload.database,
            "db_schema": payload.db_schema,
            "ssl": payload.ssl,
        }
    )
    try:
        ok, msg = await conn.test()
        tables: list[str] = []
        relations: list[RemoteRelationOut] = []
        if ok:
            tables, relations, total, truncated = await _fetch_remote_relations(
                conn,
                search=payload.search,
                object_type=payload.object_type,
                limit=payload.limit,
            )
        else:
            total, truncated = 0, False
        return DataSourceTestOut(
            ok=ok, message=msg, tables=tables, relations=relations,
            total_count=total, truncated=truncated,
        )
    finally:
        await conn.close()


@router.post("/{source_id}/test", response_model=DataSourceTestOut)
async def test_saved_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    conn = build_connector_from_source(source)
    try:
        ok, msg = await conn.test()
        if ok:
            tables, relations, total, truncated = await _fetch_remote_relations(conn)
        else:
            tables, relations, total, truncated = [], [], 0, False
        return DataSourceTestOut(
            ok=ok, message=msg, tables=tables, relations=relations,
            total_count=total, truncated=truncated,
        )
    finally:
        await conn.close()


@router.get("/{source_id}/tables/remote", response_model=DataSourceTestOut)
async def list_remote_tables(
    source_id: str,
    q: str = "",
    object_type: str | None = None,
    limit: int = 120,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    conn = build_connector_from_source(source)
    try:
        ok, msg = await conn.test()
        if ok:
            tables, relations, total, truncated = await _fetch_remote_relations(
                conn, search=q, object_type=object_type, limit=limit,
            )
        else:
            tables, relations, total, truncated = [], [], 0, False
        return DataSourceTestOut(
            ok=ok, message=msg, tables=tables, relations=relations,
            total_count=total, truncated=truncated,
        )
    finally:
        await conn.close()


@router.put("/{source_id}/tables", response_model=DataSourceOut)
async def set_source_tables(
    source_id: str,
    payload: DataSourceTablesSetIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    await assert_data_source_access(db, source, user, require_manage=True)
    is_excel = is_excel_driver(str(source.driver))
    perm_entries = [t for t in payload.tables if t.role == DataSourceTableRole.permission]
    if is_excel:
        if len(perm_entries) > 1:
            raise HTTPException(status_code=400, detail="Excel folder allows at most one permission file")
    elif len(perm_entries) != 1:
        raise HTTPException(status_code=400, detail="Must select exactly one permission table or view")
    if perm_entries:
        perm = perm_entries[0]
        if perm.object_type not in (DataSourceObjectType.table, DataSourceObjectType.view):
            raise HTTPException(status_code=400, detail="Permission source type must be table or view")
    data_count = sum(1 for t in payload.tables if t.role == DataSourceTableRole.data)
    if data_count < 1:
        raise HTTPException(status_code=400, detail="Must select at least one data table")

    for old in list(source.tables or []):
        await db.delete(old)
    await db.flush()

    all_names = [t.table_name for t in payload.tables]
    try:
        meta_list = await introspect_tables(source, all_names)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(
            status_code=400,
            detail="缺少 Excel 读取依赖，请联系管理员安装 xlrd（.xls）",
        ) from exc
    except Exception as exc:
        logger.exception("introspect_tables_failed", source_id=source_id)
        raise HTTPException(status_code=400, detail=f"读取文件失败: {exc}") from exc
    meta_by_name = {m["table_name"]: m for m in meta_list}
    data_names = [t.table_name for t in payload.tables if t.role == DataSourceTableRole.data]
    graph = infer_join_graph([meta_by_name[n] for n in data_names if n in meta_by_name])
    join_by: dict[str, list[dict[str, str]]] = {}
    for edge in graph.get("edges") or []:
        join_by.setdefault(edge["from"], []).append({"to": edge["to"], "on": edge.get("label") or ""})

    for t in payload.tables:
        meta = meta_by_name.get(t.table_name, {})
        join_keys = t.join_keys
        if t.role == DataSourceTableRole.data and not join_keys:
            join_keys = {"edges": join_by.get(t.table_name, [])}
        db.add(
            DataSourceTable(
                id=generate_uuid(),
                data_source_id=source.id,
                table_name=t.table_name,
                role=t.role,
                object_type=t.object_type,
                column_meta={"columns": meta.get("columns", []), "partition_columns": meta.get("partition_columns", [])},
                join_keys=join_keys,
                sample_rows=meta.get("sample_rows") or [],
            )
        )
    meta = source.metadata_ or {}
    meta["registered_tables"] = [t.table_name for t in payload.tables]
    source.metadata_ = meta
    await ensure_semantic_model(source)
    await db.commit()
    await db.refresh(source, ["tables"])
    return _source_out(source)


@router.get("/{source_id}/excel/files", response_model=ExcelFileListOut)
async def list_excel_folder_files(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    if not is_excel_driver(str(source.driver)):
        raise HTTPException(status_code=400, detail="Not an Excel folder data source")
    items = [ExcelFileOut(**item) for item in list_excel_files(source.id)]
    return ExcelFileListOut(items=items)


@router.post("/{source_id}/excel/upload", response_model=ExcelUploadOut)
async def upload_excel_files(
    source_id: str,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    await assert_data_source_access(db, source, user, require_manage=True)
    if not is_excel_driver(str(source.driver)):
        raise HTTPException(status_code=400, detail="Not an Excel folder data source")
    if is_excel_template_driver(str(source.driver)):
        folder = excel_input_folder(source.id)
    else:
        folder = ensure_excel_folder(source.id)
    uploaded: list[str] = []
    max_file = settings.DATA_ASK_EXCEL_MAX_FILE_MB * 1024 * 1024
    max_folder = settings.DATA_ASK_EXCEL_MAX_FOLDER_MB * 1024 * 1024
    folder_used = folder_total_bytes(source.id)
    for upload in files:
        name = (upload.filename or "").strip()
        if not name:
            continue
        safe = name.replace("\\", "/").split("/")[-1]
        if not safe.lower().endswith(tuple(EXCEL_EXTENSIONS)):
            raise HTTPException(status_code=400, detail=f"Unsupported file: {safe}")
        body = await upload.read()
        if len(body) > max_file:
            raise HTTPException(
                status_code=400,
                detail=f"File too large: {safe} (max {settings.DATA_ASK_EXCEL_MAX_FILE_MB}MB)",
            )
        if folder_used + len(body) > max_folder:
            raise HTTPException(
                status_code=400,
                detail=f"Folder quota exceeded (max {settings.DATA_ASK_EXCEL_MAX_FOLDER_MB}MB per data source)",
            )
        dest = folder / safe
        dest.write_bytes(body)
        folder_used += len(body)
        uploaded.append(safe)
    invalidate_excel_cache(source.id)
    if is_excel_template_driver(str(source.driver)):
        items = [ExcelFileOut(**item) for item in list_excel_input_files(source.id)]
    else:
        items = [ExcelFileOut(**item) for item in list_excel_files(source.id)]
    return ExcelUploadOut(uploaded=uploaded, items=items)


@router.post("/{source_id}/excel/preload", response_model=ExcelLoadStatusOut)
async def excel_preload(
    source_id: str,
    conversation_id: str | None = Query(None),
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    if not is_excel_driver(str(source.driver)):
        raise HTTPException(status_code=400, detail="Not an Excel data source")
    try:
        status = await preload_excel_source(source_id, force=force)
    except Exception as exc:
        status = get_load_status(source_id)
        raise HTTPException(status_code=500, detail=status.get("error") or str(exc)) from exc

    if conversation_id:
        conv = await db.get(Conversation, conversation_id)
        if conv and conv.owner_id == user.id and conv.is_active:
            meta = dict(conv.metadata_ or {})
            meta["excel_load"] = status
            conv.metadata_ = meta
            await db.commit()

    return ExcelLoadStatusOut(**status)


@router.get("/{source_id}/excel/load-status", response_model=ExcelLoadStatusOut)
async def excel_load_status(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    if not is_excel_driver(str(source.driver)):
        raise HTTPException(status_code=400, detail="Not an Excel data source")
    return ExcelLoadStatusOut(**get_load_status(source_id))


def _parse_job_out(job) -> ExcelParseJobOut:
    return ExcelParseJobOut(
        id=job.id,
        template_id=job.template_id,
        data_source_id=job.data_source_id,
        folder_path=job.folder_path,
        recursive=bool(job.recursive),
        status=job.status,
        progress=job.progress or 0,
        row_count=job.row_count or 0,
        success_count=job.success_count or 0,
        failed_count=job.failed_count or 0,
        output_file=job.output_file,
        columns=job.columns or [],
        error_message=job.error_message,
        error_logs=job.error_logs or [],
        result_preview=job.result_preview or [],
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


@router.get("/{source_id}/excel-template/status", response_model=ExcelTemplateStatusOut)
async def excel_template_status(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    if not is_excel_template_driver(str(source.driver)):
        raise HTTPException(status_code=400, detail="Not an excel_template data source")
    meta = source.metadata_ or {}
    return ExcelTemplateStatusOut(
        parse_status=str(meta.get("parse_status") or "idle"),
        template_id=meta.get("template_id") or None,
        last_job_id=meta.get("last_job_id") or None,
        last_output_file=meta.get("last_output_file") or None,
        input_file_count=len(list_excel_input_files(source.id)),
        output_file_count=len(list_excel_files(source.id)),
    )


@router.get("/{source_id}/excel-template/input/files", response_model=ExcelFileListOut)
async def list_excel_template_input_files(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    if not is_excel_template_driver(str(source.driver)):
        raise HTTPException(status_code=400, detail="Not an excel_template data source")
    return ExcelFileListOut(items=[ExcelFileOut(**item) for item in list_excel_input_files(source.id)])


@router.post("/{source_id}/excel-template/parse", response_model=ExcelParseJobOut, status_code=status.HTTP_201_CREATED)
async def start_excel_template_parse(
    source_id: str,
    payload: ExcelTemplateParseIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    await assert_data_source_access(db, source, user, require_chat=True)
    if not is_excel_template_driver(str(source.driver)):
        raise HTTPException(status_code=400, detail="Not an excel_template data source")
    meta = source.metadata_ or {}
    template_id = (payload.template_id or meta.get("template_id") or "").strip()
    if not template_id:
        raise HTTPException(status_code=400, detail="template_id required")
    template = await db.get(ExcelParseTemplate, template_id)
    await assert_template_use(template, user)
    if payload.template_id and payload.template_id != meta.get("template_id"):
        meta["template_id"] = template_id
        source.metadata_ = meta
        await db.flush()
    try:
        job = await create_parse_job(
            db,
            owner_id=user.id,
            template_id=template_id,
            data_source_id=source.id,
            folder_path=payload.folder_path,
            recursive=payload.recursive,
            output_filename=payload.output_filename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _parse_job_out(job)


@router.put("/{source_id}/semantic-model", response_model=DataSourceOut)
async def update_semantic_model(
    source_id: str,
    payload: SemanticModelUpdateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    await assert_data_source_access(db, source, user, require_manage=True)
    source.semantic_model = validate_semantic_model(payload.semantic_model)
    await db.commit()
    await db.refresh(source, ["tables"])
    return _source_out(source)


@router.get("/{source_id}/schema-drift", response_model=SchemaDriftOut)
async def schema_drift(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    drift = await detect_schema_drift(source, list(source.tables or []))
    return SchemaDriftOut(**drift)


@router.post("/{source_id}/schema/reindex", response_model=DataSourceOut)
async def reindex_schema(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    data_tables = [t for t in (source.tables or []) if t.role == DataSourceTableRole.data]
    if not data_tables:
        raise HTTPException(status_code=400, detail="No data tables registered")
    meta_list = await introspect_tables(source, [t.table_name for t in data_tables])
    meta_by = {m["table_name"]: m for m in meta_list}
    graph = infer_join_graph(meta_list)
    join_by: dict[str, list[dict[str, str]]] = {}
    for edge in graph.get("edges") or []:
        join_by.setdefault(edge["from"], []).append({"to": edge["to"], "on": edge.get("label") or ""})
    for t in data_tables:
        meta = meta_by.get(t.table_name, {})
        t.column_meta = {"columns": meta.get("columns", []), "partition_columns": meta.get("partition_columns", [])}
        t.sample_rows = meta.get("sample_rows") or []
        t.join_keys = {"edges": join_by.get(t.table_name, [])}
    await db.commit()
    await db.refresh(source, ["tables"])
    return _source_out(source)


@router.get("/{source_id}/audit-logs", response_model=DataAskAuditListOut)
async def list_audit_logs(
    source_id: str,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    from sqlalchemy import func

    total_q = await db.execute(
        select(func.count()).select_from(DataAskAuditLog).where(DataAskAuditLog.data_source_id == source.id)
    )
    total = int(total_q.scalar() or 0)
    result = await db.execute(
        select(DataAskAuditLog)
        .where(DataAskAuditLog.data_source_id == source.id)
        .order_by(DataAskAuditLog.created_at.desc())
        .offset(max(offset, 0))
        .limit(min(max(limit, 1), 200))
    )
    items = [
        DataAskAuditLogOut(
            id=r.id,
            user_id=r.user_id,
            data_source_id=r.data_source_id,
            question=r.question,
            sql_text=r.sql_text,
            row_count=r.row_count or 0,
            success=bool(r.success),
            error_message=r.error_message,
            created_at=r.created_at,
        )
        for r in result.scalars().all()
    ]
    return DataAskAuditListOut(items=items, total=total)


@router.get("/{source_id}/golden-queries", response_model=GoldenQueryListOut)
async def list_golden_queries(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_source(db, source_id, user)
    result = await db.execute(
        select(DataAskGoldenQuery)
        .where(DataAskGoldenQuery.data_source_id == source_id)
        .order_by(DataAskGoldenQuery.use_count.desc(), DataAskGoldenQuery.updated_at.desc())
        .limit(100)
    )
    items = [
        GoldenQueryOut(
            id=r.id,
            data_source_id=r.data_source_id,
            question=r.question,
            sql_text=r.sql_text,
            use_count=r.use_count or 0,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in result.scalars().all()
    ]
    return GoldenQueryListOut(items=items)


@router.post("/{source_id}/golden-queries", response_model=GoldenQueryOut, status_code=status.HTTP_201_CREATED)
async def create_golden_query(
    source_id: str,
    payload: GoldenQueryIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_source(db, source_id, user)
    row = await save_golden_query(
        db,
        data_source_id=source_id,
        question=payload.question,
        sql_text=payload.sql_text,
        user_id=user.id,
    )
    await db.commit()
    await db.refresh(row)
    return GoldenQueryOut(
        id=row.id,
        data_source_id=row.data_source_id,
        question=row.question,
        sql_text=row.sql_text,
        use_count=row.use_count or 0,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/{source_id}/schema-graph", response_model=SchemaGraphOut)
async def schema_graph(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    tables = [
        {
            "table_name": t.table_name,
            "columns": (t.column_meta or {}).get("columns") or [],
        }
        for t in source.tables
        if t.role == DataSourceTableRole.data
    ]
    graph = infer_join_graph(tables)
    return SchemaGraphOut(**graph)


@router.post("/{source_id}/blueprint", response_model=GenerateBlueprintOut)
async def generate_blueprint(
    source_id: str,
    payload: GenerateBlueprintIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    bp = await generate_agent_blueprint(db, source, nl_prompt=payload.nl_prompt)
    return GenerateBlueprintOut(blueprint=bp)


@router.post("/{source_id}/bind-agent", response_model=DataSourceOut)
async def bind_agent(
    source_id: str,
    payload: GenerateBlueprintIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    bp = await generate_agent_blueprint(db, source, nl_prompt=payload.nl_prompt)
    await create_agent_for_source(db, source, user, bp)
    await db.commit()
    await db.refresh(source, ["tables"])
    return _source_out(source)


@router.post("/{source_id}/create-employee", response_model=CreateEmployeeFromSourceOut)
async def create_employee_from_source(
    source_id: str,
    payload: CreateEmployeeFromSourceIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    bp = await generate_agent_blueprint(db, source, nl_prompt=payload.nl_prompt)
    if payload.create_agent and not source.agent_id:
        await create_agent_for_source(db, source, user, bp)
    emp, tasks = await create_employee_for_source(
        db, source, user, blueprint=bp, cron=payload.cron_expression
    )
    await db.commit()
    return CreateEmployeeFromSourceOut(
        employee_id=emp.id,
        agent_id=source.agent_id or emp.agent_id,
        tasks_created=tasks,
    )


async def _resolve_grant_user(db: AsyncSession, item: DataSourceGrantItemIn) -> User:
    if item.user_id:
        target = await db.get(User, item.user_id)
        if target:
            return target
    login = (item.login or "").strip()
    if login:
        result = await db.execute(select(User).where(User.login == login).limit(1))
        target = result.scalar_one_or_none()
        if target:
            return target
    raise HTTPException(status_code=400, detail="User not found for grant")


@router.get("/{source_id}/grants", response_model=DataSourceGrantListOut)
async def list_data_source_grants(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    if not await user_can_manage_data_source(db, source, user):
        raise HTTPException(status_code=403, detail="Forbidden")
    rows = (
        await db.execute(select(DataSourceGrant).where(DataSourceGrant.data_source_id == source_id))
    ).scalars().all()
    items: list[DataSourceGrantItemOut] = []
    for g in rows:
        u = await db.get(User, g.user_id)
        if not u:
            continue
        items.append(
            DataSourceGrantItemOut(
                id=g.id,
                user_id=g.user_id,
                login=u.login,
                display_name=u.display_name or u.login,
                can_ask=bool(g.can_ask),
                can_manage=bool(g.can_manage),
            )
        )
    return DataSourceGrantListOut(items=items)


@router.put("/{source_id}/grants", response_model=DataSourceGrantListOut)
async def set_data_source_grants(
    source_id: str,
    payload: DataSourceGrantSetIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await _get_source(db, source_id, user)
    if not await user_can_manage_data_source(db, source, user):
        raise HTTPException(status_code=403, detail="Forbidden")
    existing = (
        await db.execute(select(DataSourceGrant).where(DataSourceGrant.data_source_id == source_id))
    ).scalars().all()
    for row in existing:
        await db.delete(row)
    await db.flush()
    seen: set[str] = set()
    for item in payload.grants:
        target = await _resolve_grant_user(db, item)
        if target.id == user.id or target.id in seen:
            continue
        seen.add(target.id)
        db.add(
            DataSourceGrant(
                id=generate_uuid(),
                data_source_id=source_id,
                user_id=target.id,
                can_ask=item.can_ask,
                can_manage=item.can_manage,
            )
        )
    await db.commit()
    return await list_data_source_grants(source_id, db, user)


async def _get_source(db: AsyncSession, source_id: str, user: User) -> DataSource:
    result = await db.execute(
        select(DataSource).options(selectinload(DataSource.tables)).where(DataSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")
    await assert_data_source_access(db, source, user)
    return source


# ── Data Ask query (also mounted at /data-ask for convenience) ──

ask_router = APIRouter(prefix="/data-ask", tags=["DataAsk"])


@ask_router.post("/query", response_model=DataAskQueryOut)
async def data_ask_query(
    payload: DataAskQueryIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await db.get(DataSource, payload.data_source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")
    await assert_data_source_access(db, source, user, require_chat=True)

    if payload.stream and payload.execute:
        async def sse():
            try:
                async for line in stream_data_ask(
                    db,
                    data_source_id=payload.data_source_id,
                    question=payload.question,
                    user=user,
                    sql_override=payload.sql_override,
                    llm_provider=payload.llm_provider,
                    llm_model=payload.llm_model,
                    execute=True,
                ):
                    yield f"data: {line.strip()}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'event': 'error', 'error': str(exc)}, ensure_ascii=False)}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream")

    try:
        result = await run_data_ask(
            db,
            data_source_id=payload.data_source_id,
            question=payload.question,
            user=user,
            sql_override=payload.sql_override,
            llm_provider=payload.llm_provider,
            llm_model=payload.llm_model,
            execute=payload.execute,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("data_ask_query_failed")
        raise HTTPException(status_code=500, detail=str(exc)[:500]) from exc
    return DataAskQueryOut(**result)
