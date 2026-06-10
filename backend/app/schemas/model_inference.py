"""Common LLM inference parameters (OpenAI / Anthropic / Ollama / Azure compatible)."""
from typing import Optional
from pydantic import BaseModel, Field


class ModelInferenceParams(BaseModel):
    temperature: Optional[float] = Field(None, ge=0, le=2, description="Sampling temperature")
    top_p: Optional[float] = Field(None, ge=0, le=1, description="Nucleus sampling")
    top_k: Optional[int] = Field(None, ge=0, le=500, description="Top-k sampling (Anthropic, Ollama)")
    max_tokens: Optional[int] = Field(None, ge=1, le=128_000, description="Max output tokens")
    frequency_penalty: Optional[float] = Field(None, ge=-2, le=2, description="OpenAI / Azure")
    presence_penalty: Optional[float] = Field(None, ge=-2, le=2, description="OpenAI / Azure")
    repetition_penalty: Optional[float] = Field(None, ge=0, le=2, description="Ollama repeat penalty")
    stop: Optional[list[str]] = Field(None, description="Stop sequences")
    seed: Optional[int] = Field(None, ge=0, description="Random seed for reproducibility")
    timeout: Optional[float] = Field(None, ge=1, le=600, description="Request timeout (seconds)")
    num_ctx: Optional[int] = Field(None, ge=512, le=2_000_000, description="Ollama context window override")

    def merged_dict(self) -> dict:
        return self.model_dump(exclude_none=True)


INFERENCE_CONFIG_KEY = "inference"


def extract_inference_params(config: dict | None) -> ModelInferenceParams:
    raw = (config or {}).get(INFERENCE_CONFIG_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    return ModelInferenceParams.model_validate(raw)


def attach_inference_to_config(config: dict | None, params: ModelInferenceParams | None) -> dict:
    out = dict(config or {})
    if params is None:
        return out
    merged = params.merged_dict()
    if merged:
        out[INFERENCE_CONFIG_KEY] = merged
    elif INFERENCE_CONFIG_KEY in out:
        del out[INFERENCE_CONFIG_KEY]
    return out
