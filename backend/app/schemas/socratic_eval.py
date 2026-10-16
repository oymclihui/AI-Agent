"""S4 苏格拉底反问评估 schemas"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SocraticEvalSetItemIn(BaseModel):
    agent_id: Optional[str] = None
    question: str
    expected_behavior: str  # clarify / direct
    expected_domains: list[str] = Field(default_factory=list)
    difficulty: str = "medium"
    note: Optional[str] = None


class SocraticEvalSetItemUpdateIn(BaseModel):
    expected_behavior: Optional[str] = None
    expected_domains: Optional[list[str]] = None
    difficulty: Optional[str] = None
    active: Optional[bool] = None
    note: Optional[str] = None


class SocraticEvalSetItemOut(BaseModel):
    id: str
    agent_id: Optional[str] = None
    question: str
    expected_behavior: str
    expected_domains: list[str] = Field(default_factory=list)
    difficulty: str = "medium"
    active: bool = True
    note: Optional[str] = None
    source: Optional[str] = None
    created_at: Any = None


class SocraticEvalSetBuildOut(BaseModel):
    created: int = 0
    skipped_dupe: int = 0
    set_size: int = 0


class SocraticEvalRunOut(BaseModel):
    id: int
    agent_id: Optional[str] = None
    status: str
    total: int = 0
    passed: int = 0
    clarify_accuracy: Optional[float] = None
    direct_accuracy: Optional[float] = None
    avg_rounds: Optional[float] = None
    duration_ms: Optional[int] = None
    created_at: Any = None


class SocraticEvalRunDetailOut(SocraticEvalRunOut):
    items: list[dict[str, Any]] = Field(default_factory=list)


class SocraticEvalRunTriggerOut(BaseModel):
    run_id: int
    message: str = ""


class SocraticQualityOut(BaseModel):
    agent_id: Optional[str] = None
    window_days: int = 30
    total_clarify_events: int = 0
    total_user_messages: int = 0
    clarify_rate: float = 0.0
    resolve_rate: float = 0.0
    misclarify_rate: Optional[float] = None
    avg_rounds: Optional[float] = None
    last_eval_run_id: Optional[int] = None
    gates: dict[str, Any] = Field(default_factory=dict)


class SocraticWeeklyOut(BaseModel):
    ok: bool = False
    message: str = ""
    eval_run_id: Optional[int] = None
    metrics: dict[str, Any] = Field(default_factory=dict)
