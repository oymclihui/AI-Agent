"""Sync WeCom smart documents into a knowledge base."""
from __future__ import annotations

import asyncio
import hashlib
import time

import httpx
import structlog

logger = structlog.get_logger(__name__)
_TOKEN: dict[str, tuple[str, float]] = {}
_task: asyncio.Task | None = None


def _flatten(node, out: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"text", "content", "title"} and isinstance(value, str) and value.strip():
                out.append(value.strip())
            else:
                _flatten(value, out)
    elif isinstance(node, list):
        for item in node:
            _flatten(item, out)


async def _token(corp_id: str, secret: str) -> str:
    cached = _TOKEN.get(corp_id)
    if cached and cached[1] > time.time():
        return cached[0]
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={"corpid": corp_id, "corpsecret": secret},
        )
        payload = response.json()
    if payload.get("errcode") not in (0, None):
        raise RuntimeError(payload.get("errmsg") or "企业微信令牌获取失败")
    token = payload.get("access_token") or ""
    if not token:
        raise RuntimeError("企业微信没有返回令牌")
    _TOKEN[corp_id] = (token, time.time() + 7000)
    return token


async def fetch_doc_text(corp_id: str, secret: str, doc_id: str) -> str:
    token = await _token(corp_id, secret)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://qyapi.weixin.qq.com/cgi-bin/wedoc/document/get",
            params={"access_token": token},
            json={"docid": doc_id},
        )
        payload = response.json()
    if payload.get("errcode") not in (0, None):
        raise RuntimeError(payload.get("errmsg") or "读取企业微信文档失败")
    parts: list[str] = []
    _flatten(payload, parts)
    text = "\n".join(dict.fromkeys(parts))
    if not text.strip():
        raise RuntimeError("文档没有解析出文字")
    return text


async def sync_source(db, source) -> dict:
    from app.db.models import Document, KBStatus, KnowledgeBase
    from app.db.base import generate_uuid
    from app.core.data_ask.credentials import decrypt_secret
    from app.knowledge.pipeline import IngestionPipeline
    from app.knowledge.storage import save_document_file
    from app.knowledge.passages import replace_passages

    kb = await db.get(KnowledgeBase, source.knowledge_base_id)
    if kb is None:
        return {"ok": False, "error": "资料库不存在"}
    secret = decrypt_secret(source.secret_encrypted or "")
    if not source.enabled or not source.corp_id or not secret or not source.doc_ids:
        source.last_status = "skipped"
        source.last_error = "未启用或未填写企业 ID、Secret、文档 ID"
        return {"ok": False, "skipped": True}
    pipeline = IngestionPipeline(
        knowledge_base_id=kb.id,
        embedding_model=kb.embedding_model,
        chunk_size=kb.chunk_size,
        chunk_overlap=kb.chunk_overlap,
    )
    synced = 0
    errors: list[str] = []
    for doc_id in source.doc_ids[:20]:
        try:
            text = await fetch_doc_text(source.corp_id, secret, doc_id)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            filename = f"企微文档-{doc_id}.md"
            from sqlalchemy import select
            existing = (
                await db.execute(
                    select(Document).where(
                        Document.knowledge_base_id == kb.id,
                        Document.filename == filename,
                    )
                )
            ).scalar_one_or_none()
            meta = dict((existing.metadata_ if existing else {}) or {})
            if existing and meta.get("wecom_hash") == digest:
                continue
            raw = text.encode("utf-8")
            if existing is None:
                existing = Document(
                    id=generate_uuid(),
                    knowledge_base_id=kb.id,
                    filename=filename,
                    file_type="md",
                    file_size=len(raw),
                    status=KBStatus.processing,
                    metadata_={"source": "wecom_doc", "doc_id": doc_id},
                )
                db.add(existing)
                kb.document_count = (kb.document_count or 0) + 1
                await db.flush()
            existing.storage_path = save_document_file(kb.id, existing.id, filename, raw)
            existing.file_size = len(raw)
            await pipeline.ingest_file(raw, filename, existing.id)
            outcome = pipeline.last_outcome
            await replace_passages(db, kb.id, existing.id, filename, outcome.passages)
            existing.status = KBStatus.ready
            existing.chunk_count = outcome.chunk_count
            existing.metadata_ = {
                "source": "wecom_doc",
                "doc_id": doc_id,
                "wecom_hash": digest,
                "stage": "ready",
                "stages": outcome.stages,
            }
            synced += 1
        except Exception as exc:
            errors.append(f"{doc_id}: {exc}")
            logger.warning("wecom_doc_sync_item_failed", doc_id=doc_id, error=str(exc))
    source.last_status = "error" if errors and not synced else "ok"
    source.last_error = "；".join(errors)[:500] if errors else ""
    await db.flush()
    return {"ok": not errors, "synced": synced, "errors": errors}


async def sync_enabled() -> None:
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.db.models import KnowledgeWecomSource

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(select(KnowledgeWecomSource).where(KnowledgeWecomSource.enabled == True))
        ).scalars().all()
        for source in rows:
            try:
                await sync_source(db, source)
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.warning("wecom_doc_sync_failed", error=str(exc))


class WecomDocSync:
    def start(self) -> None:
        global _task
        if _task and not _task.done():
            return
        _task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        global _task
        if _task:
            _task.cancel()
            _task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(900)
            try:
                await sync_enabled()
            except Exception as exc:
                logger.warning("wecom_doc_loop_failed", error=str(exc))


wecom_doc_sync = WecomDocSync()
