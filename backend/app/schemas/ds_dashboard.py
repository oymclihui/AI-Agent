"""经营分析看板技能 API schemas。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DashboardGenerateIn(BaseModel):
    conversation_id: str | None = Field(default=None, description="生成完成后写入卡片消息的会话")
    title: str | None = Field(default=None, max_length=120, description="看板标题（缺省自动生成）")
    template: str = Field(default="retail_overview", description="P0 仅支持 retail_overview")


class DashboardGenerateOut(BaseModel):
    task_id: str
    status: str
    message: str


class DashboardEventOut(BaseModel):
    id: int
    stage: str
    status: str
    detail: dict[str, Any] = {}
    created_at: datetime | None = None


class DashboardTaskOut(BaseModel):
    id: str
    data_source_id: str
    template: str
    title: str
    status: str
    stage: str | None = None
    progress: int = 0
    period_start: str | None = None
    period_end: str | None = None
    kpis: list[dict[str, Any]] = []
    anchor_status: str | None = None
    anchor_detail: dict[str, Any] = {}
    verify_report: dict[str, Any] = {}
    error: str | None = None
    message_id: str | None = None
    view_url: str
    created_at: datetime | None = None
    events: list[DashboardEventOut] = []


class DashboardListItem(BaseModel):
    id: str
    title: str
    status: str
    stage: str | None = None
    progress: int = 0
    period_start: str | None = None
    period_end: str | None = None
    anchor_status: str | None = None
    error: str | None = None
    created_at: datetime | None = None
