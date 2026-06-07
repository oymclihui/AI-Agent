"""
Vector Store manager.
Two backends selected by settings.VECTOR_STORE_TYPE:
  - "milvus"  → remote Milvus server (pymilvus, no langchain-milvus)
  - "chroma"  → embedded / server ChromaDB

Each knowledge base gets its own collection / namespace.
"""
from __future__ import annotations

from typing import Optional
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


def _get_embeddings(model: str):
    """Return a LangChain Embeddings object for the given model name."""
    effective = model or settings.DEFAULT_EMBEDDING_MODEL

    is_ollama_embed = (
        "embed" in effective.lower()
        or effective in {
            "nomic-embed-text", "nomic-embed-text:latest",
            "nomic-embed-text-v2-moe", "nomic-embed-text-v2-moe:latest",
            "qwen3-embedding:0.6b", "bge-m3", "bge-m3:latest",
        }
    )
    if is_ollama_embed:
        try:
            from langchain_ollama import OllamaEmbeddings
            return OllamaEmbeddings(model=effective, base_url=settings.OLLAMA_BASE_URL)
        except ImportError:
            from langchain_community.embeddings import OllamaEmbeddings  # type: ignore
            return OllamaEmbeddings(model=effective, base_url=settings.OLLAMA_BASE_URL)

    if effective.startswith("text-embedding") and settings.OPENAI_API_KEY:
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(model=effective, openai_api_key=settings.OPENAI_API_KEY)

    hf_name = effective if "/" in effective else f"sentence-transformers/{effective}"
    try:
        from langchain_community.embeddings import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(model_name=hf_name)
    except Exception as exc:
        logger.warning("huggingface_embed_fallback", model=hf_name, error=str(exc))
        fallback = settings.DEFAULT_EMBEDDING_MODEL
        try:
            from langchain_ollama import OllamaEmbeddings
            return OllamaEmbeddings(model=fallback, base_url=settings.OLLAMA_BASE_URL)
        except ImportError:
            from langchain_community.embeddings import OllamaEmbeddings  # type: ignore
            return OllamaEmbeddings(model=fallback, base_url=settings.OLLAMA_BASE_URL)


def _embed_texts(embedder, texts: list[str]) -> list[list[float]]:
    return embedder.embed_documents(texts)


def _embed_query(embedder, text: str) -> list[float]:
    return embedder.embed_query(text)


_FIELD_ID = "id"
_FIELD_VECTOR = "embedding"
_FIELD_TEXT = "text"
_FIELD_DOC_ID = "document_id"
_FIELD_KB_ID = "kb_id"
_FIELD_SOURCE = "source"
_FIELD_CHUNK = "chunk_index"
_VECTOR_DIM_DEFAULT = 768


def _vector_dim(embedder) -> int:
    try:
        return len(embedder.embed_query("ping"))
    except Exception:
        return _VECTOR_DIM_DEFAULT


class MilvusVectorStoreManager:
    """Vector store backed by a remote Milvus standalone/cluster server."""

    def __init__(self, knowledge_base_id: str, embedding_model: str = ""):
        self.kb_id = knowledge_base_id
        self.collection_name = f"kb_{knowledge_base_id.replace('-', '_')}"
        self.embedding_model = embedding_model or settings.DEFAULT_EMBEDDING_MODEL
        self._embedder = None
        self._collection = None

    def _get_embedder(self):
        if self._embedder is None:
            self._embedder = _get_embeddings(self.embedding_model)
        return self._embedder

    def _connect(self):
        from pymilvus import connections
        alias = f"conn_{self.kb_id[:8]}"
        if not connections.has_connection(alias):
            uri = settings.MILVUS_URI
            connect_kwargs: dict = {"alias": alias, "uri": uri}
            if settings.MILVUS_TOKEN:
                connect_kwargs["token"] = settings.MILVUS_TOKEN
            if settings.MILVUS_DB:
                connect_kwargs["db_name"] = settings.MILVUS_DB
            connections.connect(**connect_kwargs)
            logger.info("milvus_connected", uri=uri, collection=self.collection_name)
        return alias

    def _get_collection(self):
        if self._collection is not None:
            return self._collection

        from pymilvus import (
            Collection, CollectionSchema, FieldSchema, DataType, utility,
        )

        alias = self._connect()
        embedder = self._get_embedder()
        dim = _vector_dim(embedder)

        if not utility.has_collection(self.collection_name, using=alias):
            fields = [
                FieldSchema(_FIELD_ID, DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(_FIELD_VECTOR, DataType.FLOAT_VECTOR, dim=dim),
                FieldSchema(_FIELD_TEXT, DataType.VARCHAR, max_length=65535),
                FieldSchema(_FIELD_DOC_ID, DataType.VARCHAR, max_length=256),
                FieldSchema(_FIELD_KB_ID, DataType.VARCHAR, max_length=256),
                FieldSchema(_FIELD_SOURCE, DataType.VARCHAR, max_length=512),
                FieldSchema(_FIELD_CHUNK, DataType.INT64),
            ]
            schema = CollectionSchema(fields, description=f"Knowledge base {self.kb_id}")
            col = Collection(self.collection_name, schema=schema, using=alias)
            col.create_index(
                _FIELD_VECTOR,
                {"index_type": "IVF_FLAT", "metric_type": "IP", "params": {"nlist": 128}},
            )
            logger.info("milvus_collection_created", name=self.collection_name, dim=dim)
        else:
            col = Collection(self.collection_name, using=alias)
            col.load()

        self._collection = col
        return col

    async def add_documents(self, documents, document_id: str) -> int:
        col = self._get_collection()
        embedder = self._get_embedder()
        texts = [doc.page_content for doc in documents]
        vectors = _embed_texts(embedder, texts)
        rows = [
            vectors,
            texts,
            [document_id] * len(documents),
            [self.kb_id] * len(documents),
            [doc.metadata.get("source", "") for doc in documents],
            [int(doc.metadata.get("chunk_index", i)) for i, doc in enumerate(documents)],
        ]
        col.insert(rows)
        col.flush()
        logger.info("milvus_docs_added", kb_id=self.kb_id, count=len(documents))
        return len(documents)

    async def search(self, query: str, top_k: int = 5, score_threshold: float = 0.0) -> list[dict]:
        col = self._get_collection()
        embedder = self._get_embedder()
        q_vec = _embed_query(embedder, query)
        results = col.search(
            data=[q_vec],
            anns_field=_FIELD_VECTOR,
            param={"metric_type": "IP", "params": {"nprobe": 16}},
            limit=top_k,
            output_fields=[_FIELD_TEXT, _FIELD_DOC_ID, _FIELD_SOURCE, _FIELD_CHUNK, _FIELD_KB_ID],
        )
        output = []
        for hit in results[0]:
            score = float(hit.score)
            if score < score_threshold:
                continue
            output.append({
                "content": hit.entity.get(_FIELD_TEXT, ""),
                "score": score,
                "document_id": hit.entity.get(_FIELD_DOC_ID, ""),
                "document_name": hit.entity.get(_FIELD_SOURCE, ""),
                "chunk_index": hit.entity.get(_FIELD_CHUNK, 0),
                "metadata": {
                    "kb_id": hit.entity.get(_FIELD_KB_ID, ""),
                    "document_id": hit.entity.get(_FIELD_DOC_ID, ""),
                    "source": hit.entity.get(_FIELD_SOURCE, ""),
                },
            })
        return output

    async def list_document_chunks(self, document_id: str) -> list[dict]:
        try:
            col = self._get_collection()
            expr = f'{_FIELD_DOC_ID} == "{document_id}"'
            rows = col.query(
                expr=expr,
                output_fields=[_FIELD_TEXT, _FIELD_CHUNK],
            )
            chunks = [
                {
                    "chunk_index": int(row.get(_FIELD_CHUNK, 0)),
                    "content": row.get(_FIELD_TEXT, "") or "",
                }
                for row in rows
            ]
            chunks.sort(key=lambda item: item["chunk_index"])
            return chunks
        except Exception as exc:
            logger.warning("milvus_list_chunks_failed", document_id=document_id, error=str(exc))
            return []

    async def delete_document(self, document_id: str) -> None:
        try:
            col = self._get_collection()
            expr = f'{_FIELD_DOC_ID} == "{document_id}"'
            col.delete(expr)
            col.flush()
            logger.info("milvus_doc_deleted", document_id=document_id)
        except Exception as exc:
            logger.warning("milvus_delete_failed", error=str(exc))

    async def delete_collection(self) -> None:
        try:
            from pymilvus import utility
            alias = self._connect()
            if utility.has_collection(self.collection_name, using=alias):
                utility.drop_collection(self.collection_name, using=alias)
            self._collection = None
            logger.info("milvus_collection_dropped", name=self.collection_name)
        except Exception as exc:
            logger.warning("milvus_drop_failed", error=str(exc))


import chromadb  # noqa: E402

_chroma_client: Optional[chromadb.ClientAPI] = None


def _get_chroma_client() -> chromadb.ClientAPI:
    global _chroma_client
    if _chroma_client is not None:
        return _chroma_client
    if settings.CHROMA_MODE == "local":
        import os
        os.makedirs(settings.CHROMA_LOCAL_PATH, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=settings.CHROMA_LOCAL_PATH)
    else:
        _chroma_client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT,
        )
    return _chroma_client


class ChromaVectorStoreManager:
    def __init__(self, knowledge_base_id: str, embedding_model: str = ""):
        self.kb_id = knowledge_base_id
        self.collection_name = f"kb_{knowledge_base_id.replace('-', '_')}"
        self.embedding_model = embedding_model or settings.DEFAULT_EMBEDDING_MODEL
        self._store = None

    def get_store(self):
        if self._store is None:
            from langchain_chroma import Chroma
            self._store = Chroma(
                collection_name=self.collection_name,
                embedding_function=_get_embeddings(self.embedding_model),
                client=_get_chroma_client(),
            )
        return self._store

    async def add_documents(self, documents, document_id: str) -> int:
        store = self.get_store()
        for doc in documents:
            doc.metadata["document_id"] = document_id
            doc.metadata["kb_id"] = self.kb_id
        ids = [f"{document_id}_{i}" for i in range(len(documents))]
        store.add_documents(documents, ids=ids)
        logger.info("chroma_docs_added", kb_id=self.kb_id, count=len(documents))
        return len(documents)

    async def search(self, query: str, top_k: int = 5, score_threshold: float = 0.3) -> list[dict]:
        store = self.get_store()
        results = store.similarity_search_with_score(query, k=top_k)
        output = []
        for doc, score in results:
            if score >= score_threshold:
                output.append({
                    "content": doc.page_content,
                    "score": float(score),
                    "document_id": doc.metadata.get("document_id", ""),
                    "document_name": doc.metadata.get("source", ""),
                    "chunk_index": doc.metadata.get("chunk_index", 0),
                    "metadata": doc.metadata,
                })
        return output

    async def list_document_chunks(self, document_id: str) -> list[dict]:
        try:
            store = self.get_store()
            data = store._collection.get(
                where={"document_id": document_id},
                include=["documents", "metadatas"],
            )
            documents = data.get("documents") or []
            metadatas = data.get("metadatas") or []
            chunks = []
            for index, text in enumerate(documents):
                meta = metadatas[index] if index < len(metadatas) else {}
                chunks.append({
                    "chunk_index": int(meta.get("chunk_index", index)),
                    "content": text or "",
                })
            chunks.sort(key=lambda item: item["chunk_index"])
            return chunks
        except Exception as exc:
            logger.warning("chroma_list_chunks_failed", document_id=document_id, error=str(exc))
            return []

    async def delete_document(self, document_id: str) -> None:
        store = self.get_store()
        store._collection.delete(where={"document_id": document_id})
        logger.info("chroma_doc_deleted", document_id=document_id)

    async def delete_collection(self) -> None:
        global _chroma_client
        client = _get_chroma_client()
        try:
            client.delete_collection(self.collection_name)
            self._store = None
            logger.info("chroma_collection_deleted", kb_id=self.kb_id)
        except Exception as exc:
            logger.warning("chroma_delete_failed", error=str(exc))


VectorStoreManager = MilvusVectorStoreManager  # backward-compat alias


def get_vector_store(
    knowledge_base_id: str,
    embedding_model: str = "",
) -> MilvusVectorStoreManager | ChromaVectorStoreManager:
    if settings.VECTOR_STORE_TYPE.lower() == "milvus":
        return MilvusVectorStoreManager(knowledge_base_id, embedding_model)
    return ChromaVectorStoreManager(knowledge_base_id, embedding_model)
