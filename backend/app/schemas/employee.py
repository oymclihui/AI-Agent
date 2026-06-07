from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from enum import Enum


class EmployeeStatus(str, Enum):
    active = "active"
    paused = "paused"
    archived = "archived"


class ScheduleType(str, Enum):
    cron = "cron"
    interval = "interval"


class EmployeeTaskType(str, Enum):
    agent = "agent"


class SkillBinding(BaseModel):
    skill_id: str
    always_load: bool = True
    priority: int = 0


class EmployeeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    agent_id: str
    skills_config: list[SkillBinding] = []
    knowledge_base_ids: list[str] = []
    timezone: str = Field(default="Asia/Shanghai", max_length=64)
    status: EmployeeStatus = EmployeeStatus.active


class EmployeeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    title: Optional[str] = None
    description: Optional[str] = None
    agent_id: Optional[str] = None
    skills_config: Optional[list[SkillBinding]] = None
    knowledge_base_ids: Optional[list[str]] = None
    timezone: Optional[str] = None
    status: Optional[EmployeeStatus] = None


class EmployeeResponse(BaseModel):
    id: str
    name: str
    title: Optional[str]
    description: Optional[str]
    status: EmployeeStatus
    agent_id: str
    skills_config: list[dict]
    knowledge_base_ids: list[str]
    timezone: str
    task_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ScheduledTaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    enabled: bool = True
    schedule_type: ScheduleType = ScheduleType.cron
    cron_expression: Optional[str] = Field(None, max_length=128)
    interval_seconds: Optional[int] = Field(None, ge=60, le=86400 * 7)
    timezone: Optional[str] = Field(None, max_length=64)
    task_type: EmployeeTaskType = EmployeeTaskType.agent
    task_config: dict[str, Any] = Field(default_factory=dict)
    retry_max: int = Field(default=0, ge=0, le=5)
    timeout_seconds: int = Field(default=600, ge=30, le=3600)


class ScheduledTaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    schedule_type: Optional[ScheduleType] = None
    cron_expression: Optional[str] = None
    interval_seconds: Optional[int] = Field(None, ge=60, le=86400 * 7)
    timezone: Optional[str] = None
    task_config: Optional[dict[str, Any]] = None
    retry_max: Optional[int] = Field(None, ge=0, le=5)
    timeout_seconds: Optional[int] = Field(None, ge=30, le=3600)


class ScheduledTaskResponse(BaseModel):
    id: str
    employee_id: str
    name: str
    description: Optional[str]
    enabled: bool
    schedule_type: ScheduleType
    cron_expression: Optional[str]
    interval_seconds: Optional[int]
    timezone: str
    task_type: EmployeeTaskType
    task_config: dict
    retry_max: int
    timeout_seconds: int
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    last_status: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TaskRunResponse(BaseModel):
    id: str
    task_id: str
    employee_id: str
    status: str
    triggered_by: str
    input_data: dict
    output_data: Optional[dict]
    error_message: Optional[str]
    token_usage: dict
    duration_ms: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True
