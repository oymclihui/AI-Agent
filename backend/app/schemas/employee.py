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
    desktop_automation = "desktop_automation"
    workflow = "workflow"
    crew = "crew"


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
    department_id: Optional[str] = None
    parent_employee_id: Optional[str] = None
    sort_order: int = 0


class EmployeeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    title: Optional[str] = None
    description: Optional[str] = None
    agent_id: Optional[str] = None
    skills_config: Optional[list[SkillBinding]] = None
    knowledge_base_ids: Optional[list[str]] = None
    timezone: Optional[str] = None
    status: Optional[EmployeeStatus] = None
    department_id: Optional[str] = None
    parent_employee_id: Optional[str] = None
    sort_order: Optional[int] = None


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
    department_id: Optional[str] = None
    parent_employee_id: Optional[str] = None
    sort_order: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
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


class SaveRunToKnowledgeRequest(BaseModel):
    kb_id: Optional[str] = None
    kb_name: Optional[str] = Field(None, max_length=255)


class TaskRunResponse(BaseModel):
    id: str
    task_id: str
    employee_id: str
    task_name: Optional[str] = None
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


class EmployeeTemplateSummary(BaseModel):
    template_id: str
    name_zh: str
    name_en: str
    description_zh: str
    description_en: str
    category: str
    status: str = "draft"
    employee_name: str
    employee_title: Optional[str] = None
    task_count: int
    tasks_preview: list[str] = []


class EmployeeTemplateImportRequest(BaseModel):
    template_id: str = Field(..., min_length=1, max_length=128)
    employee_name: Optional[str] = Field(None, max_length=255)


class EmployeeTemplateImportResponse(BaseModel):
    employee: EmployeeResponse
    tasks_created: int
    template_id: str


class EmployeeOrgChartNode(BaseModel):
    id: str
    name: str
    title: Optional[str] = None
    status: str
    task_count: int = 0
    department_id: Optional[str] = None
    department_name: Optional[str] = None
    parent_employee_id: Optional[str] = None
    depth: int = 0
    sort_order: int = 0
    cadence: Optional[str] = None
    cadence_label_zh: Optional[str] = None
    cadence_label_en: Optional[str] = None
    short_title_zh: Optional[str] = None
    short_title_en: Optional[str] = None


class EmployeeOrgTreeResponse(BaseModel):
    title_zh: str
    title_en: str
    subtitle_zh: str
    subtitle_en: str
    levels: list[list[EmployeeOrgChartNode]]
    roots: list[EmployeeOrgChartNode]
    unassigned: list[EmployeeOrgChartNode]
    department_count: int = 0
    employee_count: int = 0


class EmployeeOrgSyncResponse(BaseModel):
    from_metadata: int
    from_department: int
    total: int
