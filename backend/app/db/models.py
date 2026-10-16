"""
SQLAlchemy ORM models for all AIAGNET entities.
"""
from sqlalchemy import (
    Column, String, Text, Boolean, Integer, Float,
    ForeignKey, JSON, Enum as SAEnum, DateTime, UniqueConstraint, Date,
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


class AgentVisibility(str, enum.Enum):
    private = "private"
    shared = "shared"
    org = "org"
    platform = "platform"


class AgentShareGranteeType(str, enum.Enum):
    user = "user"
    department = "department"


class AgentSharePermission(str, enum.Enum):
    view = "view"
    use = "use"
    manage = "manage"


class WorkflowStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class ExecutionStatus(str, enum.Enum):
    pending = "pending"
    awaiting_confirmation = "awaiting_confirmation"
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
    primary_department_id = Column(String(36), ForeignKey("departments.id"), nullable=True, index=True)
    user_tier = Column(String(32), default="staff", nullable=False, index=True)

    model_credentials = relationship("UserModelCredential", back_populates="user", cascade="all, delete-orphan")
    mailbox_credential = relationship(
        "UserMailboxCredential", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    department_memberships = relationship(
        "UserDepartment", back_populates="user", cascade="all, delete-orphan", foreign_keys="UserDepartment.user_id"
    )
    role_assignments = relationship(
        "UserRole", back_populates="user", cascade="all, delete-orphan", foreign_keys="UserRole.user_id"
    )


class Department(Base, TimestampMixin):
    __tablename__ = "departments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    code = Column(String(64), nullable=True, unique=True, index=True)
    parent_id = Column(String(36), ForeignKey("departments.id"), nullable=True, index=True)
    path = Column(String(2048), nullable=False, index=True)
    level = Column(Integer, default=0, nullable=False)
    leader_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    liaison_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    dept_tier = Column(String(32), default="business", nullable=False, index=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    parent = relationship("Department", remote_side="Department.id", foreign_keys=[parent_id])
    members = relationship("UserDepartment", back_populates="department", cascade="all, delete-orphan")


class UserDepartment(Base, TimestampMixin):
    __tablename__ = "user_departments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    department_id = Column(String(36), ForeignKey("departments.id"), nullable=False, index=True)
    is_primary = Column(Boolean, default=True, nullable=False)

    user = relationship("User", back_populates="department_memberships", foreign_keys=[user_id])
    department = relationship("Department", back_populates="members")


class UserRole(Base, TimestampMixin):
    __tablename__ = "user_roles"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    role_code = Column(String(64), nullable=False, index=True)
    scope_department_id = Column(String(36), ForeignKey("departments.id"), nullable=True, index=True)

    user = relationship("User", back_populates="role_assignments", foreign_keys=[user_id])


class PermissionAuditLog(Base, TimestampMixin):
    __tablename__ = "permission_audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    actor_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    target_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(64), nullable=False)
    details = Column(JSON, default=dict)


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
    is_default = Column(Boolean, default=False, nullable=False)

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
    visibility = Column(String(32), default=AgentVisibility.private.value, nullable=False, index=True)
    llm_provider = Column(String(64), nullable=True)
    llm_model = Column(String(128), nullable=True)
    temperature = Column(Float, default=0.7)
    max_iterations = Column(Integer, default=10)
    tools_config = Column(JSON, default=list)
    skills_config = Column(JSON, default=list)
    memory_config = Column(JSON, default=dict)
    metadata_ = Column("metadata", JSON, default=dict)

    executions = relationship("AgentExecution", back_populates="agent", cascade="all, delete-orphan")
    shares = relationship("AgentShare", back_populates="agent", cascade="all, delete-orphan")
    share_audit_logs = relationship(
        "AgentShareAuditLog", back_populates="agent", cascade="all, delete-orphan"
    )


class AgentShare(Base, TimestampMixin):
    __tablename__ = "agent_shares"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False, index=True)
    grantee_type = Column(SAEnum(AgentShareGranteeType), nullable=False)
    grantee_id = Column(String(36), nullable=False, index=True)
    permission = Column(SAEnum(AgentSharePermission), default=AgentSharePermission.use, nullable=False)
    granted_by = Column(String(36), ForeignKey("users.id"), nullable=False)

    agent = relationship("Agent", back_populates="shares")


class AgentShareAuditLog(Base, TimestampMixin):
    __tablename__ = "agent_share_audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    actor_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False, index=True)
    action = Column(String(64), nullable=False)
    details = Column(JSON, default=dict)

    agent = relationship("Agent", back_populates="share_audit_logs")


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
    skills_config = Column(JSON, default=list)
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
    visibility = Column(String(32), default="private", nullable=False, index=True)
    document_count = Column(Integer, default=0)
    metadata_ = Column("metadata", JSON, default=dict)

    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")
    grants = relationship("KnowledgeBaseGrant", back_populates="knowledge_base", cascade="all, delete-orphan")


class KnowledgeBaseGrant(Base, TimestampMixin):
    __tablename__ = "knowledge_base_grants"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "grantee_type", "grantee_id", name="uq_kb_grant"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    knowledge_base_id = Column(String(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    grantee_type = Column(String(32), nullable=False)
    grantee_id = Column(String(36), nullable=False, index=True)
    granted_by = Column(String(36), ForeignKey("users.id"), nullable=False)

    knowledge_base = relationship("KnowledgeBase", back_populates="grants")



class KnowledgePassage(Base, TimestampMixin):
    __tablename__ = "knowledge_passages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    knowledge_base_id = Column(String(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(String(36), nullable=False, index=True)
    chunk_index = Column(Integer, default=0, nullable=False)
    parent_index = Column(Integer, nullable=True)
    role = Column(String(16), default="child", nullable=False)
    content = Column(Text, default="", nullable=False)
    title = Column(String(512), default="")


class KnowledgeFaqEntry(Base, TimestampMixin):
    __tablename__ = "knowledge_faq_entries"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    knowledge_base_id = Column(String(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    standard_question = Column(String(500), nullable=False)
    similar_questions = Column(JSON, default=list)
    negative_questions = Column(JSON, default=list)
    answer = Column(Text, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)


class KnowledgeWecomSource(Base, TimestampMixin):
    __tablename__ = "knowledge_wecom_sources"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    knowledge_base_id = Column(String(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, unique=True)
    enabled = Column(Boolean, default=False, nullable=False)
    corp_id = Column(String(64), default="")
    secret_encrypted = Column(Text, nullable=True)
    doc_ids = Column(JSON, default=list)
    last_status = Column(String(32), default="")
    last_error = Column(Text, default="")


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
    desktop_automation = "desktop_automation"
    workflow = "workflow"
    crew = "crew"


class TaskTrigger(str, enum.Enum):
    schedule = "schedule"
    manual = "manual"


class DigitalEmployee(Base, TimestampMixin):
    __tablename__ = "digital_employees"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    department_id = Column(String(36), ForeignKey("departments.id"), nullable=True, index=True)
    parent_employee_id = Column(String(36), ForeignKey("digital_employees.id"), nullable=True, index=True)
    sort_order = Column(Integer, default=0, nullable=False)
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
    parent = relationship(
        "DigitalEmployee",
        remote_side="DigitalEmployee.id",
        foreign_keys=[parent_employee_id],
    )
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
# Desktop automation (OpenAdapt integration)
# ──────────────────────────────────────────────

class DesktopDemoStatus(str, enum.Enum):
    draft = "draft"
    ready = "ready"
    archived = "archived"


class DesktopTaskAction(str, enum.Enum):
    capture_start = "capture_start"
    capture_stop = "capture_stop"
    replay = "replay"


class DesktopDemo(Base, TimestampMixin):
    __tablename__ = "desktop_demos"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    app_name = Column(String(255), nullable=True)
    tags = Column(JSON, default=list)
    status = Column(SAEnum(DesktopDemoStatus), default=DesktopDemoStatus.draft, nullable=False)
    step_count = Column(Integer, default=0)
    metadata_ = Column("metadata", JSON, default=dict)

    tasks = relationship("DesktopTask", back_populates="demo")


class DesktopSidecar(Base, TimestampMixin):
    __tablename__ = "desktop_sidecars"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    device_id = Column(String(128), nullable=False, index=True)
    device_name = Column(String(255), nullable=False)
    hostname = Column(String(255), nullable=True)
    platform = Column(String(64), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)

    tasks = relationship("DesktopTask", back_populates="sidecar")


class DesktopTask(Base, TimestampMixin):
    __tablename__ = "desktop_tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    demo_id = Column(String(36), ForeignKey("desktop_demos.id"), nullable=True)
    sidecar_id = Column(String(36), ForeignKey("desktop_sidecars.id"), nullable=True)
    action = Column(SAEnum(DesktopTaskAction), nullable=False)
    status = Column(SAEnum(ExecutionStatus), default=ExecutionStatus.pending, nullable=False)
    instructions = Column(Text, nullable=True)
    input_data = Column(JSON, default=dict)
    output_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    demo = relationship("DesktopDemo", back_populates="tasks")
    sidecar = relationship("DesktopSidecar", back_populates="tasks")


class HarnessPendingAction(Base, TimestampMixin):
    __tablename__ = "harness_pending_actions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    tool_name = Column(String(128), nullable=False)
    tool_args = Column(JSON, default=dict)
    risk_level = Column(String(16), nullable=False, default="L2")
    status = Column(SAEnum(ExecutionStatus), default=ExecutionStatus.awaiting_confirmation, nullable=False)
    source = Column(String(64), nullable=True)
    source_id = Column(String(36), nullable=True)
    result = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


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


# ──────────────────────────────────────────────
# Data Ask (问数数据源)
# ──────────────────────────────────────────────

class DataSourceDriver(str, enum.Enum):
    postgresql = "postgresql"
    vastbase = "vastbase"
    mysql = "mysql"
    hive = "hive"
    doris = "doris"
    hana = "hana"
    excel_folder = "excel_folder"
    excel_template = "excel_template"


class DataSourceTableRole(str, enum.Enum):
    data = "data"
    permission = "permission"


class DataSourceObjectType(str, enum.Enum):
    table = "table"
    view = "view"


class DataSourceStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"


class DataSource(Base, TimestampMixin):
    __tablename__ = "data_sources"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    driver = Column(String(32), nullable=False, default=DataSourceDriver.postgresql.value)
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False, default=5432)
    username = Column(String(255), nullable=False)
    password_enc = Column(Text, nullable=False, default="")
    database = Column(String(255), nullable=False)
    db_schema = Column(String(128), default="public", nullable=False)
    ssl = Column(String(16), default="prefer", nullable=False)
    permission_rules = Column(JSON, default=dict)
    permission_source_id = Column(String(36), ForeignKey("data_sources.id"), nullable=True)
    semantic_model = Column(JSON, default=dict)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=True, index=True)
    employee_id = Column(String(36), ForeignKey("digital_employees.id"), nullable=True)
    chat_enabled = Column(Boolean, default=True, nullable=False)
    report_enabled = Column(Boolean, default=True, nullable=False)
    status = Column(SAEnum(DataSourceStatus), default=DataSourceStatus.active, nullable=False)
    metadata_ = Column("metadata", JSON, default=dict)

    tables = relationship(
        "DataSourceTable",
        back_populates="data_source",
        cascade="all, delete-orphan",
        foreign_keys="DataSourceTable.data_source_id",
    )


class DataSourceTable(Base, TimestampMixin):
    __tablename__ = "data_source_tables"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    data_source_id = Column(String(36), ForeignKey("data_sources.id"), nullable=False, index=True)
    table_name = Column(String(255), nullable=False)
    role = Column(SAEnum(DataSourceTableRole), nullable=False, default=DataSourceTableRole.data)
    object_type = Column(SAEnum(DataSourceObjectType), nullable=False, default=DataSourceObjectType.table)
    column_meta = Column(JSON, default=dict)
    join_keys = Column(JSON, default=dict)
    sample_rows = Column(JSON, default=list)

    data_source = relationship("DataSource", back_populates="tables", foreign_keys=[data_source_id])


class DataAskAuditLog(Base, TimestampMixin):
    __tablename__ = "data_ask_audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    data_source_id = Column(String(36), ForeignKey("data_sources.id"), nullable=False, index=True)
    question = Column(Text, nullable=True)
    sql_text = Column(Text, nullable=False)
    row_count = Column(Integer, default=0)
    success = Column(Boolean, default=True, nullable=False)
    error_message = Column(Text, nullable=True)


class DataAskGoldenQuery(Base, TimestampMixin):
    __tablename__ = "data_ask_golden_queries"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    data_source_id = Column(String(36), ForeignKey("data_sources.id"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    sql_text = Column(Text, nullable=False)
    confirmed_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    use_count = Column(Integer, default=1, nullable=False)


class DataSourceGrant(Base, TimestampMixin):
    """Per-user access to a data source (问数 / Excel 解析)."""

    __tablename__ = "data_source_grants"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    data_source_id = Column(String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    can_ask = Column(Boolean, default=True, nullable=False)
    can_manage = Column(Boolean, default=False, nullable=False)


class ExcelParseTemplate(Base, TimestampMixin):
    __tablename__ = "excel_parse_templates"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(32), nullable=False, default="BS")
    sheet_mappings = Column(JSON, default=list)
    is_global = Column(Boolean, default=False, nullable=False)
    description = Column(Text, nullable=True)


class ExcelParseJob(Base, TimestampMixin):
    __tablename__ = "excel_parse_jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    template_id = Column(String(36), ForeignKey("excel_parse_templates.id"), nullable=False, index=True)
    data_source_id = Column(String(36), ForeignKey("data_sources.id"), nullable=True, index=True)
    folder_path = Column(Text, nullable=True)
    recursive = Column(Boolean, default=True, nullable=False)
    output_filename = Column(String(255), nullable=True)
    status = Column(String(32), default="pending", nullable=False)
    progress = Column(Integer, default=0, nullable=False)
    row_count = Column(Integer, default=0, nullable=False)
    success_count = Column(Integer, default=0, nullable=False)
    failed_count = Column(Integer, default=0, nullable=False)
    output_file = Column(String(255), nullable=True)
    columns = Column(JSON, default=list)
    result_preview = Column(JSON, default=list)
    error_logs = Column(JSON, default=list)
    error_message = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class SystemSetting(Base, TimestampMixin):
    __tablename__ = "system_settings"

    key = Column(String(64), primary_key=True)
    value = Column(JSON, default=dict)


# ──────────────────────────────────────────────
# ML Evolution（阶段一）：模型注册表 / 训练日志
# 表由 init_db 的 create_all 在应用启动时自动创建
# ──────────────────────────────────────────────
from sqlalchemy import UniqueConstraint  # noqa: E402


class MLModelRegistry(Base, TimestampMixin):
    """模型注册表：每个 (数据源, 模型类型) 多版本，仅一个 production"""
    __tablename__ = "ml_model_registry"
    __table_args__ = (
        UniqueConstraint("data_source_id", "model_type", "version", name="uq_ml_model_version"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    data_source_id = Column(String(64), nullable=False, index=True)
    model_type = Column(String(20), nullable=False)  # lstm / cnn1d
    version = Column(Integer, nullable=False)
    file_path = Column(String(500), nullable=False)
    metrics = Column(JSON, nullable=True)  # {"mae":..,"r2":..,"val_rows":..}
    status = Column(String(20), default="candidate", nullable=False, index=True)  # candidate/production/retired
    trained_rows = Column(Integer, nullable=True)


class MLTrainingLog(Base, TimestampMixin):
    """训练日志：每轮训练全留痕，进化曲线数据源"""
    __tablename__ = "ml_training_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(Integer, nullable=True, index=True)
    data_source_id = Column(String(64), nullable=True, index=True)
    trigger_query = Column(String(200), nullable=True)
    sample_rows = Column(Integer, nullable=True)
    val_mae = Column(Float, nullable=True)
    val_r2 = Column(Float, nullable=True)
    promoted = Column(Boolean, default=False, nullable=False)
    duration_ms = Column(Integer, nullable=True)
    note = Column(String(500), nullable=True)


# ──────────────────────────────────────────────
# Agent Evolution（阶段一）：语义沉淀与信号采集
# 表由 init_db 的 create_all 在应用启动时自动创建
# data_source_id 统一 String(64) 不带 FK（对齐 ml_* 表风格，避免级联删除约束）
# ──────────────────────────────────────────────


class DsSchemaProfile(Base, TimestampMixin):
    """数据源 Schema 画像：字段含义/枚举/分布/质量报告（JSON 快照 + 版本）"""
    __tablename__ = "ds_schema_profile"

    id = Column(Integer, primary_key=True, autoincrement=True)
    data_source_id = Column(String(64), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(20), default="building", nullable=False, index=True)  # building/ready/failed
    trigger = Column(String(20), default="manual", nullable=False)  # manual/auto
    profile = Column(JSON, nullable=True)
    table_count = Column(Integer, nullable=True)
    column_count = Column(Integer, nullable=True)
    row_counts = Column(JSON, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)


class DsSemanticTerm(Base, TimestampMixin):
    """术语词典：业务词 <-> 字段/口径/同义词"""
    __tablename__ = "ds_semantic_term"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    data_source_id = Column(String(64), nullable=False, index=True)
    term = Column(String(255), nullable=False)
    definition = Column(Text, nullable=True)
    column_ref = Column(String(255), nullable=True)
    synonyms = Column(JSON, default=list)
    source = Column(String(20), default="manual", nullable=False)  # manual/auto
    use_count = Column(Integer, default=0, nullable=False)


class DsSemanticMetric(Base, TimestampMixin):
    """指标口径：公式 + 维度 + 默认过滤"""
    __tablename__ = "ds_semantic_metric"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    data_source_id = Column(String(64), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    expr = Column(Text, nullable=False)
    dimensions = Column(JSON, default=list)
    default_filters = Column(JSON, default=list)
    description = Column(Text, nullable=True)
    source = Column(String(20), default="manual", nullable=False)
    use_count = Column(Integer, default=0, nullable=False)


class AskTrace(Base, TimestampMixin):
    """问数轨迹：问题/改写/SQL/结果签名/各段耗时/命中示例"""
    __tablename__ = "ask_trace"

    id = Column(Integer, primary_key=True, autoincrement=True)
    data_source_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(36), nullable=True, index=True)
    question = Column(Text, nullable=True)
    standalone_question = Column(Text, nullable=True)
    sql_text = Column(Text, nullable=True)
    row_count = Column(Integer, nullable=True)
    success = Column(Boolean, default=True, nullable=False)
    error_message = Column(Text, nullable=True)
    analysis_mode = Column(String(20), nullable=True)  # sql/overview/ml/excel/clarification
    memory_hits = Column(Integer, default=0, nullable=False)
    duration_ms = Column(Integer, nullable=True)
    rewrite_ms = Column(Integer, nullable=True)
    gen_ms = Column(Integer, nullable=True)
    exec_ms = Column(Integer, nullable=True)
    analysis_ms = Column(Integer, nullable=True)
    result_signature = Column(String(64), nullable=True)
    clarification = Column(Boolean, default=False, nullable=False)
    cached = Column(Boolean, default=False, nullable=False)


class DataAskTreeNode(Base, TimestampMixin):
    """P1-D 发现树节点：把一次问答记录成树（意图分支 / 候选 SQL / 执行结果）。

    Dream 池的数据基础——P0-B 重放与 P2-E 做梦候选生成都依赖结构化轨迹。
    trace_id 关联 ask_trace.id；run_id 分组一次问答运行；parent_id 自引用成树。
    表由 init_db 的 create_all 在应用启动时自动创建。
    """
    __tablename__ = "data_ask_tree_node"

    id = Column(String(36), primary_key=True)
    data_source_id = Column(String(64), nullable=False, index=True)
    trace_id = Column(Integer, nullable=True, index=True)
    run_id = Column(String(64), nullable=False, index=True)
    parent_id = Column(String(36), nullable=True)
    node_kind = Column(String(20), nullable=False)  # root/intent/candidate/execution/result
    node_order = Column(Integer, nullable=False, default=0)
    payload = Column(JSON, nullable=True)


class AskFeedback(Base, TimestampMixin):
    """用户反馈：赞踩/纠错前后 SQL/保存示例标记"""
    __tablename__ = "ask_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(Integer, nullable=True, index=True)
    data_source_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(36), nullable=True, index=True)
    question = Column(Text, nullable=True)
    original_sql = Column(Text, nullable=True)
    corrected_sql = Column(Text, nullable=True)
    feedback_type = Column(String(20), nullable=False)  # like/dislike/correction/example
    comment = Column(Text, nullable=True)


class DataAskTrainTask(Base, TimestampMixin):
    """对话内训练任务：反馈触发的蒸馏作业状态（前端轮询回显训练进度）"""
    __tablename__ = "data_ask_train_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    data_source_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(36), nullable=True, index=True)
    kind = Column(String(20), nullable=False, default="example")  # example/template/rule
    status = Column(String(16), nullable=False, default="queued", index=True)  # queued/running/done/failed
    progress = Column(Integer, default=0, nullable=False)
    detail = Column(JSON, nullable=True)
    feedback_id = Column(Integer, nullable=True, index=True)
    error = Column(Text, nullable=True)


class AgentMetricDaily(Base, TimestampMixin):
    """训练度量日物化（P1）：每数据源每天一行，看板趋势数据源，与实时口径同函数计算"""
    __tablename__ = "agent_metric_daily"
    __table_args__ = (UniqueConstraint("data_source_id", "day", name="uq_metric_daily_ds_day"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    data_source_id = Column(String(64), nullable=False, index=True)
    day = Column(Date, nullable=False, index=True)
    feedback_total = Column(Integer, default=0, nullable=False)
    feedback_like = Column(Integer, default=0, nullable=False)
    feedback_dislike = Column(Integer, default=0, nullable=False)
    feedback_correction = Column(Integer, default=0, nullable=False)
    feedback_example = Column(Integer, default=0, nullable=False)
    golden_created = Column(Integer, default=0, nullable=False)
    trace_total = Column(Integer, default=0, nullable=False)
    trace_success = Column(Integer, default=0, nullable=False)
    first_pass_rate = Column(Float, nullable=True)
    memory_hit_rate = Column(Float, nullable=True)
    eval_pass_rate = Column(Float, nullable=True)
    eval_overall = Column(Float, nullable=True)


class MemoryHitLog(Base, TimestampMixin):
    """记忆命中归因日志（P2）：每次问数命中了哪些金标/示例记忆、是否被用户采纳。

    归因因果链：命中记忆 → 用户反馈采纳（adopted）→ 评测通过率变化，
    支撑「本轮训练使评测通过率提升 X%」的可复算结论。
    """

    __tablename__ = "memory_hit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(Integer, nullable=True, index=True)
    data_source_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(36), nullable=True)
    question = Column(Text, nullable=True)
    matched = Column(JSON, default=list)  # [{ref, ref_type, question, score}]
    match_score = Column(Float, nullable=True)  # 命中的最高相似分
    adopted = Column(Boolean, nullable=True, index=True)  # None=未反馈 True=正反馈 False=点踩


# ──────────────────────────────────────────────
# Agent Evolution（阶段二 L2）：知识蒸馏 —— 示例库 / 分析模板 / 业务规则
# 表由 init_db 的 create_all 在应用启动时自动创建
# data_source_id 统一 String(64) 不带 FK（对齐 ml_* 与阶段一表风格，避免级联删除约束）
# ──────────────────────────────────────────────


class AskExample(Base, TimestampMixin):
    """示例库：正/负例问答对（向量入 Milvus，本表为元数据与治理）"""

    __tablename__ = "ask_example"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    data_source_id = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    sql_text = Column(Text, nullable=False)
    kind = Column(String(16), nullable=False, default="positive", index=True)  # positive/negative
    source = Column(String(20), default="feedback", nullable=False)  # like/example/correction/dislike/manual
    quality = Column(Float, default=0.0, nullable=False)
    trace_id = Column(Integer, nullable=True, index=True)
    use_count = Column(Integer, default=0, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    indexed = Column(Boolean, default=False, nullable=False)  # 是否已向量化入 Milvus
    note = Column(String(500), nullable=True)


class AskTemplate(Base, TimestampMixin):
    """分析模板：高频问题聚类蒸馏出的可复用分析框架"""

    __tablename__ = "ask_template"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    data_source_id = Column(String(64), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    intent = Column(String(255), nullable=True)
    framework = Column(Text, nullable=True)
    sample_questions = Column(JSON, default=list)
    keywords = Column(JSON, default=list)
    member_count = Column(Integer, default=0, nullable=False)
    hit_count = Column(Integer, default=0, nullable=False)
    status = Column(String(20), default="draft", nullable=False, index=True)  # draft/active
    source = Column(String(20), default="auto", nullable=False)  # auto/manual


class DsBusinessRule(Base, TimestampMixin):
    """业务规则：从纠错记录蒸馏的默认过滤 / 口径 / 术语偏好"""

    __tablename__ = "ds_business_rule"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    data_source_id = Column(String(64), nullable=False, index=True)
    rule_type = Column(String(20), nullable=False)  # caliber/terminology/filter
    name = Column(String(255), nullable=False)
    rule_text = Column(Text, nullable=False)
    applies_to = Column(String(255), nullable=True)
    payload = Column(JSON, nullable=True)  # caliber:{expr,dimensions,default_filters}; terminology:{column_ref,synonyms}; filter:{note}
    evidence = Column(JSON, nullable=True)  # {"corrections":[...], "samples":[...]}
    confidence = Column(Float, default=0.0, nullable=False)
    status = Column(String(20), default="candidate", nullable=False, index=True)  # candidate/active/rejected
    source = Column(String(20), default="auto", nullable=False)
    materialized_id = Column(String(36), nullable=True)  # 写回语义层产生的 term/metric id


# ──────────────────────────────────────────────
# Agent Evolution（阶段三 L3）：智能体工厂 —— 配置版本化 / 发布与灰度
# 表由 init_db 的 create_all 在应用启动时自动创建
# agent_id / data_source_id 统一 String 不带 FK（对齐 ml_* 与阶段一/二表风格，避免级联删除约束）
# ──────────────────────────────────────────────


class AgentVersion(Base, TimestampMixin):
    """智能体配置版本快照：每次工厂生成 / 手工编辑 / 回滚产生新版本"""

    __tablename__ = "agent_version"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(36), nullable=False, index=True)
    data_source_id = Column(String(64), nullable=True, index=True)
    version = Column(Integer, nullable=False, default=1)
    spec = Column(JSON, nullable=False)  # 完整配置快照：name/role/goal/backstory/temperature/tools_config/skills_config/memory_config/metadata
    coach = Column(JSON, nullable=True)  # 生成依据：养成画像 / 能力匹配 / 缺口
    source = Column(String(20), default="factory", nullable=False)  # factory/manual/feedback/rollback
    note = Column(String(500), nullable=True)
    status = Column(String(20), default="candidate", nullable=False, index=True)  # candidate/production/retired


class AgentRelease(Base, TimestampMixin):
    """智能体版本发布与灰度记录：发布某个版本（全量 / 灰度白名单）"""

    __tablename__ = "agent_release"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    agent_id = Column(String(36), nullable=False, index=True)
    version_id = Column(Integer, nullable=False, index=True)
    version = Column(Integer, nullable=False)
    scope = Column(String(20), default="full", nullable=False)  # full/gray
    gray_users = Column(JSON, default=list)  # 灰度白名单 user_id 列表
    active = Column(Boolean, default=True, nullable=False)
    released_by = Column(String(36), nullable=True)
    note = Column(String(500), nullable=True)



# ──────────────────────────────────────────────
# Agent Evolution 阶段四 L4：回归评估与持续进化
# 表由 init_db 的 create_all 在应用启动时自动创建
# agent_id / data_source_id 统一 String 不带 FK（对齐 ml_* 与阶段一/二表风格，避免级联删除约束）
# ──────────────────────────────────────────────

class AgentEvalSet(Base, TimestampMixin):
    """回归测试集（考题库）：golden 查询 + 正例示例 + 人工补充，全部来自真实交互"""

    __tablename__ = "agent_eval_set"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    data_source_id = Column(String(64), nullable=False, index=True)
    agent_id = Column(String(36), nullable=True, index=True)
    question = Column(Text, nullable=False)
    expected_sql = Column(Text, nullable=True)
    expected_signature = Column(String(64), nullable=True)  # 期望结果签名（评估路径真实回填）
    signature_source = Column(String(16), nullable=True)    # 基线来源：trace（真实轨迹）/ eval（评估路径）
    expected_row_count = Column(Integer, nullable=True)
    expected_chart = Column(String(20), nullable=True)
    category = Column(String(20), default="aggregation", nullable=False, index=True)
    source = Column(String(20), default="manual", nullable=False)  # golden/example/manual
    difficulty = Column(String(20), default="medium", nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    note = Column(String(500), nullable=True)


class AgentEvalRun(Base, TimestampMixin):
    """回归评估运行：一轮考题执行 + 指标汇总 + 逐题明细快照"""

    __tablename__ = "agent_eval_run"

    id = Column(Integer, primary_key=True, autoincrement=True)
    data_source_id = Column(String(64), nullable=False, index=True)
    agent_id = Column(String(36), nullable=True, index=True)
    agent_version_id = Column(Integer, nullable=True)
    agent_version = Column(Integer, nullable=True)
    trigger = Column(String(20), default="manual", nullable=False)  # manual/weekly/release
    status = Column(String(20), default="pending", nullable=False, index=True)  # pending/running/done/failed
    total = Column(Integer, default=0, nullable=False)
    passed = Column(Integer, default=0, nullable=False)
    sql_success_rate = Column(Float, nullable=True)
    consistency_rate = Column(Float, nullable=True)
    judge_score = Column(Float, nullable=True)
    overall_score = Column(Float, nullable=True)
    weak_categories = Column(JSON, default=list)
    items = Column(JSON, default=list)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    note = Column(String(500), nullable=True)


class AgentQualityScore(Base, TimestampMixin):
    """智能体质量分时序：每轮评估一条，质量看板趋势数据源"""

    __tablename__ = "agent_quality_score"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(36), nullable=True, index=True)
    data_source_id = Column(String(64), nullable=False, index=True)
    run_id = Column(Integer, nullable=False, index=True)
    score = Column(Float, nullable=False, default=0.0)
    metrics = Column(JSON, default=dict)


class DataAskReplayEpisode(Base, TimestampMixin):
    """P1-B 评测轨迹冻结池：每轮评估逐题冻结为不可变剧集（对应 DREAM-RSI trace_pool）。

    只追加、不更新、不删除：晋升判定时的逐时期不回归门槛读取本表，
    防止「新版在新题上好、在老题上崩」的跨期回归被总均分掩盖。
    """

    __tablename__ = "data_ask_replay_episode"

    id = Column(Integer, primary_key=True, autoincrement=True)
    data_source_id = Column(String(64), nullable=False, index=True)
    run_id = Column(Integer, nullable=False, index=True)       # 来源 agent_eval_run.id
    run_kind = Column(String(16), nullable=True, index=True)   # baseline/candidate/None(手动评估)
    agent_version_id = Column(Integer, nullable=True)
    agent_version = Column(Integer, nullable=True)
    era = Column(String(10), nullable=False, index=True)       # 时期键：YYYY-MM-DD（同一轮双候选同 era）
    question_id = Column(String(36), nullable=False, index=True)  # agent_eval_set.id 快照
    question = Column(Text, nullable=False)                    # 考题文本快照（防考题改词后失真）
    category = Column(String(20), nullable=True)
    budget_retries = Column(Integer, nullable=True)            # P1-A 预算点：SQL 修复重试上限（None=默认）
    sql_ok = Column(Boolean, nullable=False, default=False)
    consistency = Column(String(16), nullable=True)            # exact/baseline/mismatch/None
    judge_score = Column(Float, nullable=True)
    item_score = Column(Float, nullable=True)                  # 逐题归一化质量分 ∈[0,1]（与 overall 同权重口径）
    duration_ms = Column(Integer, nullable=True)


class AgentSocraticTrace(Base, TimestampMixin):
    """苏格拉底反问轨迹：clarify 事件与澄清收敛留痕，反问质量蒸馏数据源"""

    __tablename__ = "agent_socratic_trace"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(64), nullable=False, index=True)
    agent_id = Column(String(64), nullable=True, index=True)
    user_id = Column(String(64), nullable=True, index=True)
    question = Column(Text, nullable=False)
    clarify_questions = Column(JSON, default=list)
    round = Column(Integer, nullable=False, default=1)
    resolved = Column(Boolean, nullable=False, default=False)



class SocraticEvalSet(Base, TimestampMixin):
    """苏格拉底反问考题库：模糊问题(期望反问) + 明确问题(期望直答)，用于回归评估反问质量"""

    __tablename__ = "socratic_eval_set"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    agent_id = Column(String(36), nullable=True, index=True)  # None=通用考题
    question = Column(Text, nullable=False)
    expected_behavior = Column(String(10), nullable=False, index=True)  # clarify / direct
    expected_domains = Column(JSON, default=list)  # 期望反问维度关键词
    difficulty = Column(String(20), default="medium", nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    note = Column(String(500), nullable=True)
    source = Column(String(20), default="manual", nullable=False)


class SocraticEvalRun(Base, TimestampMixin):
    """苏格拉底反问评估运行：一轮考题执行 + 指标汇总 + 逐题明细"""

    __tablename__ = "socratic_eval_run"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(36), nullable=True, index=True)
    status = Column(String(20), default="pending", nullable=False, index=True)
    total = Column(Integer, default=0, nullable=False)
    passed = Column(Integer, default=0, nullable=False)
    clarify_accuracy = Column(Float, nullable=True)   # 模糊问题正确触发反问比例
    direct_accuracy = Column(Float, nullable=True)    # 明确问题正确直答比例 (=1-误反问率)
    avg_rounds = Column(Float, nullable=True)
    items = Column(JSON, default=list)
    duration_ms = Column(Integer, nullable=True)
    note = Column(String(500), nullable=True)


# ──────────────────────────────────────────────
# 经营分析看板技能（Dashboard Skill）：看板产物 + 阶段事件
# 表由 init_db 的 create_all 在应用启动时自动创建
# ──────────────────────────────────────────────

class DashboardArtifact(Base, TimestampMixin):
    """看板产物：一次生成任务的完整状态与自包含 HTML。

    html 列为大文本（内嵌 echarts ~1MB），列表查询应避免 select 该列。
    snapshot 留档数据快照供审计复核（锚点可复算）。
    """
    __tablename__ = "dashboard_artifacts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    data_source_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(36), nullable=True, index=True)
    conversation_id = Column(String(36), nullable=True, index=True)
    template = Column(String(64), nullable=False, default="retail_overview")
    title = Column(String(255), nullable=False, default="")
    status = Column(String(16), nullable=False, default="queued", index=True)  # queued/running/done/failed
    stage = Column(String(32), nullable=True)   # intent/schema_probe/metric_fetch/anchor_check/render/verify/done
    progress = Column(Integer, default=0, nullable=False)
    period_start = Column(String(10), nullable=True)
    period_end = Column(String(10), nullable=True)
    kpis = Column(JSON, default=list)           # 卡片摘要 [{label, value}]
    anchor_status = Column(String(8), nullable=True)  # pass/warn/fail
    anchor_detail = Column(JSON, default=dict)
    snapshot = Column(JSON, nullable=True)      # 数据快照（审计复核）
    html = Column(Text, nullable=True)          # 自包含 HTML
    verify_report = Column(JSON, default=dict)
    error = Column(Text, nullable=True)
    message_id = Column(String(36), nullable=True)  # 卡片消息 id


class DashboardEvent(Base, TimestampMixin):
    """看板生成阶段事件（SSE 推送与留痕）。"""
    __tablename__ = "dashboard_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dashboard_id = Column(String(36), nullable=False, index=True)
    stage = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False)  # start/ok/warn/fail
    detail = Column(JSON, default=dict)
