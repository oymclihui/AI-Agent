"""Query rewrite, hybrid retrieval, parent expansion, and rerank."""
from __future__ import annotations

import asyncio
import contextvars
import re
from typing import Any

_citations: contextvars.ContextVar[list] = contextvars.ContextVar("kb_citations", default=[])


def set_citations(items: list) -> None:
    _citations.set(items)


def get_citations() -> list:
    return list(_citations.get() or [])

import structlog
from langchain_core.documents import Document
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_PUNCT = re.compile(r"[\s,，。！？、；：\"'“”‘’（）()\[\]【】<>《》]+")


def grams(text: str, limit: int = 6) -> list[str]:
    cleaned = _PUNCT.sub("", text or "")
    found: list[str] = []
    for size in (4, 3, 2):
        if len(cleaned) < size:
            continue
        for index in range(len(cleaned) - size + 1):
            piece = cleaned[index:index + size]
            if piece not in found:
                found.append(piece)
            if len(found) >= limit:
                return found
    if cleaned and cleaned not in found:
        found.append(cleaned[:32])
    return found[:limit]


def overlap(left: str, right: str) -> float:
    a = set(grams(left, 12))
    b = set(grams(right, 12))
    if not a or not b:
        return 0.0
    return len(a & b) / max(min(len(a), len(b)), 1)


def history_text(messages: list) -> str:
    lines: list[str] = []
    for message in messages[-6:]:
        content = getattr(message, "content", "") or ""
        if not isinstance(content, str) or not content.strip():
            continue
        kind = message.__class__.__name__.lower()
        role = "用户" if "human" in kind else "助手"
        lines.append(f"{role}：{content.strip()[:300]}")
    return "\n".join(lines)


async def rewrite_query(question: str, prior: str) -> str:
    question = (question or "").strip()
    if not question or not prior.strip():
        return question
    try:
        from app.models_hub.router import ModelRouter

        llm = await ModelRouter.get_llm(provider="openai", model="qwen-plus")
        prompt = (
            "把最后的用户问题改写成一句可以独立检索资料的问句。"
            "不要回答问题。不要加解释。如果问题已经完整，原样输出。\n"
            f"对话：\n{prior[-1500:]}\n问题：{question}"
        )
        response = await asyncio.wait_for(llm.ainvoke(prompt), timeout=8)
        text = str(response.content or "").strip().splitlines()[0].strip(" \"“”")
        return text[:200] or question
    except Exception as exc:
        logger.warning("kb_rewrite_failed", error=str(exc))
        return question


def rrf_merge(groups: list[list[dict]], limit: int = 12) -> list[dict]:
    pooled: dict[tuple, dict] = {}
    for group in groups:
        for rank, hit in enumerate(group):
            key = (str(hit.get("document_id") or ""), int(hit.get("chunk_index") or 0), str(hit.get("role") or "child"))
            row = pooled.get(key)
            if row is None:
                row = dict(hit)
                row["rrf"] = 0.0
                pooled[key] = row
            row["rrf"] = float(row.get("rrf") or 0) + 1.0 / (60 + rank)
    ranked = sorted(pooled.values(), key=lambda item: float(item.get("rrf") or 0), reverse=True)
    return ranked[:limit]


def local_rerank(query: str, hits: list[dict]) -> list[dict]:
    for hit in hits:
        lexical = overlap(query, hit.get("snippet") or hit.get("content") or "")
        hit["rerank"] = 0.7 * lexical + 0.3 * float(hit.get("rrf") or 0)
    hits.sort(key=lambda item: float(item.get("rerank") or 0), reverse=True)
    return hits


async def model_rerank(query: str, hits: list[dict]) -> list[dict]:
    ordered = local_rerank(query, hits)
    if len(ordered) < 2:
        return ordered
    try:
        from app.models_hub.router import ModelRouter

        llm = await ModelRouter.get_llm(provider="openai", model="qwen-plus")
        packed = "\n".join(
            f"[{index}] {(item.get('snippet') or item.get('content') or '')[:160]}"
            for index, item in enumerate(ordered[:8])
        )
        prompt = (
            "按和问题的相关性从高到低排列序号。只输出序号，用逗号分隔。\n"
            f"问题：{query}\n{packed}"
        )
        response = await asyncio.wait_for(llm.ainvoke(prompt), timeout=8)
        indexes = [int(piece) for piece in re.findall(r"\d+", str(response.content or ""))]
        picked: list[dict] = []
        seen: set[int] = set()
        for index in indexes:
            if 0 <= index < len(ordered) and index not in seen:
                picked.append(ordered[index])
                seen.add(index)
        for index, item in enumerate(ordered):
            if index not in seen:
                picked.append(item)
        return picked
    except Exception as exc:
        logger.warning("kb_rerank_failed", error=str(exc))
        return ordered


async def keyword_hits(db: AsyncSession, kb_id: str, query: str) -> list[dict]:
    from app.db.models import KnowledgePassage

    pieces = [piece.replace("%", "").replace("_", "") for piece in grams(query)]
    pieces = [piece for piece in pieces if piece]
    if not pieces:
        return []
    stmt = (
        select(KnowledgePassage)
        .where(
            KnowledgePassage.knowledge_base_id == kb_id,
            KnowledgePassage.role.in_(["child", "faq"]),
            or_(*[KnowledgePassage.content.ilike(f"%{piece}%") for piece in pieces]),
        )
        .limit(20)
    )
    rows = (await db.execute(stmt)).scalars().all()
    hits = []
    for row in rows:
        hits.append({
            "content": row.content,
            "snippet": row.content[:240],
            "document_id": row.document_id,
            "document_name": row.title or "",
            "chunk_index": row.chunk_index,
            "parent_index": row.parent_index,
            "role": row.role,
            "kb_id": kb_id,
            "score": overlap(query, row.content),
        })
    hits.sort(key=lambda item: float(item["score"]), reverse=True)
    return hits[:8]


async def expand_hit(db: AsyncSession, kb_id: str, hit: dict) -> dict:
    from app.db.models import KnowledgePassage

    if hit.get("role") == "faq":
        parent = (
            await db.execute(
                select(KnowledgePassage).where(
                    KnowledgePassage.knowledge_base_id == kb_id,
                    KnowledgePassage.document_id == hit.get("document_id"),
                    KnowledgePassage.role == "faq",
                ).limit(1)
            )
        ).scalar_one_or_none()
        if parent is not None:
            hit["snippet"] = (hit.get("snippet") or parent.title or "")[:240]
            hit["content"] = parent.content
            hit["document_name"] = parent.title or hit.get("document_name") or "问答"
        return hit
    parent_index = hit.get("parent_index")
    if parent_index is None:
        return hit
    parent = (
        await db.execute(
            select(KnowledgePassage).where(
                KnowledgePassage.knowledge_base_id == kb_id,
                KnowledgePassage.document_id == hit.get("document_id"),
                KnowledgePassage.role == "parent",
                KnowledgePassage.parent_index == int(parent_index),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if parent is not None and parent.content:
        hit["snippet"] = (hit.get("snippet") or hit.get("content") or "")[:240]
        hit["content"] = parent.content
        if parent.title:
            hit["document_name"] = hit.get("document_name") or parent.title
    return hit


async def blocked_faq_ids(db: AsyncSession, kb_id: str, query: str) -> set[str]:
    from app.db.models import KnowledgeFaqEntry

    rows = (
        await db.execute(
            select(KnowledgeFaqEntry).where(
                KnowledgeFaqEntry.knowledge_base_id == kb_id,
                KnowledgeFaqEntry.enabled == True,
            )
        )
    ).scalars().all()
    blocked: set[str] = set()
    for row in rows:
        for negative in row.negative_questions or []:
            if overlap(query, str(negative)) >= 0.55:
                blocked.add(row.id)
                break
    return blocked


def to_documents(kb_name: str, hits: list[dict]) -> list[Document]:
    docs: list[Document] = []
    for hit in hits:
        content = (hit.get("content") or "").strip()
        if not content:
            continue
        docs.append(Document(
            page_content=content,
            metadata={
                "kb_id": hit.get("kb_id"),
                "kb_name": kb_name,
                "document_id": hit.get("document_id"),
                "document_name": hit.get("document_name") or "",
                "snippet": (hit.get("snippet") or content)[:240],
                "score": hit.get("rerank") or hit.get("rrf") or hit.get("score"),
                "kind": "faq" if hit.get("role") == "faq" else "chunk",
            },
        ))
    return docs


def citations_of(docs: list[Document]) -> list[dict[str, Any]]:
    items = []
    for doc in docs[:5]:
        meta = doc.metadata or {}
        items.append({
            "kb_id": meta.get("kb_id"),
            "document_id": meta.get("document_id"),
            "document_name": meta.get("document_name") or "资料",
            "snippet": meta.get("snippet") or doc.page_content[:240],
            "kind": meta.get("kind") or "chunk",
        })
    return items


def context_of(docs: list[Document]) -> str:
    blocks = []
    for index, doc in enumerate(docs[:5], start=1):
        meta = doc.metadata or {}
        name = meta.get("document_name") or "资料"
        blocks.append(f"[{index}] {name}\n{doc.page_content[:1200]}")
    return "\n\n".join(blocks)
