from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any, Literal
from datetime import datetime
from enum import Enum

from app.schemas.agent import SkillBinding


class GroupChatConfig(BaseModel):
    agent_ids: list[str] = Field(..., min_length=2, max_length=6)
    moderator_agent_id: Optional[str] = None
    orchestration: Literal["round_robin", "hierarchical", "parallel", "debate"] = "round_robin"
    max_rounds: int = Field(default=2, ge=1, le=5)
    auto_synthesize: bool = True
    lang: str = "zh"


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"
    tool = "tool"


class ChatMessage(BaseModel):
    role: MessageRole
    content: str


class ConversationCreate(BaseModel):
    title: Optional[str] = None
    agent_id: Optional[str] = None
    workflow_id: Optional[str] = None
    knowledge_base_ids: list[str] = []
    skills_config: list[SkillBinding] = []
    memory_type: str = "buffer"
    system_prompt: Optional[str] = None
    model_config_id: Optional[str] = None
    connector_id: Optional[str] = None
    web_search_enabled: bool = False
    chat_mode: Literal["single", "group", "data_ask"] = "single"
    group_config: Optional[GroupChatConfig] = None
    data_source_id: Optional[str] = None


class ConversationContextUpdate(BaseModel):
    agent_id: Optional[str] = None
    knowledge_base_ids: Optional[list[str]] = None
    skills_config: Optional[list[SkillBinding]] = None
    model_config_id: Optional[str] = None
    connector_id: Optional[str] = None
    web_search_enabled: Optional[bool] = None
    chat_mode: Optional[Literal["single", "group", "data_ask"]] = None
    group_config: Optional[GroupChatConfig] = None
    data_source_id: Optional[str] = None


class ConversationResponse(BaseModel):
    id: str
    title: Optional[str]
    agent_id: Optional[str]
    workflow_id: Optional[str]
    knowledge_base_ids: list[str] = []
    skills_config: list[dict] = []
    memory_type: str
    is_active: bool
    model_config_id: Optional[str] = None
    connector_id: Optional[str] = None
    web_search_enabled: bool = False
    chat_mode: str = "single"
    group_config: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("knowledge_base_ids", mode="before")
    @classmethod
    def _coerce_kb_ids(cls, v):
        return v if v is not None else []

    @field_validator("skills_config", mode="before")
    @classmethod
    def _coerce_skills(cls, v):
        return v if v is not None else []

    @classmethod
    def from_conversation(cls, conv) -> "ConversationResponse":
        meta = conv.metadata_ or {}
        return cls(
            id=conv.id,
            title=conv.title,
            agent_id=conv.agent_id,
            workflow_id=conv.workflow_id,
            knowledge_base_ids=conv.knowledge_base_ids or [],
            skills_config=conv.skills_config or [],
            memory_type=conv.memory_type,
            is_active=conv.is_active,
            model_config_id=meta.get("model_config_id"),
            connector_id=meta.get("connector_id"),
            web_search_enabled=bool(meta.get("web_search_enabled")),
            chat_mode=str(meta.get("chat_mode") or "single"),
            group_config=meta.get("group"),
            created_at=conv.created_at,
            updated_at=conv.updated_at,
        )

    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1)
    stream: bool = False


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: MessageRole
    content: str
    tool_calls: Optional[list[dict]] = None
    token_usage: Optional[dict] = None
    metadata_: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="metadata_",
        serialization_alias="metadata",
    )
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    agent_id: Optional[str] = None
    knowledge_base_ids: list[str] = []
    stream: bool = False
    context: Optional[dict[str, Any]] = None
    model_config_id: Optional[str] = None
    connector_id: Optional[str] = None
    web_search_enabled: Optional[bool] = None


class SuggestQuestionsResponse(BaseModel):
    questions: list[str]
    source: str = "llm"


class TranscribeResponse(BaseModel):
    text: str
    source: str = "ollama"


class SaveAsSkillRequest(BaseModel):
    title: Optional[str] = None


class SaveToKnowledgeRequest(BaseModel):
    kb_id: Optional[str] = None
    kb_name: Optional[str] = None


class DeleteOkResponse(BaseModel):
    ok: bool = True
    deleted: int = 1


class DepositSuggestRequest(BaseModel):
    lang: str = "zh"


class DepositSuggestionItem(BaseModel):
    type: str
    recommended: bool = False
    title: Optional[str] = None
    reason: str = ""
    confidence: float = 0.0


class DepositTaskPreview(BaseModel):
    name: str = ""
    schedule_type: str = "cron"
    cron_expression: Optional[str] = None
    schedule_label: Optional[str] = None
    prompt_preview: Optional[str] = None


class DepositDraftPreview(BaseModel):
    skill_title: Optional[str] = None
    knowledge_title: Optional[str] = None
    agent_name: Optional[str] = None
    employee_name: Optional[str] = None
    employee_title: Optional[str] = None
    employee_description: Optional[str] = None
    tasks: list[DepositTaskPreview] = []


class DepositSuggestResponse(BaseModel):
    worth_deposit: bool = False
    draft_id: Optional[str] = None
    suggestions: list[DepositSuggestionItem] = []
    draft: Optional[DepositDraftPreview] = None


class DepositConfirmRequest(BaseModel):
    draft_id: str
    types: list[str] = Field(..., min_length=1)
    activate_employee: bool = True
    kb_id: Optional[str] = None
    kb_name: Optional[str] = None
    skill_title: Optional[str] = None


class DepositConfirmResponse(BaseModel):
    skill_id: Optional[str] = None
    knowledge_base_id: Optional[str] = None
    agent_id: Optional[str] = None
    employee_id: Optional[str] = None
    tasks_created: int = 0
