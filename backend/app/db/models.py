"""
SQLAlchemy ORM models for all AIAGNET entities.
"""
from sqlalchemy import (
    Column, String, Text, Boolean, Integer, Float,
    ForeignKey, JSON, Enum as SAEnum, DateTime,
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
# User & credentials
# ──────────────────────────────────────────────

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    employee_no = Column(String(64), unique=True, nullable=True, index=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)

    model_credentials = relationship("UserModelCredential", back_populates="user", cascade="all, delete-orphan")
    mailbox_credential = relationship(
        "UserMailboxCredential", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class PasswordResetToken(Base, TimestampMixin):
    __tablename__ = "password_reset_tokens"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(128), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)


class UserMailboxCredential(Base, TimestampMixin):
    """Per-user corporate mailbox password for IMAP fetch_mail tool."""
    __tablename__ = "user_mailbox_credentials"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=False)
    mailbox_password = Column(Text, nullable=False)
    imap_host = Column(String(255), nullable=True)
    imap_port = Column(Integer, nullable=True)
    imap_use_ssl = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    user = relationship("User", back_populates="mailbox_credential")


class UserModelCredential(Base, TimestampMixin):
    """Per-user LLM API keys (same model catalog, different keys)."""
    __tablename__ = "user_model_credentials"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(64), nullable=False)
    model_id = Column(String(128), nullable=True)  # null = all models for provider
    api_key = Column(Text, nullable=False)
    base_url = Column(String(512), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    user = relationship("User", back_populates="model_credentials")


# ──────────────────────────────────────────────
# Agent
# ──────────────────────────────────────────────

class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
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
    skills_config = Column(JSON, default=list)
    memory_config = Column(JSON, default=dict)
    metadata_ = Column("metadata", JSON, default=dict)

    executions = relationship("AgentExecution", back_populates="agent", cascade="all, delete-orphan")


# ──────────────────────────────────────────────
# Workflow
# ──────────────────────────────────────────────

class Workflow(Base, TimestampMixin):
    __tablename__ = "workflows"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
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
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
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
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
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
# Skills
# ──────────────────────────────────────────────

class SkillStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class Skill(Base, TimestampMixin):
    __tablename__ = "skills"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    slug = Column(String(64), nullable=False, unique=True)
    display_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    instructions_md = Column(Text, nullable=False, default="")
    status = Column(SAEnum(SkillStatus), default=SkillStatus.draft, nullable=False)
    scope = Column(String(32), default="global", nullable=False)
    auto_invoke = Column(Boolean, default=False, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    resources = Column(JSON, default=list)
    tools_required = Column(JSON, default=list)
    knowledge_base_ids = Column(JSON, default=list)
    tags = Column(JSON, default=list)
    metadata_ = Column("metadata", JSON, default=dict)


# ──────────────────────────────────────────────
# Digital Employee (scheduled agents)
# ──────────────────────────────────────────────

class EmployeeStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    archived = "archived"


class ScheduleType(str, enum.Enum):
    cron = "cron"
    interval = "interval"


class EmployeeTaskType(str, enum.Enum):
    agent = "agent"


class TaskTrigger(str, enum.Enum):
    schedule = "schedule"
    manual = "manual"


class DigitalEmployee(Base, TimestampMixin):
    __tablename__ = "digital_employees"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    status = Column(SAEnum(EmployeeStatus), default=EmployeeStatus.active, nullable=False)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False)
    skills_config = Column(JSON, default=list)
    knowledge_base_ids = Column(JSON, default=list)
    timezone = Column(String(64), default="Asia/Shanghai", nullable=False)
    metadata_ = Column("metadata", JSON, default=dict)

    agent = relationship("Agent", foreign_keys=[agent_id])
    scheduled_tasks = relationship(
        "EmployeeScheduledTask", back_populates="employee", cascade="all, delete-orphan"
    )
    task_runs = relationship(
        "EmployeeTaskRun", back_populates="employee", cascade="all, delete-orphan"
    )


class EmployeeScheduledTask(Base, TimestampMixin):
    __tablename__ = "employee_scheduled_tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    employee_id = Column(String(36), ForeignKey("digital_employees.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    schedule_type = Column(SAEnum(ScheduleType), default=ScheduleType.cron, nullable=False)
    cron_expression = Column(String(128), nullable=True)
    interval_seconds = Column(Integer, nullable=True)
    timezone = Column(String(64), default="Asia/Shanghai", nullable=False)
    task_type = Column(SAEnum(EmployeeTaskType), default=EmployeeTaskType.agent, nullable=False)
    task_config = Column(JSON, default=dict)
    retry_max = Column(Integer, default=0)
    timeout_seconds = Column(Integer, default=600)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String(32), nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)

    employee = relationship("DigitalEmployee", back_populates="scheduled_tasks")
    runs = relationship("EmployeeTaskRun", back_populates="task", cascade="all, delete-orphan")


class EmployeeTaskRun(Base, TimestampMixin):
    __tablename__ = "employee_task_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("employee_scheduled_tasks.id"), nullable=False)
    employee_id = Column(String(36), ForeignKey("digital_employees.id"), nullable=False)
    status = Column(SAEnum(ExecutionStatus), default=ExecutionStatus.pending, nullable=False)
    triggered_by = Column(SAEnum(TaskTrigger), default=TaskTrigger.manual, nullable=False)
    input_data = Column(JSON, default=dict)
    output_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    token_usage = Column(JSON, default=dict)
    duration_ms = Column(Integer, nullable=True)
    agent_execution_id = Column(String(36), ForeignKey("agent_executions.id"), nullable=True)

    task = relationship("EmployeeScheduledTask", back_populates="runs")
    employee = relationship("DigitalEmployee", back_populates="task_runs")


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
