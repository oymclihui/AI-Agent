"""高级分析 AnalysisSpec：请求与响应模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


SpecType = Literal[
    "aggregate", "timeseries", "distribution", "topn", "detail",
    "period_compare", "contribution", "breakdown", "outlier", "pareto",
    "forecast", "correlation", "cluster", "cohort", "funnel",
    "whatif", "impact",
]
FilterOp = Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "between", "like"]
Granularity = Literal["day", "week", "month", "quarter", "year"]


class MetricRef(BaseModel):
    name: str = ""
    expr: str
    alias: Optional[str] = None
    agg: Optional[str] = None


class Filter(BaseModel):
    field: str
    op: FilterOp = "eq"
    value: Any = None


class TimeRange(BaseModel):
    field: str
    start: Optional[str] = None
    end: Optional[str] = None
    granularity: Granularity = "day"


class OrderBy(BaseModel):
    field: str
    desc: bool = True


class AnalysisSpecIn(BaseModel):
    type: SpecType
    data_source_id: str
    metrics: list[MetricRef] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    time_range: Optional[TimeRange] = None
    order_by: list[OrderBy] = Field(default_factory=list)
    limit: int = 100
    options: dict[str, Any] = Field(default_factory=dict)
    name: str = ""


class AnalysisSpecRunIn(BaseModel):
    spec: AnalysisSpecIn
    save: bool = False
    name: str = ""


class AnalysisRunOut(BaseModel):
    run_id: str
    spec_hash: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    facts: list[dict[str, str]]
    chart: dict[str, Any]
    query: dict[str, Any]
    error: Optional[str] = None


class AnalysisSpecOut(BaseModel):
    id: str
    data_source_id: str
    name: str
    spec: dict[str, Any]
    spec_hash: str
    version: int
    created_at: Optional[datetime] = None


class AnalysisSpecListOut(BaseModel):
    items: list[AnalysisSpecOut] = Field(default_factory=list)
