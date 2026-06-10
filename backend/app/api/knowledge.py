from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import KnowledgeBase, Document, KBStatus, User
from app.db.base import generate_uuid
from app.schemas.knowledge import (
    KnowledgeBaseCreate, KnowledgeBaseResponse,
    DocumentResponse, DocumentContentResponse, DocumentChunkResponse,
    SearchRequest, SearchResult,
)
from app.knowledge.pipeline import IngestionPipeline
from app.knowledge.storage import save_document_file, read_document_file, delete_document_file
from app.core.auth.deps import get_current_user
from app.core.auth.scoping import scope_readable, assert_mutable_by_user

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])


@router.get("/", response_model=list[KnowledgeBaseResponse])
async def list_knowledge_bases(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(KnowledgeBase)
        .where(scope_readable(KnowledgeBase, user.id))
        .order_by(KnowledgeBase.created_at.desc())
    )
    return result.scalars().all()


@router.post("/", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = KnowledgeBase(
        id=generate_uuid(),
        owner_id=user.id,
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
async def get_knowledge_base(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb or not (kb.owner_id == user.id or kb.owner_id is None):
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return kb


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    assert_mutable_by_user(kb, user.id, "knowledge base")
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
    filename = file.filename or "unknown"

    doc = Document(
        id=doc_id,
        knowledge_base_id=kb_id,
        filename=filename,
        file_type=filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt",
        file_size=len(file_bytes),
        status=KBStatus.processing,
        storage_path=save_document_file(kb_id, doc_id, filename, file_bytes),
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
        chunk_count = await pipeline.ingest_file(file_bytes, filename, doc_id)

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


@router.get("/{kb_id}/documents/{doc_id}/content", response_model=DocumentContentResponse)
async def get_document_content(
    kb_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
):
    doc = await db.get(Document, doc_id)
    if not doc or doc.knowledge_base_id != kb_id:
        raise HTTPException(status_code=404, detail="Document not found")

    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    content = ""
    source = "chunks"
    chunks: list[DocumentChunkResponse] = []

    if doc.storage_path:
        raw = read_document_file(doc.storage_path)
        if raw is not None:
            content = raw.decode("utf-8", errors="replace")
            source = "file"

    if not content.strip():
        pipeline = IngestionPipeline(
            knowledge_base_id=kb_id,
            embedding_model=kb.embedding_model,
        )
        chunk_rows = await pipeline.list_document_chunks(doc_id)
        chunks = [DocumentChunkResponse(**row) for row in chunk_rows]
        content = "\n\n".join(
            row.content.strip() for row in chunks if row.content.strip()
        )
        source = "chunks"

    return DocumentContentResponse(
        id=doc.id,
        filename=doc.filename,
        file_type=doc.file_type,
        content=content,
        source=source,
        chunk_count=len(chunks) or doc.chunk_count,
        chunks=chunks,
    )


@router.delete("/{kb_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(kb_id: str, doc_id: str, db: AsyncSession = Depends(get_db)):
    doc = await db.get(Document, doc_id)
    if not doc or doc.knowledge_base_id != kb_id:
        raise HTTPException(status_code=404, detail="Document not found")

    pipeline = IngestionPipeline(knowledge_base_id=kb_id)
    await pipeline.vector_store.delete_document(doc_id)
    delete_document_file(doc.storage_path or "")
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
