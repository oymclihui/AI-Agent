from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.db.models import ExecutionStatus


class HarnessPendingActionResponse(BaseModel):
    id: str
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    risk_level: str
    status: ExecutionStatus
    source: Optional[str] = None
    source_id: Optional[str] = None
    result: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class HarnessToolRiskResponse(BaseModel):
    name: str
    risk_level: str
