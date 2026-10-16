from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime

from app.db.models import KBStatus


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    embedding_model: str = "nomic-embed-text"
    chunk_size: int = Field(default=1000, ge=100, le=8000)
    chunk_overlap: int = Field(default=200, ge=0, le=1000)


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None


class KnowledgeGrantIn(BaseModel):
    grantee_type: str
    grantee_id: str


class KnowledgeAccessUpdate(BaseModel):
    visibility: str = "private"
    grants: list[KnowledgeGrantIn] = []


class KnowledgeGrantOut(BaseModel):
    grantee_type: str
    grantee_id: str
    label: str


class KnowledgeAccessResponse(BaseModel):
    visibility: str
    can_manage: bool
    grants: list[KnowledgeGrantOut] = []


class KnowledgeShareTargets(BaseModel):
    users: list[dict[str, Optional[str]]] = []
    departments: list[dict[str, str]] = []


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    status: KBStatus
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    document_count: int
    source_type: str = "local"
    visibility: str = "private"
    can_manage: bool = False
    grant_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentResponse(BaseModel):
    id: str
    knowledge_base_id: str
    filename: str
    file_type: str
    file_size: Optional[int]
    status: KBStatus
    chunk_count: int
    stage: Optional[str] = None
    stages: dict[str, str] = {}
    stage_error: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentChunkResponse(BaseModel):
    chunk_index: int
    content: str


class DocumentContentResponse(BaseModel):
    id: str
    filename: str
    file_type: str
    content: str
    source: str
    chunk_count: int
    chunks: list[DocumentChunkResponse] = []


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    score_threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class FaqEntryIn(BaseModel):
    standard_question: str = Field(..., min_length=1, max_length=500)
    similar_questions: list[str] = []
    negative_questions: list[str] = []
    answer: str = Field(..., min_length=1)
    enabled: bool = True


class FaqEntryOut(BaseModel):
    id: str
    standard_question: str
    similar_questions: list[str] = []
    negative_questions: list[str] = []
    answer: str
    enabled: bool = True


class WecomDocSourceIn(BaseModel):
    enabled: bool = False
    corp_id: str = ""
    secret: str = ""
    doc_ids: list[str] = []


class WecomDocSourceOut(BaseModel):
    enabled: bool = False
    corp_id: str = ""
    secret_set: bool = False
    doc_ids: list[str] = []
    last_status: str = ""
    last_error: str = ""


class SearchResult(BaseModel):
    content: str
    score: float
    document_id: str
    document_name: str
    chunk_index: int
    metadata: dict[str, Any] = {}
