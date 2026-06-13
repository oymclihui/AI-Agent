"""Database admin API schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class DbPresetOut(BaseModel):
    driver: str
    label_zh: str
    label_en: str
    port: int
    db_schema: str = "public"
    ssl: str
    hint_zh: str
    hint_en: str


class DbConfigOut(BaseModel):
    driver: str
    host: str
    port: int
    user: str
    password_set: bool
    password_preview: str
    database: str
    ssl: str
    db_schema: str = "public"
    database_url_preview: str
    connected: bool = False
    connection_message: str = ""
    existing_tables: list[str] = Field(default_factory=list)
    app_table_count: int = 0


class DbConnectionTestIn(BaseModel):
    driver: str = "postgresql"
    host: str
    port: int = 5432
    user: str
    password: str = ""
    database: str
    ssl: str = "prefer"
    db_schema: str = "public"


class DbConnectionTestOut(BaseModel):
    ok: bool
    message: str


class DbConfigSaveIn(BaseModel):
    driver: str = "postgresql"
    host: str
    port: int = 5432
    user: str
    password: str | None = None
    database: str
    ssl: str = "prefer"
    db_schema: str = "public"


class DbConfigSaveOut(BaseModel):
    ok: bool
    message: str
    restart_required: bool = True


class DbInitializeIn(BaseModel):
    driver: str = "postgresql"
    host: str | None = None
    port: int | None = None
    user: str | None = None
    password: str | None = None
    database: str | None = None
    ssl: str | None = None
    db_schema: str = "public"
    seed_test_data: bool = True
    use_stored_config: bool = True


class DbInitializeOut(BaseModel):
    status: str  # created | conflict | error
    message: str
    db_schema: str = "public"
    existing_tables: list[str] = Field(default_factory=list)
    tables_created: int = 0
    seeds_run: bool = False


class DbSeedStepOut(BaseModel):
    zh: str
    en: str


class DbInitSqlPreviewOut(BaseModel):
    db_schema: str
    table_count: int
    seed_test_data: bool
    prelude_sql: list[str] = Field(default_factory=list)
    create_table_sql: list[str] = Field(default_factory=list)
    post_create_sql: list[str] = Field(default_factory=list)
    seed_steps: list[DbSeedStepOut] = Field(default_factory=list)
    full_sql: str
