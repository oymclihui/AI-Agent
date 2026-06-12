from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.db.models import DesktopDemoStatus, DesktopTaskAction, ExecutionStatus


class DesktopDemoCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    app_name: Optional[str] = None
    tags: list[str] = []


class DesktopDemoUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    app_name: Optional[str] = None
    tags: Optional[list[str]] = None
    status: Optional[DesktopDemoStatus] = None


class DesktopDemoResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    app_name: Optional[str]
    tags: list[str]
    status: DesktopDemoStatus
    step_count: int
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class DesktopTaskResponse(BaseModel):
    id: str
    demo_id: Optional[str]
    demo_name: Optional[str] = None
    action: DesktopTaskAction
    status: ExecutionStatus
    instructions: Optional[str]
    input_data: dict[str, Any]
    output_data: Optional[dict[str, Any]]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class DesktopReplayRequest(BaseModel):
    demo_id: Optional[str] = None
    demo_name: Optional[str] = None
    instructions: Optional[str] = None
    confirmed: bool = False


class DesktopCaptureRequest(BaseModel):
    demo_name: Optional[str] = None
    app_name: Optional[str] = None
    description: Optional[str] = None


class SidecarRegisterRequest(BaseModel):
    device_id: Optional[str] = None
    device_name: str = Field(..., min_length=1, max_length=255)
    hostname: Optional[str] = None
    platform: Optional[str] = None


class SidecarRegisterResponse(BaseModel):
    id: str
    device_id: str
    device_name: str
    hostname: Optional[str]
    platform: Optional[str]
    online: bool


class SidecarStatusResponse(BaseModel):
    online: bool
    device_id: Optional[str] = None
    device_name: Optional[str] = None
    hostname: Optional[str] = None
    platform: Optional[str] = None
    last_seen_at: Optional[datetime] = None


class SidecarPollResponse(BaseModel):
    tasks: list[DesktopTaskResponse]


class DemoDepositRequest(BaseModel):
    target: str = Field(..., pattern="^(skill|knowledge)$")
    kb_id: Optional[str] = None
    kb_name: Optional[str] = None
    use_llm: bool = True


class DemoDepositResponse(BaseModel):
    target: str
    skill_id: Optional[str] = None
    skill_slug: Optional[str] = None
    kb_id: Optional[str] = None
    document_id: Optional[str] = None


class SidecarTaskCompleteRequest(BaseModel):
    status: ExecutionStatus
    output_data: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    demo_name: Optional[str] = None
    app_name: Optional[str] = None
    description: Optional[str] = None
    step_count: Optional[int] = None
