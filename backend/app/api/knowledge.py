import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import KnowledgeBase, Document, KBStatus
from app.db.base import generate_uuid
from app.schemas.knowledge import (
    KnowledgeBaseCreate, KnowledgeBaseResponse,
    DocumentResponse, SearchRequest, SearchResult,
)
from app.knowledge.pipeline import IngestionPipeline
from app.config import settings

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])


@router.get("/", response_model=list[KnowledgeBaseResponse])
async def list_knowledge_bases(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()))
    return result.scalars().all()


@router.post("/", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(payload: KnowledgeBaseCreate, db: AsyncSession = Depends(get_db)):
    kb = KnowledgeBase(
        id=generate_uuid(),
        name=payload.name,
        description=payload.description,
        embedding_model=payload.embedding_model,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
        status=KBStatus.ready,
    )
    db.add(kb)
    await db.flush()
    await db.refresh(kb)
    return kb


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_knowledge_base(kb_id: str, db: AsyncSession = Depends(get_db)):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return kb


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(kb_id: str, db: AsyncSession = Depends(get_db)):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    await db.delete(kb)


@router.post("/{kb_id}/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    kb_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    file_bytes = await file.read()
    doc_id = generate_uuid()

    doc = Document(
        id=doc_id,
        knowledge_base_id=kb_id,
        filename=file.filename or "unknown",
        file_type=file.filename.rsplit(".", 1)[-1].lower() if file.filename else "txt",
        file_size=len(file_bytes),
        status=KBStatus.processing,
    )
    db.add(doc)
    await db.flush()

    try:
        pipeline = IngestionPipeline(
            knowledge_base_id=kb_id,
            embedding_model=kb.embedding_model,
            chunk_size=kb.chunk_size,
            chunk_overlap=kb.chunk_overlap,
        )
        chunk_count = await pipeline.ingest_file(file_bytes, file.filename or "unknown", doc_id)

        doc.status = KBStatus.ready
        doc.chunk_count = chunk_count
        kb.document_count = kb.document_count + 1
        await db.flush()
    except Exception as e:
        doc.status = KBStatus.error
        doc.metadata_ = {"error": str(e)}
        await db.flush()
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")

    await db.refresh(doc)
    return doc


@router.get("/{kb_id}/documents", response_model=list[DocumentResponse])
async def list_documents(kb_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Document)
        .where(Document.knowledge_base_id == kb_id)
        .order_by(Document.created_at.desc())
    )
    return result.scalars().all()


@router.delete("/{kb_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(kb_id: str, doc_id: str, db: AsyncSession = Depends(get_db)):
    doc = await db.get(Document, doc_id)
    if not doc or doc.knowledge_base_id != kb_id:
        raise HTTPException(status_code=404, detail="Document not found")

    pipeline = IngestionPipeline(knowledge_base_id=kb_id)
    await pipeline.vector_store.delete_document(doc_id)
    await db.delete(doc)


@router.post("/{kb_id}/search", response_model=list[SearchResult])
async def search_knowledge_base(kb_id: str, payload: SearchRequest, db: AsyncSession = Depends(get_db)):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    pipeline = IngestionPipeline(
        knowledge_base_id=kb_id,
        embedding_model=kb.embedding_model,
    )
    results = await pipeline.search(payload.query, top_k=payload.top_k, score_threshold=payload.score_threshold)
    return [SearchResult(**r) for r in results]
