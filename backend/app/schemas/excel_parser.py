from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class SheetMappingIn(BaseModel):
    sheet_name: str
    field_mapping: list[dict[str, str]] | dict[str, str] = Field(default_factory=dict)


class ExcelParseTemplateCreate(BaseModel):
    id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(default="BS", max_length=32)
    sheet_mappings: list[SheetMappingIn] = Field(default_factory=list)
    description: Optional[str] = None
    is_global: bool = False


class ExcelParseTemplateUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    sheet_mappings: Optional[list[SheetMappingIn]] = None
    description: Optional[str] = None
    is_global: Optional[bool] = None


class ExcelParseTemplateOut(BaseModel):
    id: str
    name: str
    type: str
    sheet_mappings: list[dict[str, Any]] = Field(default_factory=list)
    description: Optional[str] = None
    is_global: bool = False
    owner_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ExcelParseTemplateListOut(BaseModel):
    items: list[ExcelParseTemplateOut]


class ExcelParseJobCreate(BaseModel):
    template_id: str
    data_source_id: Optional[str] = None
    folder_path: Optional[str] = None
    recursive: bool = True
    output_filename: Optional[str] = None


class ExcelParseJobOut(BaseModel):
    id: str
    template_id: str
    data_source_id: Optional[str] = None
    folder_path: Optional[str] = None
    recursive: bool = True
    status: str
    progress: int = 0
    row_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    output_file: Optional[str] = None
    columns: list[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    error_logs: list[dict[str, Any]] = Field(default_factory=list)
    result_preview: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    completed_at: Optional[datetime] = None


class ExcelParseJobListOut(BaseModel):
    items: list[ExcelParseJobOut]


class ExcelTemplateParseIn(BaseModel):
    template_id: Optional[str] = None
    folder_path: Optional[str] = None
    recursive: bool = True
    output_filename: Optional[str] = None


class ExcelTemplateStatusOut(BaseModel):
    parse_status: str = "idle"
    template_id: Optional[str] = None
    last_job_id: Optional[str] = None
    last_output_file: Optional[str] = None
    input_file_count: int = 0
    output_file_count: int = 0


class ExcelParseGlobalStatsOut(BaseModel):
    total: int = 0
    success: int = 0
    failed: int = 0
    last_parse_time: Optional[str] = None


class ExcelParseResultOut(BaseModel):
    columns: list[str] = Field(default_factory=list)
    data: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
