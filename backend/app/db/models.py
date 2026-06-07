"""
SQLAlchemy ORM models for all AIAGNET entities.
"""
from sqlalchemy import (
    Column, String, Text, Boolean, Integer, Float,
    ForeignKey, JSON, Enum as SAEnum
)
from sqlalchemy.orm import relationship
import enum

from app.db.base import Base, TimestampMixin, generate_uuid


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────

class AgentStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"


class WorkflowStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class ExecutionStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ProcessType(str, enum.Enum):
    sequential = "sequential"
    hierarchical = "hierarchical"
    parallel = "parallel"


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    system = "system"
    tool = "tool"


class KBStatus(str, enum.Enum):
    processing = "processing"
    ready = "ready"
    error = "error"


# ──────────────────────────────────────────────
# Agent
# ──────────────────────────────────────────────

class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    role = Column(String(255), nullable=False)
    goal = Column(Text, nullable=False)
    backstory = Column(Text, nullable=True)
    status = Column(SAEnum(AgentStatus), default=AgentStatus.active, nullable=False)
    llm_provider = Column(String(64), nullable=True)
    llm_model = Column(String(128), nullable=True)
    temperature = Column(Float, default=0.7)
    max_iterations = Column(Integer, default=10)
    tools_config = Column(JSON, default=list)
    memory_config = Column(JSON, default=dict)
    metadata_ = Column("metadata", JSON, default=dict)

    executions = relationship("AgentExecution", back_populates="agent", cascade="all, delete-orphan")


# ──────────────────────────────────────────────
# Workflow
# ──────────────────────────────────────────────

class Workflow(Base, TimestampMixin):
    __tablename__ = "workflows"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(SAEnum(WorkflowStatus), default=WorkflowStatus.draft, nullable=False)
    process_type = Column(SAEnum(ProcessType), default=ProcessType.sequential, nullable=False)
    graph_definition = Column(JSON, default=dict)  # nodes + edges
    agents_config = Column(JSON, default=list)
    triggers_config = Column(JSON, default=list)
    metadata_ = Column("metadata", JSON, default=dict)

    executions = relationship("WorkflowExecution", back_populates="workflow", cascade="all, delete-orphan")


class WorkflowExecution(Base, TimestampMixin):
    __tablename__ = "workflow_executions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workflow_id = Column(String(36), ForeignKey("workflows.id"), nullable=False)
    status = Column(SAEnum(ExecutionStatus), default=ExecutionStatus.pending, nullable=False)
    input_data = Column(JSON, default=dict)
    output_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    state_snapshot = Column(JSON, nullable=True)  # LangGraph checkpoint
    token_usage = Column(JSON, default=dict)
    duration_ms = Column(Integer, nullable=True)

    workflow = relationship("Workflow", back_populates="executions")
    agent_executions = relationship("AgentExecution", back_populates="workflow_execution", cascade="all, delete-orphan")


class AgentExecution(Base, TimestampMixin):
    __tablename__ = "agent_executions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workflow_execution_id = Column(String(36), ForeignKey("workflow_executions.id"), nullable=True)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False)
    task_description = Column(Text, nullable=False)
    status = Column(SAEnum(ExecutionStatus), default=ExecutionStatus.pending, nullable=False)
    output = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    token_usage = Column(JSON, default=dict)
    steps = Column(JSON, default=list)  # tool calls, reasoning steps

    agent = relationship("Agent", back_populates="executions")
    workflow_execution = relationship("WorkflowExecution", back_populates="agent_executions")


# ──────────────────────────────────────────────
# Conversation & Messages
# ──────────────────────────────────────────────

class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(255), nullable=True)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=True)
    workflow_id = Column(String(36), ForeignKey("workflows.id"), nullable=True)
    knowledge_base_ids = Column(JSON, default=list)
    memory_type = Column(String(64), default="buffer")
    is_active = Column(Boolean, default=True)
    metadata_ = Column("metadata", JSON, default=dict)

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    conversation_id = Column(String(36), ForeignKey("conversations.id"), nullable=False)
    role = Column(SAEnum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)
    tool_calls = Column(JSON, nullable=True)
    token_usage = Column(JSON, nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)

    conversation = relationship("Conversation", back_populates="messages")


# ──────────────────────────────────────────────
# Knowledge Base
# ──────────────────────────────────────────────

class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(SAEnum(KBStatus), default=KBStatus.processing, nullable=False)
    embedding_model = Column(String(128), default="text-embedding-3-small")
    chunk_size = Column(Integer, default=1000)
    chunk_overlap = Column(Integer, default=200)
    document_count = Column(Integer, default=0)
    metadata_ = Column("metadata", JSON, default=dict)

    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    knowledge_base_id = Column(String(36), ForeignKey("knowledge_bases.id"), nullable=False)
    filename = Column(String(512), nullable=False)
    file_type = Column(String(32), nullable=False)
    file_size = Column(Integer, nullable=True)
    storage_path = Column(String(1024), nullable=True)
    status = Column(SAEnum(KBStatus), default=KBStatus.processing, nullable=False)
    chunk_count = Column(Integer, default=0)
    metadata_ = Column("metadata", JSON, default=dict)

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")


# ──────────────────────────────────────────────
# Model Configuration
# ──────────────────────────────────────────────

class ModelConfig(Base, TimestampMixin):
    __tablename__ = "model_configs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False, unique=True)
    provider = Column(String(64), nullable=False)
    model_id = Column(String(128), nullable=False)
    api_key_encrypted = Column(Text, nullable=True)
    base_url = Column(String(512), nullable=True)
    config = Column(JSON, default=dict)
    is_default = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    context_window = Column(Integer, nullable=True)
    cost_per_1k_input = Column(Float, nullable=True)
    cost_per_1k_output = Column(Float, nullable=True)


# ──────────────────────────────────────────────
# Tool Registry
# ──────────────────────────────────────────────

class ToolDefinition(Base, TimestampMixin):
    __tablename__ = "tool_definitions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=False)
    category = Column(String(64), nullable=False, default="custom")
    parameters_schema = Column(JSON, default=dict)
    implementation_type = Column(String(32), default="builtin")  # builtin | http | python
    config = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
