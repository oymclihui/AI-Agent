"""
RAG Ingestion Pipeline - orchestrates load -> chunk -> embed -> store.
"""
import os
import tempfile
from dataclasses import dataclass, field

import structlog

from app.knowledge.loader import DocumentLoader
from app.knowledge.chunker import DocumentChunker
from app.knowledge.vectorstore import get_vector_store

logger = structlog.get_logger(__name__)


@dataclass
class IngestOutcome:
    chunk_count: int = 0
    stages: dict = field(default_factory=dict)
    passages: list = field(default_factory=list)


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
        self.last_outcome = IngestOutcome()

    async def ingest_file(
        self,
        file_bytes: bytes,
        filename: str,
        document_id: str,
    ) -> IngestOutcome:
        log = logger.bind(kb_id=self.kb_id, filename=filename, doc_id=document_id)
        log.info("ingestion_start")
        stages = {"parse": "running", "ocr": "skipped", "chunk": "pending", "index": "pending"}
        outcome = IngestOutcome(stages=stages)

        with tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            documents = await self.loader.load_file(tmp_path, filename)
            text = "\n".join(doc.page_content for doc in documents if doc.page_content.strip())
            suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
            if suffix == "pdf" and len(text) < 40:
                stages["ocr"] = "running"
                from app.knowledge.ocr import pdf_scan_to_text
                recognized = pdf_scan_to_text(tmp_path)
                if recognized:
                    from langchain_core.documents import Document
                    documents = [Document(page_content=recognized, metadata={"source": filename, "type": "pdf-ocr"})]
                    stages["ocr"] = "ok"
                else:
                    stages["ocr"] = "empty"
            elif suffix in {"png", "jpg", "jpeg", "webp", "bmp", "gif"}:
                stages["ocr"] = "ok" if text else "empty"
            stages["parse"] = "ok" if text or documents else "empty"
            if not any(doc.page_content.strip() for doc in documents):
                raise ValueError("没有解析出文字")
            stages["chunk"] = "running"
            parents, children = self.chunker.split_parent_child(documents)
            passages = []
            for parent in parents:
                passages.append({
                    "role": "parent",
                    "chunk_index": parent.metadata.get("chunk_index", 0),
                    "parent_index": parent.metadata.get("parent_index", 0),
                    "content": parent.page_content,
                })
            for child in children:
                passages.append({
                    "role": "child",
                    "chunk_index": child.metadata.get("chunk_index", 0),
                    "parent_index": child.metadata.get("parent_index", 0),
                    "content": child.page_content,
                })
            stages["chunk"] = "ok"
            stages["index"] = "running"
            try:
                await self.vector_store.delete_document(document_id)
            except Exception:
                pass
            indexed = children or parents
            count = await self.vector_store.add_documents(indexed, document_id)
            stages["index"] = "ok"
            outcome.chunk_count = count
            outcome.passages = passages
            self.last_outcome = outcome
            log.info("ingestion_complete", chunks=count)
            return count
        except Exception:
            if stages.get("parse") == "running":
                stages["parse"] = "error"
            elif stages.get("chunk") == "running":
                stages["chunk"] = "error"
            elif stages.get("index") == "running":
                stages["index"] = "error"
            raise
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
