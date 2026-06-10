from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


class DashboardSchedulerInfo(BaseModel):
    running: bool
    last_tick: Optional[datetime] = None
    last_error: Optional[str] = None
    interval_seconds: int = 30


class DashboardTodayStats(BaseModel):
    total_runs: int = 0
    completed: int = 0
    failed: int = 0
    running: int = 0
    active_employees: int = 0
    avg_duration_ms: Optional[int] = None
    token_usage: dict[str, Any] = {}


class DashboardHourlyRun(BaseModel):
    hour: int
    count: int
    completed: int
    failed: int


class DashboardLastRun(BaseModel):
    id: str
    status: str
    at: datetime
    task_name: Optional[str] = None
    task_id: Optional[str] = None
    summary: Optional[str] = None
    triggered_by: Optional[str] = None
    duration_ms: Optional[int] = None


class DashboardEmployeeCard(BaseModel):
    id: str
    name: str
    title: Optional[str] = None
    agent_name: Optional[str] = None
    employee_status: str
    operational_status: str
    task_count: int = 0
    enabled_tasks: int = 0
    next_run_at: Optional[datetime] = None
    today_runs: int = 0
    today_success: int = 0
    today_failed: int = 0
    last_run: Optional[DashboardLastRun] = None


class DashboardRecentRun(BaseModel):
    id: str
    employee_id: str
    employee_name: str
    task_id: str
    task_name: Optional[str] = None
    status: str
    triggered_by: str
    created_at: datetime
    duration_ms: Optional[int] = None
    prompt_summary: Optional[str] = None
    output_summary: Optional[str] = None


class DashboardPlatformCounts(BaseModel):
    employees: int = 0
    agents: int = 0
    skills: int = 0
    workflows: int = 0
    knowledge_bases: int = 0
    active_employees: int = 0
    enabled_tasks: int = 0


class DashboardOverview(BaseModel):
    generated_at: datetime
    timezone: str = "Asia/Shanghai"
    day_start: datetime
    scheduler: DashboardSchedulerInfo
    health: dict[str, Any]
    platform: DashboardPlatformCounts
    today: DashboardTodayStats
    hourly_runs: list[DashboardHourlyRun]
    employees: list[DashboardEmployeeCard]
    recent_runs: list[DashboardRecentRun]
