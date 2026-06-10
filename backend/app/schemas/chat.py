from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any
from datetime import datetime
from enum import Enum


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
    memory_type: str = "buffer"
    system_prompt: Optional[str] = None


class ConversationResponse(BaseModel):
    id: str
    title: Optional[str]
    agent_id: Optional[str]
    workflow_id: Optional[str]
    knowledge_base_ids: list[str] = []
    memory_type: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("knowledge_base_ids", mode="before")
    @classmethod
    def _coerce_kb_ids(cls, v):
        return v if v is not None else []

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
