"""Agent Evolution 阶段一 Schemas：画像 / 语义层 / 反馈 / 轨迹。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── Schema 画像 ───

class ProfileBuildOut(BaseModel):
    profile_id: int
    version: int
    status: str
    message: str = ""


class ProfileStatusOut(BaseModel):
    status: str  # none/building/ready/failed
    profile_id: Optional[int] = None
    version: Optional[int] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    updated_at: Optional[datetime] = None


class ProfileOut(BaseModel):
    id: int
    data_source_id: str
    version: int
    status: str
    trigger: str
    profile: Optional[dict[str, Any]] = None
    table_count: Optional[int] = None
    column_count: Optional[int] = None
    row_counts: Optional[dict[str, Any]] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None


# ─── 术语词典 ───

class TermIn(BaseModel):
    term: str = Field(min_length=1, max_length=255)
    definition: Optional[str] = None
    column_ref: Optional[str] = None
    synonyms: list[str] = Field(default_factory=list)


class TermOut(BaseModel):
    id: str
    term: str
    definition: Optional[str] = None
    column_ref: Optional[str] = None
    synonyms: list[str] = Field(default_factory=list)
    source: str = "manual"
    use_count: int = 0
    created_at: Optional[datetime] = None


# ─── 指标口径 ───

class MetricIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    expr: str = Field(min_length=1)
    dimensions: list[str] = Field(default_factory=list)
    default_filters: list[str] = Field(default_factory=list)
    description: Optional[str] = None


class MetricOut(BaseModel):
    id: str
    name: str
    expr: str
    dimensions: list[str] = Field(default_factory=list)
    default_filters: list[str] = Field(default_factory=list)
    description: Optional[str] = None
    source: str = "manual"
    use_count: int = 0
    created_at: Optional[datetime] = None


# ─── 问数反馈 ───

class FeedbackIn(BaseModel):
    data_source_id: str
    feedback_type: str  # like / dislike / correction / example
    trace_id: Optional[int] = None
    question: Optional[str] = None
    original_sql: Optional[str] = None
    corrected_sql: Optional[str] = None
    comment: Optional[str] = None


class FeedbackOut(BaseModel):
    id: int
    saved_example: bool = False
    message: str = ""
    task_id: Optional[int] = None


# ─── 对话内训练任务 ───

class TrainTaskOut(BaseModel):
    id: int
    data_source_id: str
    kind: str = "example"
    status: str = "queued"
    progress: int = 0
    detail: Optional[dict[str, Any]] = None
    feedback_id: Optional[int] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ─── 问数轨迹 ───

class TraceOut(BaseModel):
    id: int
    data_source_id: str
    user_id: Optional[str] = None
    question: Optional[str] = None
    standalone_question: Optional[str] = None
    sql_text: Optional[str] = None
    row_count: Optional[int] = None
    success: bool = True
    error_message: Optional[str] = None
    analysis_mode: Optional[str] = None
    memory_hits: int = 0
    duration_ms: Optional[int] = None
    rewrite_ms: Optional[int] = None
    gen_ms: Optional[int] = None
    exec_ms: Optional[int] = None
    analysis_ms: Optional[int] = None
    result_signature: Optional[str] = None
    clarification: bool = False
    cached: bool = False
    created_at: Optional[datetime] = None
