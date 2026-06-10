from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from enum import Enum


class SkillLibraryImportItem(BaseModel):
    source: str
    slug: str


class SkillLibraryImportRequest(BaseModel):
    items: list[SkillLibraryImportItem] = Field(..., min_length=1)
    overwrite: bool = False


class SkillLibraryTemplate(BaseModel):
    source: str
    slug: str
    path: str
    display_name: str
    description: str
    category: str
    tags: list[str] = []


class SkillStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class SkillResource(BaseModel):
    path: str
    kind: str = "markdown"  # markdown | script | reference
    content: str = ""


class SkillCreate(BaseModel):
    slug: Optional[str] = Field(None, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    instructions_md: str = Field(default="")
    status: SkillStatus = SkillStatus.draft
    scope: str = Field(default="global", max_length=32)
    auto_invoke: bool = False
    resources: list[SkillResource] = []
    tools_required: list[str] = []
    knowledge_base_ids: list[str] = []
    tags: list[str] = []
    metadata_: dict[str, Any] = Field(default={}, alias="metadata")

    class Config:
        populate_by_name = True


class SkillUpdate(BaseModel):
    slug: Optional[str] = Field(None, max_length=64)
    display_name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    instructions_md: Optional[str] = None
    status: Optional[SkillStatus] = None
    scope: Optional[str] = None
    auto_invoke: Optional[bool] = None
    resources: Optional[list[SkillResource]] = None
    tools_required: Optional[list[str]] = None
    knowledge_base_ids: Optional[list[str]] = None
    tags: Optional[list[str]] = None


class SkillResponse(BaseModel):
    id: str
    slug: str
    display_name: str
    description: str
    instructions_md: str
    status: SkillStatus
    scope: str
    auto_invoke: bool
    version: int
    resources: list[dict]
    tools_required: list[str]
    knowledge_base_ids: list[str]
    tags: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata")
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True
