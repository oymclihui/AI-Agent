"""Multi knowledge-base retriever for chat RAG."""
from __future__ import annotations

import structlog
from langchain_core.documents import Document
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeBase, User
from app.knowledge.byd_kms import BydKmsError, search_byd_kms
from app.knowledge.kms_credentials import CallerKmsContext, resolve_caller_kms_context
from app.knowledge.pipeline import IngestionPipeline

logger = structlog.get_logger(__name__)


def _is_byd_kms(kb: KnowledgeBase) -> bool:
    meta = kb.metadata_ or {}
    return meta.get("source_type") == "byd_kms" or meta.get("provider") == "byd_kms"


class MultiKnowledgeRetriever:
    """Retrieve relevant chunks across multiple knowledge bases."""

    def __init__(
        self,
        kb_specs: list[tuple[str, KnowledgeBase]],
        caller_kms: CallerKmsContext | None = None,
    ):
        self.kb_specs = kb_specs
        self.caller_kms = caller_kms

    async def aretrieve(self, query: str) -> list[Document]:
        docs: list[Document] = []
        for kb_id, kb in self.kb_specs:
            try:
                if _is_byd_kms(kb):
                    hits = await search_byd_kms(
                        kb.metadata_ or {},
                        query,
                        top_k=3,
                        score_threshold=0.2,
                        caller_kms_user_id=self.caller_kms.kms_user_id if self.caller_kms else None,
                        caller_api_url=self.caller_kms.api_url if self.caller_kms else None,
                        caller_api_key=self.caller_kms.api_key if self.caller_kms else None,
                    )
                else:
                    pipeline = IngestionPipeline(
                        knowledge_base_id=kb_id,
                        embedding_model=kb.embedding_model,
                        chunk_size=kb.chunk_size or 1000,
                        chunk_overlap=kb.chunk_overlap or 200,
                    )
                    hits = await pipeline.search(query, top_k=3, score_threshold=0.2)
                for hit in hits:
                    content = (hit.get("content") or "").strip()
                    if not content:
                        continue
                    docs.append(
                        Document(
                            page_content=content,
                            metadata={
                                "kb_id": kb_id,
                                "kb_name": kb.name,
                                "document_id": hit.get("document_id"),
                                "document_name": hit.get("document_name"),
                                "score": hit.get("score"),
                            },
                        )
                    )
            except BydKmsError as exc:
                logger.warning("kb_retrieve_byd_failed", kb_id=kb_id, error=str(exc))
            except Exception as exc:
                logger.warning("kb_retrieve_failed", kb_id=kb_id, error=str(exc))
        docs.sort(key=lambda d: float((d.metadata or {}).get("score") or 0), reverse=True)
        return docs[:8]


async def build_multi_kb_retriever(
    db: AsyncSession,
    kb_ids: list[str],
    caller_user: User | None = None,
) -> MultiKnowledgeRetriever | None:
    if not kb_ids:
        return None
    specs: list[tuple[str, KnowledgeBase]] = []
    for kb_id in kb_ids:
        kb = await db.get(KnowledgeBase, kb_id)
        if kb:
            specs.append((kb_id, kb))
    if not specs:
        return None
    caller_kms = await resolve_caller_kms_context(caller_user, db)
    return MultiKnowledgeRetriever(specs, caller_kms=caller_kms)
