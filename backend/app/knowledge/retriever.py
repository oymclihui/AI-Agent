"""Multi knowledge-base retriever for chat RAG."""
from __future__ import annotations

import structlog
from langchain_core.documents import Document
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeBase, User
from app.knowledge.pipeline import IngestionPipeline
from app.knowledge.quality import (
    blocked_faq_ids,
    expand_hit,
    keyword_hits,
    model_rerank,
    rewrite_query,
    rrf_merge,
    to_documents,
)

logger = structlog.get_logger(__name__)


class MultiKnowledgeRetriever:
    """Retrieve relevant chunks across multiple knowledge bases."""

    def __init__(self, kb_specs: list[tuple[str, KnowledgeBase]], db: AsyncSession):
        self.kb_specs = kb_specs
        self.db = db

    async def aretrieve(self, query: str, history_text: str = "") -> list[Document]:
        rewritten = await rewrite_query(query, history_text)
        docs: list[Document] = []
        for kb_id, kb in self.kb_specs:
            try:
                docs.extend(await self._search_kb(kb_id, kb, rewritten))
            except Exception as exc:
                logger.warning("kb_retrieve_failed", kb_id=kb_id, error=str(exc))
        docs.sort(key=lambda item: float((item.metadata or {}).get("score") or 0), reverse=True)
        return docs[:5]

    async def _search_kb(self, kb_id: str, kb: KnowledgeBase, query: str) -> list[Document]:
        pipeline = IngestionPipeline(
            knowledge_base_id=kb_id,
            embedding_model=kb.embedding_model,
            chunk_size=kb.chunk_size or 1000,
            chunk_overlap=kb.chunk_overlap or 200,
        )
        vector_hits = await pipeline.search(query, top_k=8, score_threshold=0.0)
        for hit in vector_hits:
            hit["role"] = "child"
            hit["kb_id"] = kb_id
            hit["snippet"] = (hit.get("content") or "")[:240]
        lexical = await keyword_hits(self.db, kb_id, query)
        merged = rrf_merge([vector_hits, lexical])
        banned = await blocked_faq_ids(self.db, kb_id, query)
        merged = [hit for hit in merged if str(hit.get("document_id") or "") not in banned]
        ranked = await model_rerank(query, merged)
        expanded = []
        for hit in ranked[:5]:
            expanded.append(await expand_hit(self.db, kb_id, hit))
        return to_documents(kb.name, expanded)


async def build_multi_kb_retriever(
    db: AsyncSession,
    kb_ids: list[str],
    caller_user: User | None = None,
) -> MultiKnowledgeRetriever | None:
    if not kb_ids:
        return None
    from app.core.knowledge.access import can_read_kb

    specs: list[tuple[str, KnowledgeBase]] = []
    for kb_id in kb_ids:
        kb = await db.get(KnowledgeBase, kb_id)
        if not kb:
            continue
        if caller_user is not None and not await can_read_kb(db, kb, caller_user):
            continue
        if caller_user is None and (kb.visibility or "private") != "public":
            continue
        specs.append((kb_id, kb))
    if not specs:
        return None
    return MultiKnowledgeRetriever(specs, db)
