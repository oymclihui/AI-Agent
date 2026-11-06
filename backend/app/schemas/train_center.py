"""训练中心 P1 Schemas：统一训练工单（五步向导）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class TrainStageOut(BaseModel):
    key: str
    label: str = ""
    status: str = "pending"  # pending/running/done/failed/skipped
    progress: int = 0
    message: Optional[str] = None
    detail: Optional[dict[str, Any]] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class TrainJobOut(BaseModel):
    id: str
    target_type: str = "ds"
    target_id: str
    kind: str = "full"
    status: str = "queued"
    stage: str = "queued"
    progress: int = 0
    stages: list[TrainStageOut] = Field(default_factory=list)
    detail: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    note: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TrainJobCreateIn(BaseModel):
    target_type: str = Field(default="ds", pattern="^(ds|agent)$")
    target_id: str = Field(min_length=1, max_length=64)
    kind: str = Field(default="full", pattern="^(distill|eval|full|prompt|trajectory)$")
    note: Optional[str] = Field(default=None, max_length=500)


class TrainJobRetryIn(BaseModel):
    from_stage: str = Field(min_length=1, max_length=32)


class FeedbackStepOut(BaseModel):
    key: str
    label: str
    done: bool = False


class FeedbackStatusOut(BaseModel):
    feedback_id: int
    data_source_id: str
    question: Optional[str] = None
    feedback_type: str = ""
    task_id: Optional[int] = None
    task_status: Optional[str] = None
    queued: bool = False
    distilled: bool = False
    effective: bool = False
    example_id: Optional[str] = None
    example_indexed: bool = False
    steps: list[FeedbackStepOut] = Field(default_factory=list)
    message: str = ""
    created_at: Optional[datetime] = None


# ── P2: PromptCandidate (GEPA) ──


class PromptCandidateOut(BaseModel):
    id: str
    agent_id: str
    data_source_id: Optional[str] = None
    base_version_id: Optional[int] = None
    field: str
    before: str
    after: str
    reason: Optional[str] = None
    failure_clusters: list[Any] = Field(default_factory=list)
    score_delta: Optional[float] = None
    status: str = "pending"
    eval_run_id: Optional[int] = None
    train_job_id: Optional[str] = None
    model: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None


class PromptDiffOut(BaseModel):
    field: str
    changed: bool
    old_preview: str = ""
    new_preview: str = ""
    before: str = ""
    after: str = ""


# ── P3: 标准化训练轨迹 ──


class TrainTrajectoryOut(BaseModel):
    id: str
    data_source_id: str
    agent_id: Optional[str] = None
    trace_id: Optional[int] = None
    run_id: str
    question: Optional[str] = None
    standalone_question: Optional[str] = None
    mode: Optional[str] = None
    plan: Optional[dict[str, Any]] = None
    tool_calls: list[Any] = Field(default_factory=list)
    observation: Optional[dict[str, Any]] = None
    result: Optional[dict[str, Any]] = None
    reward: float = 0.0
    success: bool = False
    n_candidates: int = 0
    n_invalid_calls: int = 0
    n_rounds: int = 1
    source: str = "tree"
    train_job_id: Optional[str] = None
    created_at: Optional[datetime] = None


# ── P4: RL 训练数据导出 ──


class RlExportIn(BaseModel):
    data_source_id: str = Field(min_length=1, max_length=64)
    range: str = Field(default="all", max_length=32)  # all/failed/success/last:N
    reward_rule: str = Field(
        default="success=+1.0;invalid=-0.5;clarify=+0.2",
        max_length=200,
        description="规则奖励：key=value 分号分隔，支持 success/invalid/clarify 三类",
    )


class RlExportOut(BaseModel):
    id: str
    data_source_id: str
    agent_id: Optional[str] = None
    range: str = "all"
    format: str = "jsonl"
    reward_rule: str = ""
    row_count: int = 0
    uri: Optional[str] = None
    train_job_id: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
