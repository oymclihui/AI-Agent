from pydantic import BaseModel, Field
from typing import Optional, Any

from app.schemas.model_inference import ModelInferenceParams, attach_inference_to_config, extract_inference_params


class ModelConfigCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    provider: str = Field(..., min_length=1, max_length=64)
    model_id: str = Field(..., min_length=1, max_length=128)
    base_url: Optional[str] = Field(None, max_length=512)
    context_window: Optional[int] = Field(None, ge=1024, le=2_000_000)
    cost_per_1k_input: Optional[float] = Field(None, ge=0)
    cost_per_1k_output: Optional[float] = Field(None, ge=0)
    is_default: bool = False
    inference_params: ModelInferenceParams = Field(default_factory=ModelInferenceParams)
    config: dict[str, Any] = Field(default_factory=dict)


class ModelConfigUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    provider: Optional[str] = Field(None, min_length=1, max_length=64)
    model_id: Optional[str] = Field(None, min_length=1, max_length=128)
    base_url: Optional[str] = Field(None, max_length=512)
    context_window: Optional[int] = Field(None, ge=1024, le=2_000_000)
    cost_per_1k_input: Optional[float] = Field(None, ge=0)
    cost_per_1k_output: Optional[float] = Field(None, ge=0)
    is_default: Optional[bool] = None
    inference_params: Optional[ModelInferenceParams] = None
    config: Optional[dict[str, Any]] = None


class ModelConfigResponse(BaseModel):
    id: str
    name: str
    provider: str
    model_id: str
    base_url: Optional[str] = None
    is_default: bool
    is_active: bool
    context_window: Optional[int] = None
    cost_per_1k_input: Optional[float] = None
    cost_per_1k_output: Optional[float] = None
    inference_params: ModelInferenceParams = Field(default_factory=ModelInferenceParams)
    config: dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


def build_config_payload(
    config: dict | None,
    inference_params: ModelInferenceParams | dict | None,
) -> dict:
    if isinstance(inference_params, dict):
        inference_params = ModelInferenceParams.model_validate(inference_params)
    return attach_inference_to_config(config, inference_params)


def response_inference_params(config: dict | None) -> ModelInferenceParams:
    return extract_inference_params(config)


class ModelConnectionTestRequest(BaseModel):
    provider: str = Field(..., min_length=1, max_length=64)
    model_id: str = Field(..., min_length=1, max_length=128)
    base_url: Optional[str] = Field(None, max_length=512)


class ModelConnectionTestResponse(BaseModel):
    ok: bool
    message: str
    latency_ms: int = 0
    endpoint: Optional[str] = None
    preview: Optional[str] = None
