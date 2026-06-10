from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from enum import Enum


class AgentStatus(str, Enum):
    active = "active"
    inactive = "inactive"


class ToolConfig(BaseModel):
    tool_name: str
    config: dict[str, Any] = {}


class SkillBinding(BaseModel):
    skill_id: str
    always_load: bool = True
    priority: int = 0


class MemoryConfig(BaseModel):
    type: str = "buffer"  # buffer | summary | vector
    max_tokens: int = 4000
    k: int = 10  # for buffer memory: keep last k messages


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    role: str = Field(..., min_length=1, max_length=255)
    goal: str = Field(..., min_length=1)
    backstory: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_iterations: int = Field(default=10, ge=1, le=50)
    tools_config: list[ToolConfig] = []
    skills_config: list[SkillBinding] = []
    memory_config: MemoryConfig = MemoryConfig()
    metadata_: dict[str, Any] = Field(default={}, alias="metadata")

    class Config:
        populate_by_name = True


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    goal: Optional[str] = None
    backstory: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    temperature: Optional[float] = None
    max_iterations: Optional[int] = None
    tools_config: Optional[list[ToolConfig]] = None
    skills_config: Optional[list[SkillBinding]] = None
    memory_config: Optional[MemoryConfig] = None
    status: Optional[AgentStatus] = None


class AgentResponse(BaseModel):
    id: str
    name: str
    role: str
    goal: str
    backstory: Optional[str]
    status: AgentStatus
    llm_provider: Optional[str]
    llm_model: Optional[str]
    temperature: float
    max_iterations: int
    tools_config: list[dict]
    skills_config: list[dict] = []
    memory_config: dict
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgentLibraryImportRequest(BaseModel):
    items: list[dict[str, str]] = Field(default_factory=list)
    overwrite: bool = False
    import_all: bool = False
    import_skills: bool = True


class AgentLibraryTemplate(BaseModel):
    source: str
    slug: str
    name: str
    description: str = ""
    division: str = "general"
    tags: list[str] = []


class AgentRunRequest(BaseModel):
    task: str = Field(..., min_length=1)
    context: Optional[dict[str, Any]] = None
    stream: bool = False
