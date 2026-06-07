from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from enum import Enum


class WorkflowStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class ProcessType(str, Enum):
    sequential = "sequential"
    hierarchical = "hierarchical"
    parallel = "parallel"


class ExecutionStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class NodeType(str, Enum):
    start = "start"
    end = "end"
    agent = "agent"
    tool = "tool"
    condition = "condition"
    human = "human"
    llm = "llm"
    http = "http"
    code = "code"
    note = "note"
    subworkflow = "subworkflow"
    trigger = "trigger"
    switch = "switch"
    set = "set"
    merge = "merge"
    split = "split"
    filter = "filter"
    wait = "wait"
    transform = "transform"
    integration = "integration"
    respond_webhook = "respond_webhook"
    stop_error = "stop_error"


class NodeDefinition(BaseModel):
    id: str
    type: str  # execution type or catalog id
    catalog_id: Optional[str] = None  # n8n catalog node id
    label: str
    config: dict[str, Any] = {}
    position: dict[str, float] = {"x": 0, "y": 0}


class EdgeDefinition(BaseModel):
    id: str
    source: str
    target: str
    condition: Optional[str] = None  # expression for conditional edges
    label: Optional[str] = None


class GraphDefinition(BaseModel):
    nodes: list[NodeDefinition] = []
    edges: list[EdgeDefinition] = []


class TriggerConfig(BaseModel):
    type: str  # webhook | cron | manual | event
    config: dict[str, Any] = {}


class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    process_type: ProcessType = ProcessType.sequential
    graph_definition: GraphDefinition = GraphDefinition()
    agents_config: list[dict[str, Any]] = []
    triggers_config: list[TriggerConfig] = []
    metadata_: dict[str, Any] = Field(default={}, alias="metadata")

    class Config:
        populate_by_name = True


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[WorkflowStatus] = None
    process_type: Optional[ProcessType] = None
    graph_definition: Optional[GraphDefinition] = None
    agents_config: Optional[list[dict[str, Any]]] = None
    triggers_config: Optional[list[TriggerConfig]] = None


class WorkflowResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    status: WorkflowStatus
    process_type: ProcessType
    graph_definition: dict
    agents_config: list
    triggers_config: list
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkflowExecuteRequest(BaseModel):
    input_data: dict[str, Any] = {}
    stream: bool = False


class WorkflowExecutionResponse(BaseModel):
    id: str
    workflow_id: str
    status: ExecutionStatus
    input_data: dict
    output_data: Optional[dict]
    error_message: Optional[str]
    token_usage: dict
    duration_ms: Optional[int]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NodeConfigAssistRequest(BaseModel):
    node_id: str = Field(..., description="Catalog node id, e.g. httpRequest")
    prompt: str = Field(..., min_length=1, description="Natural language config request")
    current_config: dict[str, Any] = {}
    workflow_context: dict[str, Any] = {}
    provider: Optional[str] = None
    model: Optional[str] = None


class NodeConfigAssistResponse(BaseModel):
    config: dict[str, Any]
    explanation: str = ""
    parsed: bool = True
    node: Optional[dict[str, Any]] = None


class WorkflowGenerateRequest(BaseModel):
    description: str = Field(..., min_length=5, description="Natural language workflow description")
    provider: Optional[str] = None
    model: Optional[str] = None
