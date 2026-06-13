"""BYD corporate KMS RAG QA client (kms-api.byd.com)."""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

DEFAULT_BYD_KMS_URL = "https://kms-api.byd.com/open-api/1.0/llm/v1/rag-qa"
DEFAULT_TEST_QUERY = "你好"


class BydKmsError(Exception):
    def __init__(self, message: str, *, status_code: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def resolve_byd_kms_config(
    meta: Optional[dict],
    *,
    caller_kms_user_id: str | None = None,
    caller_api_url: str | None = None,
    caller_api_key: str | None = None,
) -> Optional[dict]:
    if not meta or meta.get("source_type") != "byd_kms":
        return None
    cfg = meta.get("byd_kms") or {}
    use_caller = cfg.get("use_caller_identity", True)

    if use_caller and caller_kms_user_id:
        user_id = caller_kms_user_id.strip()
    else:
        user_id = (cfg.get("user_id") or "").strip()

    api_url = (
        (caller_api_url or "").strip()
        or (cfg.get("api_url") or settings.BYD_KMS_DEFAULT_URL).strip()
    )
    if not user_id or not api_url:
        return None
    api_key = (
        (caller_api_key or "").strip()
        or (cfg.get("api_key") or settings.BYD_KMS_API_KEY or "").strip()
        or None
    )
    return {
        "api_url": api_url.rstrip("/"),
        "user_id": user_id,
        "api_key": api_key,
    }


def build_byd_kms_metadata(
    *,
    api_url: str,
    user_id: str,
    api_key: Optional[str] = None,
    existing: Optional[dict] = None,
) -> dict:
    prev = (existing or {}).get("byd_kms") or {}
    key = (api_key or "").strip() or prev.get("api_key") or settings.BYD_KMS_API_KEY or ""
    return {
        "source_type": "byd_kms",
        "byd_kms": {
            "api_url": (api_url or DEFAULT_BYD_KMS_URL).strip().rstrip("/"),
            "user_id": user_id.strip(),
            "use_caller_identity": True,
            **({"api_key": key} if key else {}),
        },
    }


def _headers(api_key: Optional[str]) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _request_payload(user_id: str, query: str) -> dict[str, Any]:
    return {
        "userId": user_id,
        "user_id": user_id,
        "question": query,
        "query": query,
    }


def _extract_text(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("content", "text", "answer", "chunk", "snippet", "document_content"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        nested = item.get("data")
        if nested is not None:
            return _extract_text(nested)
    return ""


def _parse_search_results(data: Any, query: str) -> list[dict]:
    if isinstance(data, str) and data.strip():
        return [{
            "content": data.strip(),
            "score": 1.0,
            "document_id": "byd-kms",
            "document_name": "API 知识库",
            "chunk_index": 0,
            "metadata": {"source": "byd_kms", "query": query},
        }]

    if not isinstance(data, dict):
        return []

    for key in ("answer", "content", "text", "response"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return [{
                "content": val.strip(),
                "score": 1.0,
                "document_id": "byd-kms",
                "document_name": "API 知识库",
                "chunk_index": 0,
                "metadata": {"source": "byd_kms", "query": query},
            }]

    chunks: list[Any] = []
    for key in ("chunks", "references", "docs", "documents", "results", "data", "items"):
        val = data.get(key)
        if isinstance(val, list):
            chunks = val
            break

    output: list[dict] = []
    for idx, item in enumerate(chunks):
        content = _extract_text(item)
        if not content:
            continue
        score = 1.0
        doc_name = "API 知识库"
        if isinstance(item, dict):
            score = float(item.get("score") or item.get("similarity") or item.get("relevance") or 1.0)
            doc_name = str(
                item.get("document_name")
                or item.get("docName")
                or item.get("title")
                or item.get("source")
                or doc_name
            )
        output.append({
            "content": content,
            "score": score,
            "document_id": str(item.get("document_id") or item.get("docId") or "byd-kms") if isinstance(item, dict) else "byd-kms",
            "document_name": doc_name,
            "chunk_index": idx,
            "metadata": {"source": "byd_kms", "query": query, "raw": item if isinstance(item, dict) else {}},
        })
    return output


async def call_byd_kms(
    *,
    api_url: str,
    user_id: str,
    query: str,
    api_key: Optional[str] = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    url = api_url.rstrip("/")
    payload = _request_payload(user_id, query)
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=timeout, verify=True) as client:
        try:
            resp = await client.post(url, json=payload, headers=_headers(api_key))
        except httpx.RequestError as exc:
            raise BydKmsError(f"无法连接 API 知识库接口: {exc}") from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    if resp.status_code >= 400:
        body_preview = resp.text[:500]
        raise BydKmsError(
            f"API 知识库返回 HTTP {resp.status_code}: {body_preview}",
            status_code=resp.status_code,
            body=body_preview,
        )

    try:
        data = resp.json()
    except ValueError:
        text = resp.text.strip()
        if not text:
            raise BydKmsError("API 知识库返回空响应", status_code=resp.status_code)
        data = {"answer": text}

    results = _parse_search_results(data, query)
    preview = results[0]["content"][:200] if results else _extract_text(data)[:200]

    return {
        "ok": True,
        "latency_ms": elapsed_ms,
        "status_code": resp.status_code,
        "preview": preview,
        "result_count": len(results),
        "raw": data if isinstance(data, dict) else {"text": str(data)},
        "results": results,
    }


async def test_byd_kms_connection(
    *,
    api_url: str,
    user_id: str,
    api_key: Optional[str] = None,
    test_query: str = DEFAULT_TEST_QUERY,
) -> dict[str, Any]:
    result = await call_byd_kms(
        api_url=api_url,
        user_id=user_id,
        query=test_query or DEFAULT_TEST_QUERY,
        api_key=api_key,
        timeout=float(settings.BYD_KMS_TIMEOUT_SECONDS),
    )
    logger.info(
        "byd_kms_test_ok",
        url=api_url,
        user_id=user_id[:4] + "***" if len(user_id) > 4 else user_id,
        latency_ms=result["latency_ms"],
    )
    return {
        "ok": True,
        "message": "连通成功",
        "latency_ms": result["latency_ms"],
        "status_code": result["status_code"],
        "preview": result.get("preview") or "",
        "result_count": result.get("result_count", 0),
    }


async def search_byd_kms(
    meta: dict,
    query: str,
    *,
    top_k: int = 5,
    score_threshold: float = 0.0,
    caller_kms_user_id: str | None = None,
    caller_api_url: str | None = None,
    caller_api_key: str | None = None,
) -> list[dict]:
    cfg = resolve_byd_kms_config(
        meta,
        caller_kms_user_id=caller_kms_user_id,
        caller_api_url=caller_api_url,
        caller_api_key=caller_api_key,
    )
    if not cfg:
        raise BydKmsError("API 知识库配置不完整，请填写 User ID 与接口地址")

    result = await call_byd_kms(
        api_url=cfg["api_url"],
        user_id=cfg["user_id"],
        query=query,
        api_key=cfg.get("api_key"),
        timeout=float(settings.BYD_KMS_TIMEOUT_SECONDS),
    )
    items = result.get("results") or []
    filtered = [r for r in items if float(r.get("score", 0)) >= score_threshold]
    return filtered[:top_k]
