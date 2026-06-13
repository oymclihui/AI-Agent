"""First-run setup — configure database and create admin before login."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Header, HTTPException

from app.config import settings
from app.core.database.env_config import save_db_config, validate_schema_name
from app.core.database.provisioning import DB_PRESETS, initialize_database, test_connection
from app.core.setup.state import setup_status_snapshot
from app.core.setup.token import assert_setup_token
from app.schemas.database import DbConnectionTestIn, DbConnectionTestOut, DbInitializeIn, DbPresetOut
from app.schemas.setup import SetupInitializeOut, SetupStatusOut

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/setup", tags=["Setup"])


async def _assert_setup_allowed() -> None:
    snap = await setup_status_snapshot()
    if not snap["setup_required"]:
        raise HTTPException(
            status_code=403,
            detail="Setup already completed. Sign in with your admin account.",
        )


@router.get("/status", response_model=SetupStatusOut)
async def setup_status():
    snap = await setup_status_snapshot()
    return SetupStatusOut(**snap)


@router.get("/presets", response_model=list[DbPresetOut])
async def setup_presets(x_setup_token: str | None = Header(None, alias="X-Setup-Token")):
    await _assert_setup_allowed()
    assert_setup_token(x_setup_token)
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


@router.post("/test", response_model=DbConnectionTestOut)
async def setup_test_connection(
    body: DbConnectionTestIn,
    x_setup_token: str | None = Header(None, alias="X-Setup-Token"),
):
    await _assert_setup_allowed()
    assert_setup_token(x_setup_token)
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


@router.post("/initialize", response_model=SetupInitializeOut)
async def setup_initialize(
    body: DbInitializeIn,
    x_setup_token: str | None = Header(None, alias="X-Setup-Token"),
):
    await _assert_setup_allowed()
    assert_setup_token(x_setup_token)

    if not body.host or not body.user or not body.database:
        raise HTTPException(status_code=400, detail="host, user, and database are required")
    if not body.password:
        raise HTTPException(status_code=400, detail="Database password is required")

    try:
        schema = validate_schema_name(body.db_schema or "public")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        save_db_config(
            driver=body.driver,
            host=body.host,
            port=body.port or 5432,
            user=body.user,
            password=body.password,
            database=body.database,
            ssl=body.ssl or "prefer",
            schema=schema,
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write .env: {exc}") from exc

    result = await initialize_database(
        driver=body.driver,
        host=body.host,
        port=int(body.port or 5432),
        user=body.user,
        password=str(body.password),
        database=body.database,
        ssl=body.ssl or "prefer",
        schema=schema,
        seed_test_data=body.seed_test_data,
    )

    if result.status == "conflict":
        return SetupInitializeOut(
            status="conflict",
            message=result.message,
            db_schema=result.schema,
            existing_tables=result.existing_tables,
            restart_required=False,
        )
    if result.status == "error":
        raise HTTPException(status_code=502, detail=result.message)

    logger.info("first_run_setup_complete", schema=result.schema, seeds=result.seeds_run)
    return SetupInitializeOut(
        status="created",
        message=result.message + " 请关闭并重新启动应用，然后使用下方账号登录。",
        admin_login=settings.DEFAULT_ADMIN_EMPLOYEE_NO,
        admin_password=settings.DEFAULT_ADMIN_PASSWORD if result.seeds_run else "",
        db_schema=result.schema,
        tables_created=result.tables_created,
        seeds_run=result.seeds_run,
        restart_required=True,
    )
