"""示例库向量索引（Agent Evolution 阶段二 L2）。

每个数据源一个 Milvus collection（askex_{ds}），存正/负例问答对的问句向量。
- 复用 app.knowledge.vectorstore 的 embedding 构造（Ollama nomic-embed-text, 768 维）
- pymilvus / embedder 懒加载；Milvus 不可用时返回空结果，绝不影响问数主流程
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from app.config import settings

logger = logging.getLogger("ds_distill_vector")

_PREFIX = "askex_"
_F_ID = "id"
_F_VEC = "embedding"
_F_EXAMPLE_ID = "example_id"
_F_QUESTION = "question"
_F_SQL = "sql_text"
_F_KIND = "kind"
_F_SOURCE = "source"
_F_TRACE = "trace_id"

_dim_cache: dict[str, int] = {}
_embedder = None
_embedder_loop = None  # 持有创建该实例的事件循环对象引用（身份比较，避免 id 回收复用）
_lock = threading.Lock()


def _collection_name(data_source_id: str) -> str:
    return _PREFIX + str(data_source_id).replace("-", "_")


def _get_embedder():
    # 按事件循环隔离 embedder 实例。
    # Celery 任务每次 asyncio.run() 都会新建事件循环，而 OllamaEmbeddings 内部的
    # httpx 连接池绑定创建时的事件循环；跨 loop 复用旧实例会抛 Event loop is closed，
    # 导致任务首轮 embedding 调用失败、评估指标失真。
    # 因此缓存按当前 loop 标识 id 隔离，换 loop 即重建。
    global _embedder, _embedder_loop
    # 不能用 id(loop) 做键：loop 关闭被回收后 id 会被新 loop 复用，导致隔离失效。
    # 改为持有 loop 对象本身做身份比较（is）。
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _embedder is None or _embedder_loop is not loop:
        with _lock:
            if _embedder is None or _embedder_loop is not loop:
                from app.knowledge.vectorstore import _get_embeddings

                _embedder = _get_embeddings(settings.DEFAULT_EMBEDDING_MODEL)
                _embedder_loop = loop
    return _embedder


def _vector_dim() -> int:
    key = settings.DEFAULT_EMBEDDING_MODEL
    if key not in _dim_cache:
        from app.knowledge.vectorstore import _vector_dim as _dim

        _dim_cache[key] = int(_dim(_get_embedder()))
    return _dim_cache[key]


def _connect(data_source_id: str):
    from pymilvus import connections

    alias = _PREFIX + str(data_source_id).replace("-", "_")[:16]
    if not connections.has_connection(alias):
        kwargs: dict[str, Any] = {"alias": alias, "uri": settings.MILVUS_URI}
        if settings.MILVUS_TOKEN:
            kwargs["token"] = settings.MILVUS_TOKEN
        if settings.MILVUS_DB:
            kwargs["db_name"] = settings.MILVUS_DB
        connections.connect(**kwargs)
    return alias


def _get_collection(data_source_id: str):
    from pymilvus import (
        Collection,
        CollectionSchema,
        DataType,
        FieldSchema,
        utility,
    )

    alias = _connect(data_source_id)
    name = _collection_name(data_source_id)
    dim = _vector_dim()
    if not utility.has_collection(name, using=alias):
        fields = [
            FieldSchema(_F_ID, DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(_F_VEC, DataType.FLOAT_VECTOR, dim=dim),
            FieldSchema(_F_EXAMPLE_ID, DataType.VARCHAR, max_length=64),
            FieldSchema(_F_QUESTION, DataType.VARCHAR, max_length=4096),
            FieldSchema(_F_SQL, DataType.VARCHAR, max_length=8192),
            FieldSchema(_F_KIND, DataType.VARCHAR, max_length=16),
            FieldSchema(_F_SOURCE, DataType.VARCHAR, max_length=32),
            FieldSchema(_F_TRACE, DataType.INT64),
        ]
        col = Collection(
            name,
            schema=CollectionSchema(fields, description=f"ask examples {data_source_id}"),
            using=alias,
        )
        col.create_index(
            _F_VEC,
            {"index_type": "IVF_FLAT", "metric_type": "IP", "params": {"nlist": 128}},
        )
        col.load()
    else:
        col = Collection(name, using=alias)
        col.load()
    return col


def upsert_example(
    *,
    data_source_id: str,
    example_id: str,
    question: str,
    sql_text: str,
    kind: str = "positive",
    source: str = "feedback",
    trace_id: int = 0,
) -> bool:
    try:
        col = _get_collection(data_source_id)
        vec = _get_embedder().embed_query((question or "").strip()[:4000])
        col.delete(expr=f'{_F_EXAMPLE_ID} == "{example_id}"')
        col.insert(
            [
                [vec],
                [str(example_id)],
                [(question or "")[:4000]],
                [(sql_text or "")[:8000]],
                [(kind or "positive")[:16]],
                [(source or "feedback")[:32]],
                [int(trace_id or 0)],
            ]
        )
        col.flush()
        return True
    except Exception as exc:
        logger.warning("upsert_example_failed ds=%s err=%s", data_source_id, str(exc)[:200])
        return False


def delete_example(*, data_source_id: str, example_id: str) -> None:
    try:
        col = _get_collection(data_source_id)
        col.delete(expr=f'{_F_EXAMPLE_ID} == "{example_id}"')
        col.flush()
    except Exception as exc:
        logger.warning("delete_example_failed err=%s", str(exc)[:200])


def search_examples(
    *,
    data_source_id: str,
    question: str,
    top_k: int = 3,
    kinds: tuple[str, ...] = ("positive",),
) -> list[dict[str, Any]]:
    try:
        col = _get_collection(data_source_id)
        vec = _get_embedder().embed_query((question or "").strip()[:4000])
        expr = " or ".join(f'{_F_KIND} == "{k}"' for k in kinds) if kinds else ""
        results = col.search(
            data=[vec],
            anns_field=_F_VEC,
            param={"metric_type": "IP", "params": {"nprobe": 16}},
            limit=max(1, int(top_k)),
            expr=expr or None,
            output_fields=[_F_EXAMPLE_ID, _F_QUESTION, _F_SQL, _F_KIND, _F_SOURCE],
        )
        out: list[dict[str, Any]] = []
        for hit in results[0]:
            out.append(
                {
                    "example_id": hit.entity.get(_F_EXAMPLE_ID, ""),
                    "question": hit.entity.get(_F_QUESTION, ""),
                    "sql": hit.entity.get(_F_SQL, ""),
                    "kind": hit.entity.get(_F_KIND, ""),
                    "source": hit.entity.get(_F_SOURCE, ""),
                    "score": round(float(hit.score), 4),
                }
            )
        return out
    except Exception as exc:
        logger.warning("search_examples_failed ds=%s err=%s", data_source_id, str(exc)[:200])
        return []
