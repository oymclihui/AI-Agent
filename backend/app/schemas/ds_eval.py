"""Agent Evolution 阶段四 L4 Schemas：回归评估与质量看板。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── 回归测试集（考题库）───

class EvalSetItemIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    expected_sql: Optional[str] = None
    expected_row_count: Optional[int] = None
    expected_chart: Optional[str] = None
    category: Optional[str] = None
    difficulty: str = "medium"
    note: Optional[str] = None


class EvalSetItemUpdateIn(BaseModel):
    question: Optional[str] = None
    expected_sql: Optional[str] = None
    expected_row_count: Optional[int] = None
    expected_chart: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[str] = None
    active: Optional[bool] = None
    note: Optional[str] = None


class EvalSetItemOut(BaseModel):
    id: str
    data_source_id: str
    agent_id: Optional[str] = None
    question: str
    expected_sql: Optional[str] = None
    expected_signature: Optional[str] = None
    signature_source: Optional[str] = None
    expected_row_count: Optional[int] = None
    expected_chart: Optional[str] = None
    category: str = "aggregation"
    source: str = "manual"
    difficulty: str = "medium"
    active: bool = True
    note: Optional[str] = None
    created_at: Optional[datetime] = None


class EvalSetBuildOut(BaseModel):
    data_source_id: str
    created: int = 0
    golden_used: int = 0
    examples_used: int = 0
    skipped_dupe: int = 0
    baseline_hits: int = 0
    set_size: int = 0
    gaps: list[str] = Field(default_factory=list)


# ─── 评估运行 ──

class EvalRunOut(BaseModel):
    id: int
    data_source_id: str
    agent_id: Optional[str] = None
    agent_version_id: Optional[int] = None
    agent_version: Optional[int] = None
    trigger: str = "manual"
    status: str = "pending"
    total: int = 0
    passed: int = 0
    sql_success_rate: Optional[float] = None
    consistency_rate: Optional[float] = None
    judge_score: Optional[float] = None
    overall_score: Optional[float] = None
    weak_categories: list[dict[str, Any]] = Field(default_factory=list)
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None
    note: Optional[str] = None
    created_at: Optional[datetime] = None


class EvalRunDetailOut(EvalRunOut):
    items: list[dict[str, Any]] = Field(default_factory=list)


class EvalRunTriggerOut(BaseModel):
    run_id: int
    status: str = "pending"
    message: str = ""


# ─── 质量看板 ──

class EvalTrendPoint(BaseModel):
    run_id: int
    created_at: Optional[datetime] = None
    agent_version: Optional[int] = None
    overall_score: Optional[float] = None
    sql_success_rate: Optional[float] = None
    consistency_rate: Optional[float] = None
    judge_score: Optional[float] = None


class EvalQualityOut(BaseModel):
    data_source_id: str
    eval_set_size: int = 0
    latest_run: Optional[EvalRunOut] = None
    trend: list[EvalTrendPoint] = Field(default_factory=list)
    weak_categories: list[dict[str, Any]] = Field(default_factory=list)
    promotion_gate: dict[str, Any] = Field(default_factory=dict)


# ─── 主动学习缺口 ──

class EvalGapCategory(BaseModel):
    category: str
    trace_count: int = 0
    eval_count: int = 0
    status: str = "covered"  # covered / eval_gap / unexplored
    sample_metrics: list[str] = Field(default_factory=list)


class EvalGapsOut(BaseModel):
    data_source_id: str
    window_days: int = 90
    trace_count: int = 0
    eval_set_size: int = 0
    categories: list[EvalGapCategory] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


# ─── 每周进化 ──

class EvalWeeklySourceResult(BaseModel):
    data_source_id: str
    data_source_name: Optional[str] = None
    distill: dict[str, Any] = Field(default_factory=dict)
    eval_set: dict[str, Any] = Field(default_factory=dict)
    candidate_version: Optional[int] = None
    eval_run_id: Optional[int] = None
    scores: dict[str, Any] = Field(default_factory=dict)
    promoted: bool = False
    reason: str = ""


class EvalWeeklyOut(BaseModel):
    results: list[EvalWeeklySourceResult] = Field(default_factory=list)
    message: str = ""
