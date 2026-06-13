"""First-run setup API schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.database import DbConnectionTestIn, DbInitializeIn, DbPresetOut


class SetupStatusOut(BaseModel):
    setup_required: bool
    setup_token_required: bool = False
    db_connected: bool
    connection_message: str = ""
    has_users: bool
    user_count: int = 0
    default_admin_login: str
    db_driver: str = ""
    db_host: str = ""
    db_port: int = 5432
    db_user: str = ""
    db_name: str = ""
    db_schema: str = "public"


class SetupInitializeOut(BaseModel):
    status: str
    message: str
    admin_login: str = ""
    admin_password: str = ""
    db_schema: str = "public"
    tables_created: int = 0
    seeds_run: bool = False
    restart_required: bool = True
    existing_tables: list[str] = Field(default_factory=list)
