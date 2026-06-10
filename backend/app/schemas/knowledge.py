from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Any, Literal
from datetime import datetime

from app.db.models import KBStatus
from app.knowledge.byd_kms import DEFAULT_BYD_KMS_URL


class BydKmsConfigInput(BaseModel):
    api_url: str = Field(default=DEFAULT_BYD_KMS_URL, min_length=8, max_length=512)
    user_id: str = Field(..., min_length=1, max_length=128)
    api_key: Optional[str] = Field(default=None, max_length=512)

    @field_validator("api_url", "user_id", mode="before")
    @classmethod
    def strip_required(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v


class BydKmsConfigPublic(BaseModel):
    api_url: str
    user_id: str
    has_api_key: bool = False


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    source_type: Literal["local", "byd_kms"] = "local"
    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = Field(default=1000, ge=100, le=8000)
    chunk_overlap: int = Field(default=200, ge=0, le=1000)
    byd_kms: Optional[BydKmsConfigInput] = None

    @model_validator(mode="after")
    def require_byd_config(self) -> "KnowledgeBaseCreate":
        if self.source_type == "byd_kms" and not self.byd_kms:
            raise ValueError("byd_kms configuration is required when source_type is byd_kms")
        return self


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    byd_kms: Optional[BydKmsConfigInput] = None


class BydKmsTestRequest(BaseModel):
    api_url: str = Field(default=DEFAULT_BYD_KMS_URL, min_length=8, max_length=512)
    user_id: str = Field(..., min_length=1, max_length=128)
    api_key: Optional[str] = None
    test_query: str = Field(default="你好", min_length=1, max_length=500)


class BydKmsTestResponse(BaseModel):
    ok: bool
    message: str
    latency_ms: int = 0
    status_code: Optional[int] = None
    preview: str = ""
    result_count: int = 0


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
    byd_kms: Optional[BydKmsConfigPublic] = None
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
