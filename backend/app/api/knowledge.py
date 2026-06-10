from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import KnowledgeBase, Document, KBStatus, User
from app.db.base import generate_uuid
from app.schemas.knowledge import (
    KnowledgeBaseCreate, KnowledgeBaseUpdate, KnowledgeBaseResponse,
    DocumentResponse, DocumentContentResponse, DocumentChunkResponse,
    SearchRequest, SearchResult,
    BydKmsTestRequest, BydKmsTestResponse, BydKmsConfigPublic,
)
from app.knowledge.pipeline import IngestionPipeline
from app.knowledge.storage import save_document_file, read_document_file, delete_document_file
from app.knowledge.byd_kms import (
    BydKmsError,
    build_byd_kms_metadata,
    resolve_byd_kms_config,
    search_byd_kms,
    test_byd_kms_connection,
)
from app.core.auth.deps import get_current_user
from app.core.auth.scoping import scope_readable, assert_mutable_by_user

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])


def _kb_response(kb: KnowledgeBase) -> KnowledgeBaseResponse:
    meta = kb.metadata_ or {}
    source_type = meta.get("source_type", "local")
    byd_public = None
    if source_type == "byd_kms":
        cfg = meta.get("byd_kms") or {}
        byd_public = BydKmsConfigPublic(
            api_url=cfg.get("api_url") or "",
            user_id=cfg.get("user_id") or "",
            has_api_key=bool(cfg.get("api_key")),
        )
    return KnowledgeBaseResponse(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        status=kb.status,
        embedding_model=kb.embedding_model,
        chunk_size=kb.chunk_size,
        chunk_overlap=kb.chunk_overlap,
        document_count=kb.document_count,
        source_type=source_type,
        byd_kms=byd_public,
        created_at=kb.created_at,
        updated_at=kb.updated_at,
    )


def _is_byd_kms(kb: KnowledgeBase) -> bool:
    return (kb.metadata_ or {}).get("source_type") == "byd_kms"


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
    return [_kb_response(kb) for kb in result.scalars().all()]


@router.post("/", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    metadata: dict = {"source_type": payload.source_type}
    if payload.source_type == "byd_kms" and payload.byd_kms:
        metadata = build_byd_kms_metadata(
            api_url=payload.byd_kms.api_url,
            user_id=payload.byd_kms.user_id,
            api_key=payload.byd_kms.api_key,
        )

    kb = KnowledgeBase(
        id=generate_uuid(),
        owner_id=user.id,
        name=payload.name,
        description=payload.description,
        embedding_model=payload.embedding_model,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
        status=KBStatus.ready,
        metadata_=metadata,
    )
    db.add(kb)
    await db.flush()
    await db.refresh(kb)
    return _kb_response(kb)


@router.post("/test-byd-kms", response_model=BydKmsTestResponse)
async def test_byd_kms(
    payload: BydKmsTestRequest,
    user: User = Depends(get_current_user),
):
    _ = user
    try:
        result = await test_byd_kms_connection(
            api_url=payload.api_url,
            user_id=payload.user_id,
            api_key=payload.api_key,
            test_query=payload.test_query,
        )
        return BydKmsTestResponse(**result)
    except BydKmsError as exc:
        return BydKmsTestResponse(
            ok=False,
            message=str(exc),
            status_code=exc.status_code,
        )


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_knowledge_base(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb or not (kb.owner_id == user.id or kb.owner_id is None):
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return _kb_response(kb)


@router.patch("/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(
    kb_id: str,
    payload: KnowledgeBaseUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    assert_mutable_by_user(kb, user.id, "knowledge base")

    if payload.name is not None:
        kb.name = payload.name
    if payload.description is not None:
        kb.description = payload.description

    if payload.byd_kms is not None:
        if not _is_byd_kms(kb):
            raise HTTPException(status_code=400, detail="This knowledge base is not an API knowledge base connector")
        kb.metadata_ = build_byd_kms_metadata(
            api_url=payload.byd_kms.api_url,
            user_id=payload.byd_kms.user_id,
            api_key=payload.byd_kms.api_key,
            existing=kb.metadata_,
        )

    await db.flush()
    await db.refresh(kb)
    return _kb_response(kb)


@router.post("/{kb_id}/test-connection", response_model=BydKmsTestResponse)
async def test_knowledge_base_connection(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb or not (kb.owner_id == user.id or kb.owner_id is None):
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    cfg = resolve_byd_kms_config(kb.metadata_)
    if not cfg:
        raise HTTPException(status_code=400, detail="API knowledge base connection is not configured")

    try:
        result = await test_byd_kms_connection(
            api_url=cfg["api_url"],
            user_id=cfg["user_id"],
            api_key=cfg.get("api_key"),
        )
        return BydKmsTestResponse(**result)
    except BydKmsError as exc:
        return BydKmsTestResponse(ok=False, message=str(exc), status_code=exc.status_code)


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
    if _is_byd_kms(kb):
        raise HTTPException(
            status_code=400,
            detail="API knowledge bases are managed externally; document upload is not supported",
        )

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
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    if _is_byd_kms(kb):
        return []
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
    if _is_byd_kms(kb):
        raise HTTPException(status_code=400, detail="API knowledge bases do not store local documents")

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

    kb = await db.get(KnowledgeBase, kb_id)
    if kb and _is_byd_kms(kb):
        raise HTTPException(status_code=400, detail="API knowledge bases do not support local document deletion")

    pipeline = IngestionPipeline(knowledge_base_id=kb_id)
    await pipeline.vector_store.delete_document(doc_id)
    delete_document_file(doc.storage_path or "")
    await db.delete(doc)


@router.post("/{kb_id}/search", response_model=list[SearchResult])
async def search_knowledge_base(kb_id: str, payload: SearchRequest, db: AsyncSession = Depends(get_db)):
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    if _is_byd_kms(kb):
        try:
            results = await search_byd_kms(
                kb.metadata_ or {},
                payload.query,
                top_k=payload.top_k,
                score_threshold=payload.score_threshold,
            )
            return [SearchResult(**r) for r in results]
        except BydKmsError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    pipeline = IngestionPipeline(
        knowledge_base_id=kb_id,
        embedding_model=kb.embedding_model,
    )
    results = await pipeline.search(payload.query, top_k=payload.top_k, score_threshold=payload.score_threshold)
    return [SearchResult(**r) for r in results]
