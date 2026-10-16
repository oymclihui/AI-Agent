"""Official chat endpoints for DeepSeek, Qianwen, and Zhipu."""
from __future__ import annotations  # noqa: I001

from typing import Any, Optional

PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "default_base_url": "https://api.deepseek.com",
        "base_urls": ["https://api.deepseek.com"],
        "models": [
            {"id": "deepseek-v4-pro", "label": "DeepSeek Pro"},
            {"id": "deepseek-flash", "label": "DeepSeek Flash"},
        ],
    },
    {
        "id": "qwen",
        "name": "千问",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "base_urls": [
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "https://maas.qianwenaiapi.com/compatible-mode/v1",
        ],
        "models": [
            {"id": "qwen-plus", "label": "千问 Plus"},
            {"id": "qwen-max", "label": "千问 Max"},
            {"id": "qwen-turbo", "label": "千问 Turbo"},
            {"id": "qwen3.8-flash", "label": "千问 3.8 Flash"},
            {"id": "qwen3.8-max", "label": "千问 3.8 Max"},
        ],
    },
    {
        "id": "glm",
        "name": "智谱",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "base_urls": ["https://open.bigmodel.cn/api/paas/v4"],
        "models": [
            {"id": "glm-5.3", "label": "GLM-5.3"},
            {"id": "glm-4.7", "label": "GLM-4.7"},
            {"id": "glm-4.7-flash", "label": "GLM-4.7 Flash"},
        ],
    },
]

_BY_ID = {item["id"]: item for item in PROVIDERS}
OPENAI_COMPAT_PROVIDERS = frozenset({"openai", "deepseek", "qwen", "glm"})


def _clean_url(url: Optional[str]) -> str:
    return (url or "").strip().rstrip("/")


def provider_of(provider: Optional[str]) -> Optional[dict]:
    return _BY_ID.get((provider or "").strip().lower())


def normalize_catalog_choice(
    provider: str,
    model_id: Optional[str],
    base_url: Optional[str],
    *,
    require_model: bool,
):
    """Return provider, model id, and an official base URL. Reject anything else."""
    item = provider_of(provider)
    if not item:
        raise ValueError("只能选择 DeepSeek、千问或智谱")
    model = (model_id or "").strip()
    known = {row["id"] for row in item["models"]}
    if require_model and model not in known:
        raise ValueError("请从目录中选择模型")
    if model and model not in known:
        raise ValueError("请从目录中选择模型")
    allowed = {_clean_url(url) for url in item["base_urls"]}
    chosen = _clean_url(base_url) or _clean_url(item["default_base_url"])
    if chosen not in allowed:
        raise ValueError("接口地址必须是该厂商的官方地址")
    return item["id"], (model or None), chosen


async def probe_official_chat(base_url: str, model_id: str, api_key: str) -> tuple[bool, str]:
    import httpx

    url = base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model_id,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url,
                json=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
    except Exception as exc:
        return False, f"无法连接接口：{type(exc).__name__}"
    if resp.status_code >= 400:
        detail = resp.text[:180].replace(api_key, "***")
        return False, f"接口返回 {resp.status_code}：{detail}"
    return True, "连接成功"


def catalog_payload(enterprise_model_ids: set[str]) -> dict[str, Any]:
    providers = []
    for item in PROVIDERS:
        models = []
        for row in item["models"]:
            models.append({
                "id": row["id"],
                "label": row["label"],
                "enterprise_ready": row["id"] in enterprise_model_ids,
            })
        providers.append({
            "id": item["id"],
            "name": item["name"],
            "default_base_url": item["default_base_url"],
            "base_urls": list(item["base_urls"]),
            "models": models,
        })
    return {"providers": providers}
