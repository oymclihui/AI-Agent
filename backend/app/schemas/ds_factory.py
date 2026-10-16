"""Agent Evolution 阶段三 L3 Schemas：智能体工厂（养成画像 / 配置生成 / 版本 / 发布）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── 养成画像 ───

class CoachOut(BaseModel):
    data_source_id: str
    data_source_name: Optional[str] = None
    driver: Optional[str] = None
    profile: dict[str, Any] = Field(default_factory=dict)
    semantic: dict[str, Any] = Field(default_factory=dict)
    distill: dict[str, Any] = Field(default_factory=dict)
    signal: dict[str, Any] = Field(default_factory=dict)
    ml: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[dict[str, Any]] = Field(default_factory=list)
    readiness: dict[str, Any] = Field(default_factory=dict)
    gaps: list[str] = Field(default_factory=list)


# ─── 配置生成 ───

class GenerateSpecIn(BaseModel):
    nl_prompt: Optional[str] = None
    name: Optional[str] = None


class AgentSpecIn(BaseModel):
    name: str
    role: str = "Data Analyst"
    goal: str = ""
    backstory: Optional[str] = None
    temperature: float = 0.35
    tools_config: list[dict[str, Any]] = Field(default_factory=list)
    skills_config: list[dict[str, Any]] = Field(default_factory=list)
    memory_config: dict[str, Any] = Field(default_factory=dict)
    metadata_: dict[str, Any] = Field(default_factory=dict)


class SpecOut(BaseModel):
    name: str
    role: str
    goal: str
    backstory: Optional[str] = None
    temperature: float = 0.35
    tools_config: list[dict[str, Any]] = Field(default_factory=list)
    skills_config: list[dict[str, Any]] = Field(default_factory=list)
    memory_config: dict[str, Any] = Field(default_factory=dict)
    metadata_: dict[str, Any] = Field(default_factory=dict)
    opening_questions: list[str] = Field(default_factory=list)


class GenerateSpecOut(BaseModel):
    spec: SpecOut
    coach: CoachOut


class PublishIn(BaseModel):
    spec: AgentSpecIn
    coach: Optional[dict[str, Any]] = None
    note: Optional[str] = None


class PublishOut(BaseModel):
    agent_id: str
    version: int
    version_id: int
    release_id: str
    message: str = ""


# ─── 版本化 ───

class VersionOut(BaseModel):
    id: int
    agent_id: str
    data_source_id: Optional[str] = None
    version: int
    source: str
    note: Optional[str] = None
    status: str
    spec: dict[str, Any]
    coach: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None


class DiffItemOut(BaseModel):
    field: str
    changed: bool
    old: Optional[Any] = None
    new: Optional[Any] = None
    old_preview: str = ""
    new_preview: str = ""


class DiffOut(BaseModel):
    agent_id: str
    base_version: Optional[int] = None
    target_version: int
    items: list[DiffItemOut] = Field(default_factory=list)


class RollbackIn(BaseModel):
    note: Optional[str] = None


# ─── 发布与灰度 ───

class ReleaseIn(BaseModel):
    version_id: int
    scope: str = "full"  # full / gray
    gray_users: list[str] = Field(default_factory=list)
    note: Optional[str] = None


class ReleaseOut(BaseModel):
    id: str
    agent_id: str
    version_id: int
    version: int
    scope: str
    gray_users: list[str] = Field(default_factory=list)
    active: bool = True
    released_by: Optional[str] = None
    note: Optional[str] = None
    created_at: Optional[datetime] = None


# ─── 试跑 ───

class TrialIn(BaseModel):
    question: str = Field(min_length=1)


class TrialOut(BaseModel):
    success: bool = True
    sql: str = ""
    row_count: int = 0
    analysis_mode: str = "sql"
    answer_excerpt: str = ""
    chart: Optional[dict[str, Any]] = None
    trace_id: Optional[int] = None
    error: Optional[str] = None
