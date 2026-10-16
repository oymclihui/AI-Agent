"""Agent Evolution 阶段二 Schemas：示例库 / 分析模板 / 业务规则 / 训练度量。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── 训练度量看板（P1） ───

class TrainPreviewIn(BaseModel):
    data_source_id: str
    sql: str = Field(min_length=1)
    limit: int = Field(default=50, ge=1, le=50)


class TrainPreviewOut(BaseModel):
    sql: str
    columns: list[str] = []
    rows: list[list[Any]] = []
    row_count: int = 0
    truncated: bool = False
    duration_ms: int = 0


class TrainKpiOut(BaseModel):
    feedback_total: int = 0
    feedback_like: int = 0
    feedback_dislike: int = 0
    feedback_correction: int = 0
    feedback_example: int = 0
    adoption_rate: Optional[float] = None  # (纠正+存示例) / 反馈总数
    golden_total: int = 0
    golden_net_add: int = 0                # 窗口内新增金标数
    trace_total: int = 0
    trace_success: int = 0
    first_pass_rate: Optional[float] = None  # (总轨迹-被纠正-失败) / 总轨迹
    memory_hit_rate: Optional[float] = None  # memory_hits>0 的轨迹占比
    eval_runs: int = 0
    eval_pass_rate: Optional[float] = None   # 最近一次 done 评测 passed/total
    eval_overall: Optional[float] = None
    eval_weak: list[str] = []


class TrainDayPoint(BaseModel):
    day: str
    feedback_total: int = 0
    feedback_correction: int = 0
    feedback_example: int = 0
    golden_created: int = 0
    trace_total: int = 0
    trace_success: int = 0
    first_pass_rate: Optional[float] = None
    eval_pass_rate: Optional[float] = None


class TrainMetricsOut(BaseModel):
    data_source_id: str
    days: int = 30
    kpi: TrainKpiOut
    series: list[TrainDayPoint] = []


class MaterializeOut(BaseModel):
    message: str = ""
    day: str = ""
    upserted: int = 0


# ─── 示例库 ───

class ExampleOut(BaseModel):
    id: str
    data_source_id: str
    question: str
    sql_text: str
    kind: str  # positive / negative
    source: str
    quality: float = 0.0
    trace_id: Optional[int] = None
    use_count: int = 0
    active: bool = True
    indexed: bool = False
    note: Optional[str] = None
    created_at: Optional[datetime] = None


class DistillOut(BaseModel):
    message: str = ""
    created: int = 0
    updated: int = 0
    indexed: int = 0
    templates: int = 0
    rules: int = 0
    reason: Optional[str] = None


# ─── 分析模板 ───

class TemplateOut(BaseModel):
    id: str
    data_source_id: str
    name: str
    intent: Optional[str] = None
    framework: Optional[str] = None
    sample_questions: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    member_count: int = 0
    hit_count: int = 0
    status: str = "draft"
    source: str = "auto"
    created_at: Optional[datetime] = None


class TemplateUpdateIn(BaseModel):
    name: Optional[str] = None
    intent: Optional[str] = None
    framework: Optional[str] = None
    keywords: Optional[list[str]] = None
    status: Optional[str] = None  # draft / active


# ─── 业务规则 ───

class RuleOut(BaseModel):
    id: str
    data_source_id: str
    rule_type: str  # caliber / terminology / filter
    name: str
    rule_text: str
    applies_to: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    evidence: Optional[dict[str, Any]] = None
    confidence: float = 0.0
    status: str = "candidate"  # candidate / active / rejected
    source: str = "auto"
    materialized_id: Optional[str] = None
    created_at: Optional[datetime] = None


class RuleUpdateIn(BaseModel):
    name: Optional[str] = None
    rule_text: Optional[str] = None
    applies_to: Optional[str] = None
    payload: Optional[dict[str, Any]] = None


# ─── 概览统计 ───

class DistillStatsOut(BaseModel):
    data_source_id: str
    examples_positive: int = 0
    examples_negative: int = 0
    examples_indexed: int = 0
    templates_total: int = 0
    templates_active: int = 0
    rules_total: int = 0
    rules_active: int = 0
    traces_total: int = 0
    feedback_total: int = 0


# ─── P2：影子对比 / 效果归因 / 训练流水线 ───

class ShadowCompareIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AttributionOut(BaseModel):
    data_source_id: str
    days: int = 30
    agent: Optional[dict[str, Any]] = None          # {id, name, production_version}
    memory: dict[str, Any] = {}                     # 命中/采纳统计（memory_hit_log 直算）
    adoption_evidence: list[dict[str, Any]] = []    # 采纳证据明细（top N）
    eval: dict[str, Any] = {}                       # 最近两次回归评测 before/after
    conclusion: str = ""                            # 「本轮训练 → 通过率变化」可复算结论


class EvolveOut(BaseModel):
    message: str = ""
    task_id: int = 0


class TrainTaskItemOut(BaseModel):
    id: int
    kind: str
    status: str
    progress: int = 0
    detail: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TrainEventSnapshotOut(BaseModel):
    event: str = "snapshot"
    data_source_id: str
    tasks: list[TrainTaskItemOut] = []
    eval_runs: list[dict[str, Any]] = []
