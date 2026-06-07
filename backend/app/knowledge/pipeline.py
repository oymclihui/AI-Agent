"""
RAG Ingestion Pipeline - orchestrates load -> chunk -> embed -> store.
"""
import os
import tempfile
import structlog

from app.knowledge.loader import DocumentLoader
from app.knowledge.chunker import DocumentChunker
from app.knowledge.vectorstore import get_vector_store

logger = structlog.get_logger(__name__)


class IngestionPipeline:
    def __init__(
        self,
        knowledge_base_id: str,
        embedding_model: str = "text-embedding-3-small",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        self.kb_id = knowledge_base_id
        self.loader = DocumentLoader()
        self.chunker = DocumentChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.vector_store = get_vector_store(knowledge_base_id, embedding_model)

    async def ingest_file(
        self,
        file_bytes: bytes,
        filename: str,
        document_id: str,
    ) -> int:
        """
        Full ingestion pipeline for an uploaded file.
        Returns the number of chunks stored.
        """
        log = logger.bind(kb_id=self.kb_id, filename=filename, doc_id=document_id)
        log.info("ingestion_start")

        with tempfile.NamedTemporaryFile(
            suffix=f"_{filename}",
            delete=False,
        ) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            documents = await self.loader.load_file(tmp_path, filename)
            chunks = self.chunker.split(documents)
            count = await self.vector_store.add_documents(chunks, document_id)
            log.info("ingestion_complete", chunks=count)
            return count
        finally:
            os.unlink(tmp_path)

    async def ingest_url(self, url: str, document_id: str) -> int:
        logger.info("ingestion_url", kb_id=self.kb_id, url=url)
        documents = await self.loader.load_url(url)
        chunks = self.chunker.split(documents)
        return await self.vector_store.add_documents(chunks, document_id)

    async def search(self, query: str, top_k: int = 5, score_threshold: float = 0.3) -> list[dict]:
        return await self.vector_store.search(query, top_k=top_k, score_threshold=score_threshold)

    async def list_document_chunks(self, document_id: str) -> list[dict]:
        return await self.vector_store.list_document_chunks(document_id)
