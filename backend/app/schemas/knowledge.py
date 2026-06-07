from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime

from app.db.models import KBStatus


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = Field(default=1000, ge=100, le=8000)
    chunk_overlap: int = Field(default=200, ge=0, le=1000)


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    status: KBStatus
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    document_count: int
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


class SearchResult(BaseModel):
    content: str
    score: float
    document_id: str
    document_name: str
    chunk_index: int
    metadata: dict[str, Any] = {}
