"""Map unified inference params to LangChain provider constructors."""
from typing import Any, Optional

from app.schemas.model_inference import ModelInferenceParams


def merge_inference(
    stored: ModelInferenceParams,
    overrides: Optional[dict[str, Any]] = None,
    temperature_override: Optional[float] = None,
) -> dict[str, Any]:
    merged = stored.merged_dict()
    if overrides:
        for key, value in overrides.items():
            if value is not None:
                merged[key] = value
    if temperature_override is not None:
        merged["temperature"] = temperature_override
    return merged


def build_openai_kwargs(params: dict[str, Any], streaming: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"streaming": streaming}
    if "temperature" in params:
        kwargs["temperature"] = params["temperature"]
    if "top_p" in params:
        kwargs["top_p"] = params["top_p"]
    if "max_tokens" in params:
        kwargs["max_tokens"] = params["max_tokens"]
    if "frequency_penalty" in params:
        kwargs["frequency_penalty"] = params["frequency_penalty"]
    if "presence_penalty" in params:
        kwargs["presence_penalty"] = params["presence_penalty"]
    if "stop" in params and params["stop"]:
        kwargs["stop"] = params["stop"]
    if "seed" in params:
        kwargs["seed"] = params["seed"]
    if "timeout" in params:
        kwargs["timeout"] = params["timeout"]
    return kwargs


def build_anthropic_kwargs(params: dict[str, Any], streaming: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"streaming": streaming}
    if "temperature" in params:
        kwargs["temperature"] = params["temperature"]
    if "top_p" in params:
        kwargs["top_p"] = params["top_p"]
    if "top_k" in params:
        kwargs["top_k"] = params["top_k"]
    if "max_tokens" in params:
        kwargs["max_tokens"] = params["max_tokens"]
    if "stop" in params and params["stop"]:
        kwargs["stop_sequences"] = params["stop"]
    if "timeout" in params:
        kwargs["default_request_timeout"] = params["timeout"]
    return kwargs


def build_ollama_kwargs(params: dict[str, Any], streaming: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"streaming": streaming}
    if "temperature" in params:
        kwargs["temperature"] = params["temperature"]
    if "top_p" in params:
        kwargs["top_p"] = params["top_p"]
    if "top_k" in params:
        kwargs["top_k"] = params["top_k"]
    if "max_tokens" in params:
        kwargs["num_predict"] = params["max_tokens"]
    if "repetition_penalty" in params:
        kwargs["repeat_penalty"] = params["repetition_penalty"]
    if "stop" in params and params["stop"]:
        kwargs["stop"] = params["stop"]
    if "seed" in params:
        kwargs["seed"] = params["seed"]
    if "timeout" in params:
        kwargs["timeout"] = params["timeout"]
    if "num_ctx" in params:
        kwargs["num_ctx"] = params["num_ctx"]
    return kwargs
