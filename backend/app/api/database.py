"""Database configuration — admin status, test, save, and safe initialize."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth.deps import get_current_user
from app.core.auth.permissions import assert_permission, resolve_data_scope
from app.core.database.env_config import current_db_config, save_db_config, validate_schema_name
from app.core.database.provisioning import (
    DB_PRESETS,
    app_table_names,
    build_init_sql_preview,
    initialize_database,
    list_existing_app_tables,
    test_connection,
)
from app.db.models import User
from app.db.session import engine, get_db
from app.schemas.database import (
    DbConfigOut,
    DbConfigSaveIn,
    DbConfigSaveOut,
    DbConnectionTestIn,
    DbConnectionTestOut,
    DbInitializeIn,
    DbInitializeOut,
    DbInitSqlPreviewOut,
    DbPresetOut,
    DbSeedStepOut,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/database", tags=["Database"])


async def _require_org_admin_async(user: User, db: AsyncSession) -> None:
    scope = await resolve_data_scope(db, user)
    assert_permission(scope, "org:manage")


@router.get("/admin/presets", response_model=list[DbPresetOut])
async def database_presets(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_admin_async(user, db)
    return [
        DbPresetOut(
            driver=p["driver"],
            label_zh=p["label_zh"],
            label_en=p["label_en"],
            port=p["port"],
            db_schema=p["schema"],
            ssl=p["ssl"],
            hint_zh=p["hint_zh"],
            hint_en=p["hint_en"],
        )
        for p in DB_PRESETS.values()
    ]


@router.get("/admin/status", response_model=DbConfigOut)
async def database_admin_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_admin_async(user, db)
    cfg = current_db_config()
    connected = False
    message = ""
    existing: list[str] = []

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        connected = True
        message = "Connected"
        existing = await list_existing_app_tables(engine, cfg["db_schema"])
    except Exception as exc:
        message = str(exc)[:300]

    return DbConfigOut(
        **cfg,
        connected=connected,
        connection_message=message,
        existing_tables=existing,
        app_table_count=len(app_table_names()),
    )


@router.post("/admin/test", response_model=DbConnectionTestOut)
async def database_test_connection(
    body: DbConnectionTestIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_admin_async(user, db)
    try:
        validate_schema_name(body.db_schema)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    ok, message = await test_connection(
        driver=body.driver,
        host=body.host,
        port=body.port,
        user=body.user,
        password=body.password,
        database=body.database,
        ssl=body.ssl,
        schema=body.db_schema,
    )
    return DbConnectionTestOut(ok=ok, message=message)


@router.get("/admin/init-sql-preview", response_model=DbInitSqlPreviewOut)
async def database_init_sql_preview(
    db_schema: str = "public",
    seed_test_data: bool = True,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_admin_async(user, db)
    try:
        schema = validate_schema_name(db_schema)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    preview = build_init_sql_preview(schema=schema, seed_test_data=seed_test_data)
    return DbInitSqlPreviewOut(
        db_schema=preview["schema"],
        table_count=preview["table_count"],
        seed_test_data=preview["seed_test_data"],
        prelude_sql=preview["prelude_sql"],
        create_table_sql=preview["create_table_sql"],
        post_create_sql=preview["post_create_sql"],
        seed_steps=[DbSeedStepOut(**s) for s in preview["seed_steps"]],
        full_sql=preview["full_sql"],
    )


@router.post("/admin/config", response_model=DbConfigSaveOut)
async def database_save_config(
    body: DbConfigSaveIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_admin_async(user, db)
    try:
        schema = validate_schema_name(body.db_schema)
        save_db_config(
            driver=body.driver,
            host=body.host,
            port=body.port,
            user=body.user,
            password=body.password,
            database=body.database,
            ssl=body.ssl,
            schema=schema,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write .env: {exc}") from exc

    return DbConfigSaveOut(
        ok=True,
        message="Database settings saved to backend/.env. Restart the backend to apply.",
        restart_required=True,
    )


def _resolve_init_params(body: DbInitializeIn) -> dict:
    stored = current_db_config()
    if body.use_stored_config:
        return {
            "driver": body.driver or stored["driver"],
            "host": body.host or stored["host"],
            "port": body.port or stored["port"],
            "user": body.user or stored["user"],
            "password": body.password if body.password is not None else "",
            "database": body.database or stored["database"],
            "ssl": body.ssl or stored["ssl"],
            "schema": body.db_schema or stored["db_schema"],
        }
    if not all([body.host, body.user, body.database]):
        raise HTTPException(status_code=400, detail="host, user, and database are required")
    return {
        "driver": body.driver,
        "host": body.host or "",
        "port": body.port or 5432,
        "user": body.user or "",
        "password": body.password or "",
        "database": body.database or "",
        "ssl": body.ssl or "prefer",
        "schema": body.db_schema or "public",
    }


@router.post("/admin/initialize", response_model=DbInitializeOut)
async def database_initialize(
    body: DbInitializeIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_org_admin_async(user, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Only platform admin can initialize database tables")

    params = _resolve_init_params(body)
    if not params["password"] and not current_db_config()["password_set"]:
        raise HTTPException(status_code=400, detail="Database password is required")

    if not params["password"]:
        from app.core.database.env_config import parse_database_url

        if settings.DB_HOST:
            params["password"] = settings.DB_PASSWORD
        else:
            params["password"] = parse_database_url(settings.DATABASE_URL)["password"]  # type: ignore[assignment]

    try:
        validate_schema_name(params["schema"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = await initialize_database(
        driver=params["driver"],
        host=params["host"],
        port=int(params["port"]),
        user=params["user"],
        password=str(params["password"]),
        database=params["database"],
        ssl=params["ssl"],
        schema=params["schema"],
        seed_test_data=body.seed_test_data,
    )

    if result.status == "conflict":
        return DbInitializeOut(
            status="conflict",
            message=result.message,
            db_schema=result.schema,
            existing_tables=result.existing_tables,
        )
    if result.status == "error":
        raise HTTPException(status_code=502, detail=result.message)

    return DbInitializeOut(
        status="created",
        message=result.message,
        db_schema=result.schema,
        tables_created=result.tables_created,
        seeds_run=result.seeds_run,
    )
