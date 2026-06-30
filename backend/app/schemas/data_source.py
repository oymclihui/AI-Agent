from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class DataSourceDriver(str, Enum):
    postgresql = "postgresql"
    vastbase = "vastbase"
    mysql = "mysql"
    hive = "hive"
    doris = "doris"
    hana = "hana"
    excel_folder = "excel_folder"
    excel_template = "excel_template"


class DataSourceTableRole(str, Enum):
    data = "data"
    permission = "permission"


class DataSourceObjectType(str, Enum):
    table = "table"
    view = "view"


class PermissionRulesIn(BaseModel):
    user_column: str = "user_id"
    scope_column: str = "country_code"
    data_column: str = "country_code"


class DataSourceTestIn(BaseModel):
    driver: DataSourceDriver = DataSourceDriver.postgresql
    host: str
    port: int = 5432
    username: str
    password: str = ""
    database: str
    db_schema: str = "public"
    ssl: str = "prefer"
    search: str = ""
    object_type: Optional[str] = None
    limit: int = 120


class DataSourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    driver: DataSourceDriver = DataSourceDriver.postgresql
    host: str = "127.0.0.1"
    port: int = 5432
    username: str = "user"
    password: str = ""
    database: str = "db"
    db_schema: str = "public"
    ssl: str = "prefer"
    permission_rules: PermissionRulesIn = Field(default_factory=PermissionRulesIn)
    permission_source_id: Optional[str] = None
    semantic_model: dict[str, Any] = Field(default_factory=dict)
    chat_enabled: bool = True
    report_enabled: bool = True
    template_id: Optional[str] = None

    @model_validator(mode="after")
    def excel_defaults(self) -> "DataSourceCreate":
        if self.driver in (DataSourceDriver.excel_folder, DataSourceDriver.excel_template):
            self.host = self.host or "local"
            self.username = self.username or "-"
            self.password = self.password or ""
            self.database = self.database or self.name
            self.port = 0
        return self


class DataSourceUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    database: Optional[str] = None
    db_schema: Optional[str] = None
    ssl: Optional[str] = None
    permission_rules: Optional[PermissionRulesIn] = None
    permission_source_id: Optional[str] = None
    semantic_model: Optional[dict[str, Any]] = None
    agent_id: Optional[str] = None
    chat_enabled: Optional[bool] = None
    report_enabled: Optional[bool] = None
    status: Optional[str] = None


class DataSourceTableIn(BaseModel):
    table_name: str
    role: DataSourceTableRole = DataSourceTableRole.data
    object_type: DataSourceObjectType = DataSourceObjectType.table
    join_keys: dict[str, Any] = Field(default_factory=dict)


class DataSourceTablesSetIn(BaseModel):
    tables: list[DataSourceTableIn]


class DataSourceTableOut(BaseModel):
    id: str
    table_name: str
    role: str
    object_type: str = "table"
    column_meta: dict[str, Any] = Field(default_factory=dict)
    join_keys: dict[str, Any] = Field(default_factory=dict)
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)


class DataSourceOut(BaseModel):
    id: str
    name: str
    driver: str
    host: str
    port: int
    username: str
    password_set: bool
    database: str
    db_schema: str
    ssl: str
    permission_rules: dict[str, Any] = Field(default_factory=dict)
    permission_source_id: Optional[str] = None
    semantic_model: dict[str, Any] = Field(default_factory=dict)
    agent_id: Optional[str] = None
    employee_id: Optional[str] = None
    chat_enabled: bool = True
    report_enabled: bool = True
    status: str
    tables: list[DataSourceTableOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class DataSourceListOut(BaseModel):
    items: list[DataSourceOut]


class RemoteRelationOut(BaseModel):
    name: str
    object_type: str


class DataSourceTestOut(BaseModel):
    ok: bool
    message: str
    tables: list[str] = Field(default_factory=list)
    relations: list[RemoteRelationOut] = Field(default_factory=list)
    total_count: int = 0
    truncated: bool = False


class SchemaGraphOut(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class DataAskQueryIn(BaseModel):
    data_source_id: str
    question: str = Field(..., min_length=1)
    sql_override: Optional[str] = None
    stream: bool = False
    execute: bool = True
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None


class DataAskQueryOut(BaseModel):
    answer: str
    sql: str
    display_sql: str = ""
    explanation: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    chart: Optional[dict[str, Any]] = None
    generated_only: bool = False
    analysis_mode: str = "sql"
    files_released: bool = False


class DataAskAuditLogOut(BaseModel):
    id: str
    user_id: Optional[str] = None
    data_source_id: str
    question: Optional[str] = None
    sql_text: str
    row_count: int
    success: bool
    error_message: Optional[str] = None
    created_at: datetime


class DataAskAuditListOut(BaseModel):
    items: list[DataAskAuditLogOut]
    total: int


class GoldenQueryIn(BaseModel):
    question: str = Field(..., min_length=1)
    sql_text: str = Field(..., min_length=1)


class GoldenQueryOut(BaseModel):
    id: str
    data_source_id: str
    question: str
    sql_text: str
    use_count: int
    created_at: datetime
    updated_at: datetime


class GoldenQueryListOut(BaseModel):
    items: list[GoldenQueryOut]


class SemanticModelUpdateIn(BaseModel):
    semantic_model: dict[str, Any]


class SchemaDriftOut(BaseModel):
    changed: bool
    tables: list[dict[str, Any]] = Field(default_factory=list)


class GenerateBlueprintIn(BaseModel):
    nl_prompt: Optional[str] = None


class GenerateBlueprintOut(BaseModel):
    blueprint: dict[str, Any]


class CreateEmployeeFromSourceIn(BaseModel):
    nl_prompt: Optional[str] = None
    cron_expression: str = "0 8 * * *"
    create_agent: bool = True


class ExcelFileOut(BaseModel):
    name: str
    size_bytes: int
    modified_at: float


class ExcelFileListOut(BaseModel):
    items: list[ExcelFileOut] = Field(default_factory=list)


class ExcelUploadOut(BaseModel):
    uploaded: list[str] = Field(default_factory=list)
    items: list[ExcelFileOut] = Field(default_factory=list)


class ExcelLoadStatusOut(BaseModel):
    status: str = "idle"
    sheet_count: int = 0
    total_rows: int = 0
    file_count: int = 0
    loaded_at: Optional[float] = None
    error: Optional[str] = None
    table_names: list[str] = Field(default_factory=list)


class CreateEmployeeFromSourceOut(BaseModel):
    employee_id: str
    agent_id: str
    tasks_created: int
