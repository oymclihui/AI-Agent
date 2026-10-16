from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from app.knowledge.loader import DocumentLoader
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, select

from app.db.session import get_db
from app.db.models import (
    Department, KnowledgeBase, KnowledgeBaseGrant, KnowledgeFaqEntry,
    KnowledgeWecomSource, Document, KBStatus, User,
)
from app.db.base import generate_uuid
from app.schemas.knowledge import (
    KnowledgeBaseCreate, KnowledgeBaseUpdate, KnowledgeBaseResponse,
    KnowledgeAccessResponse, KnowledgeAccessUpdate, KnowledgeShareTargets,
    DocumentResponse, DocumentContentResponse, DocumentChunkResponse,
    FaqEntryIn, FaqEntryOut, WecomDocSourceIn, WecomDocSourceOut,
    SearchRequest, SearchResult,
)
from app.knowledge.pipeline import IngestionPipeline
from app.knowledge.storage import save_document_file, read_document_file, delete_document_file
from app.core.auth.deps import get_current_user
from app.core.knowledge.access import can_read_kb, department_ids, grant_counts, grant_labels, readable_filter

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])
logger = structlog.get_logger(__name__)


def _kb_response(kb: KnowledgeBase, user: User, grant_count: int = 0) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        status=kb.status,
        embedding_model=kb.embedding_model,
        chunk_size=kb.chunk_size,
        chunk_overlap=kb.chunk_overlap,
        document_count=kb.document_count,
        visibility=kb.visibility or "private",
        can_manage=kb.owner_id == user.id,
        grant_count=grant_count,
        created_at=kb.created_at,
        updated_at=kb.updated_at,
    )


def _doc_out(doc: Document) -> DocumentResponse:
    meta = doc.metadata_ or {}
    return DocumentResponse(
        id=doc.id,
        knowledge_base_id=doc.knowledge_base_id,
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        status=doc.status,
        chunk_count=doc.chunk_count or 0,
        stage=meta.get("stage"),
        stages=meta.get("stages") or {},
        stage_error=meta.get("error"),
        created_at=doc.created_at,
    )


async def _require_kb(db: AsyncSession, kb_id: str, user: User, *, manage: bool = False) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb or not await can_read_kb(db, kb, user):
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    if manage and kb.owner_id != user.id:
        raise HTTPException(status_code=403, detail="只有资料库所有者可以修改")
    return kb


@router.get("/", response_model=list[KnowledgeBaseResponse])
async def list_knowledge_bases(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    dept_ids = await department_ids(db, user)
    result = await db.execute(
        select(KnowledgeBase)
        .where(readable_filter(user, dept_ids))
        .order_by(KnowledgeBase.created_at.desc())
    )
    rows = result.scalars().all()
    counts = await grant_counts(db, [kb.id for kb in rows])
    return [_kb_response(kb, user, counts.get(kb.id, 0)) for kb in rows]


@router.get("/share-targets", response_model=KnowledgeShareTargets)
async def knowledge_share_targets(
    q: str = Query("", max_length=128),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from sqlalchemy import func as sa_func

    users_out = []
    term = q.strip()
    if term:
        pattern = f"%{term}%"
        found = await db.execute(
            select(User)
            .where(
                User.is_active == True,
                User.id != user.id,
                or_(
                    User.display_name.ilike(pattern),
                    User.employee_no.ilike(pattern),
                    sa_func.lower(User.email).like(pattern.lower()),
                ),
            )
            .order_by(User.display_name.asc())
            .limit(30)
        )
        users_out = [
            {
                "id": item.id,
                "display_name": item.display_name,
                "employee_no": item.employee_no,
            }
            for item in found.scalars().all()
        ]
    dept_rows = await db.execute(
        select(Department).where(Department.is_active == True).order_by(Department.name.asc()).limit(200)
    )
    return KnowledgeShareTargets(
        users=users_out,
        departments=[{"id": item.id, "name": item.name} for item in dept_rows.scalars().all()],
    )


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
        visibility="private",
        status=KBStatus.ready,
        metadata_={"source_type": "local"},
    )
    db.add(kb)
    await db.flush()
    await db.refresh(kb)
    return _kb_response(kb, user)


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_knowledge_base(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await _require_kb(db, kb_id, user)
    counts = await grant_counts(db, [kb.id])
    return _kb_response(kb, user, counts.get(kb.id, 0))


@router.get("/{kb_id}/access", response_model=KnowledgeAccessResponse)
async def get_knowledge_access(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await _require_kb(db, kb_id, user, manage=True)
    return KnowledgeAccessResponse(
        visibility=kb.visibility or "private",
        can_manage=True,
        grants=await grant_labels(db, kb.id),
    )


@router.put("/{kb_id}/access", response_model=KnowledgeAccessResponse)
async def update_knowledge_access(
    kb_id: str,
    payload: KnowledgeAccessUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await _require_kb(db, kb_id, user, manage=True)
    if payload.visibility not in ("private", "public"):
        raise HTTPException(status_code=400, detail="可见范围只能是私有或公开")
    if len(payload.grants) > 100:
        raise HTTPException(status_code=400, detail="共享对象不超过 100 个")
    seen: set[tuple[str, str]] = set()
    cleaned: list[tuple[str, str]] = []
    for item in payload.grants:
        key = (item.grantee_type, item.grantee_id)
        if key in seen:
            continue
        seen.add(key)
        if item.grantee_type == "user":
            person = await db.get(User, item.grantee_id)
            if not person or not person.is_active or person.id == user.id:
                raise HTTPException(status_code=400, detail="共享的个人不存在")
        elif item.grantee_type == "department":
            department = await db.get(Department, item.grantee_id)
            if not department or not department.is_active:
                raise HTTPException(status_code=400, detail="共享的部门不存在")
        else:
            raise HTTPException(status_code=400, detail="共享类型不正确")
        cleaned.append(key)
    kb.visibility = payload.visibility
    existing = (
        await db.execute(select(KnowledgeBaseGrant).where(KnowledgeBaseGrant.knowledge_base_id == kb.id))
    ).scalars().all()
    for row in existing:
        await db.delete(row)
    await db.flush()
    for grantee_type, grantee_id in cleaned:
        db.add(KnowledgeBaseGrant(
            id=generate_uuid(),
            knowledge_base_id=kb.id,
            grantee_type=grantee_type,
            grantee_id=grantee_id,
            granted_by=user.id,
        ))
    await db.flush()
    return KnowledgeAccessResponse(
        visibility=kb.visibility,
        can_manage=True,
        grants=await grant_labels(db, kb.id),
    )


@router.patch("/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(
    kb_id: str,
    payload: KnowledgeBaseUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await _require_kb(db, kb_id, user, manage=True)

    if payload.name is not None:
        kb.name = payload.name
    if payload.description is not None:
        kb.description = payload.description

    await db.flush()
    await db.refresh(kb)
    counts = await grant_counts(db, [kb.id])
    return _kb_response(kb, user, counts.get(kb.id, 0))


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await _require_kb(db, kb_id, user, manage=True)
    await db.delete(kb)


@router.post("/{kb_id}/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    kb_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await _require_kb(db, kb_id, user, manage=True)

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
        await pipeline.ingest_file(file_bytes, filename, doc_id)
        outcome = pipeline.last_outcome
        from app.knowledge.passages import replace_passages
        await replace_passages(db, kb_id, doc_id, filename, outcome.passages)

        doc.status = KBStatus.ready
        doc.chunk_count = outcome.chunk_count
        doc.metadata_ = {"stage": "ready", "stages": outcome.stages}
        kb.document_count = kb.document_count + 1
        await db.flush()
    except Exception as e:
        doc.status = KBStatus.error
        doc.metadata_ = {"stage": "error", "error": str(e), "stages": {}}
        await db.flush()
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")

    await db.refresh(doc)
    return _doc_out(doc)


@router.get("/{kb_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _require_kb(db, kb_id, user)
    result = await db.execute(
        select(Document)
        .where(Document.knowledge_base_id == kb_id)
        .order_by(Document.created_at.desc())
    )
    return [_doc_out(doc) for doc in result.scalars().all()]


@router.get("/{kb_id}/documents/{doc_id}/content", response_model=DocumentContentResponse)
async def get_document_content(
    kb_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _require_kb(db, kb_id, user)
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
        try:
            from app.knowledge.storage import _uploads_root
            _abs_path = str(_uploads_root() / doc.storage_path)
            _docs = await DocumentLoader.load_file(_abs_path, doc.filename)
            if _docs:
                content = "\n\n".join(d.page_content for d in _docs if d.page_content.strip())
                source = "file"
        except Exception:
            if (doc.file_type or "").lower() not in {"xlsx", "xlsm", "xls"}:
                raw = read_document_file(doc.storage_path)
                if raw is not None:
                    encoding = DocumentLoader._detect_encoding(raw)
                    content = raw.decode(encoding, errors="replace")
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
async def delete_document(
    kb_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _require_kb(db, kb_id, user, manage=True)
    doc = await db.get(Document, doc_id)
    if not doc or doc.knowledge_base_id != kb_id:
        raise HTTPException(status_code=404, detail="Document not found")

    pipeline = IngestionPipeline(knowledge_base_id=kb_id)
    try:
        await pipeline.vector_store.delete_document(doc_id)
    except Exception as exc:
        logger.warning("vector_delete_failed", doc_id=doc_id, error=str(exc))
    from app.knowledge.passages import delete_passages
    await delete_passages(db, doc_id)
    delete_document_file(doc.storage_path or "")
    await db.delete(doc)


@router.post("/{kb_id}/search", response_model=list[SearchResult])
async def search_knowledge_base(
    kb_id: str,
    payload: SearchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await _require_kb(db, kb_id, user)

    from app.knowledge.retriever import MultiKnowledgeRetriever
    retriever = MultiKnowledgeRetriever([(kb.id, kb)], db)
    docs = await retriever.aretrieve(payload.query)
    results = []
    for index, doc in enumerate(docs[:payload.top_k]):
        meta = doc.metadata or {}
        results.append(SearchResult(
            content=doc.page_content,
            score=float(meta.get("score") or 0),
            document_id=str(meta.get("document_id") or ""),
            document_name=str(meta.get("document_name") or ""),
            chunk_index=index,
            metadata={"snippet": meta.get("snippet") or ""},
        ))
    return results


async def _reindex_document(db: AsyncSession, kb: KnowledgeBase, doc: Document) -> Document:
    raw = read_document_file(doc.storage_path or "")
    if raw is None:
        raise HTTPException(status_code=400, detail="原文件不在，无法重试")
    doc.status = KBStatus.processing
    doc.metadata_ = {"stage": "parse", "stages": {"parse": "running"}}
    await db.flush()
    pipeline = IngestionPipeline(
        knowledge_base_id=kb.id,
        embedding_model=kb.embedding_model,
        chunk_size=kb.chunk_size,
        chunk_overlap=kb.chunk_overlap,
    )
    try:
        await pipeline.ingest_file(raw, doc.filename, doc.id)
        outcome = pipeline.last_outcome
        from app.knowledge.passages import replace_passages
        await replace_passages(db, kb.id, doc.id, doc.filename, outcome.passages)
        doc.status = KBStatus.ready
        doc.chunk_count = outcome.chunk_count
        doc.metadata_ = {"stage": "ready", "stages": outcome.stages}
    except Exception as exc:
        doc.status = KBStatus.error
        doc.metadata_ = {"stage": "error", "error": str(exc)}
        await db.flush()
        raise HTTPException(status_code=500, detail=f"重试失败: {exc}") from exc
    await db.flush()
    return doc


@router.post("/{kb_id}/documents/{doc_id}/retry", response_model=DocumentResponse)
async def retry_document(
    kb_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await _require_kb(db, kb_id, user, manage=True)
    doc = await db.get(Document, doc_id)
    if not doc or doc.knowledge_base_id != kb_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return _doc_out(await _reindex_document(db, kb, doc))


@router.get("/{kb_id}/faq", response_model=list[FaqEntryOut])
async def list_faq(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _require_kb(db, kb_id, user)
    rows = (
        await db.execute(
            select(KnowledgeFaqEntry)
            .where(KnowledgeFaqEntry.knowledge_base_id == kb_id)
            .order_by(KnowledgeFaqEntry.created_at.desc())
        )
    ).scalars().all()
    return [
        FaqEntryOut(
            id=row.id,
            standard_question=row.standard_question,
            similar_questions=row.similar_questions or [],
            negative_questions=row.negative_questions or [],
            answer=row.answer,
            enabled=row.enabled,
        )
        for row in rows
    ]


async def _index_faq(db: AsyncSession, kb: KnowledgeBase, entry: KnowledgeFaqEntry) -> None:
    from langchain_core.documents import Document as LcDocument
    from app.knowledge.passages import replace_passages

    questions = [entry.standard_question, *[q for q in (entry.similar_questions or []) if q.strip()]]
    pipeline = IngestionPipeline(
        knowledge_base_id=kb.id,
        embedding_model=kb.embedding_model,
        chunk_size=kb.chunk_size,
        chunk_overlap=kb.chunk_overlap,
    )
    try:
        await pipeline.vector_store.delete_document(entry.id)
    except Exception:
        pass
    if entry.enabled:
        docs = [
            LcDocument(
                page_content=question,
                metadata={"source": entry.standard_question, "chunk_index": index, "role": "faq"},
            )
            for index, question in enumerate(questions)
        ]
        await pipeline.vector_store.add_documents(docs, entry.id)
    passages = [
        {
            "role": "faq",
            "chunk_index": index,
            "parent_index": 0,
            "content": f"{question}\n{entry.answer}",
        }
        for index, question in enumerate(questions)
    ] if entry.enabled else []
    await replace_passages(db, kb.id, entry.id, entry.standard_question, passages)


def _clean_questions(items: list[str]) -> list[str]:
    cleaned = []
    for item in items:
        text = item.strip()
        if text and text not in cleaned:
            cleaned.append(text[:300])
    return cleaned[:20]


@router.post("/{kb_id}/faq", response_model=FaqEntryOut, status_code=status.HTTP_201_CREATED)
async def create_faq(
    kb_id: str,
    payload: FaqEntryIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await _require_kb(db, kb_id, user, manage=True)
    entry = KnowledgeFaqEntry(
        id=generate_uuid(),
        knowledge_base_id=kb.id,
        standard_question=payload.standard_question.strip(),
        similar_questions=_clean_questions(payload.similar_questions),
        negative_questions=_clean_questions(payload.negative_questions),
        answer=payload.answer.strip(),
        enabled=payload.enabled,
    )
    db.add(entry)
    await db.flush()
    await _index_faq(db, kb, entry)
    return FaqEntryOut(
        id=entry.id,
        standard_question=entry.standard_question,
        similar_questions=entry.similar_questions or [],
        negative_questions=entry.negative_questions or [],
        answer=entry.answer,
        enabled=entry.enabled,
    )


@router.delete("/{kb_id}/faq/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_faq(
    kb_id: str,
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await _require_kb(db, kb_id, user, manage=True)
    entry = await db.get(KnowledgeFaqEntry, entry_id)
    if not entry or entry.knowledge_base_id != kb_id:
        raise HTTPException(status_code=404, detail="FAQ 不存在")
    pipeline = IngestionPipeline(knowledge_base_id=kb.id, embedding_model=kb.embedding_model)
    try:
        await pipeline.vector_store.delete_document(entry.id)
    except Exception:
        pass
    from app.knowledge.passages import delete_passages
    await delete_passages(db, entry.id)
    await db.delete(entry)


def _wecom_out(source: KnowledgeWecomSource | None) -> WecomDocSourceOut:
    if source is None:
        return WecomDocSourceOut()
    return WecomDocSourceOut(
        enabled=bool(source.enabled),
        corp_id=source.corp_id or "",
        secret_set=bool(source.secret_encrypted),
        doc_ids=source.doc_ids or [],
        last_status=source.last_status or "",
        last_error=source.last_error or "",
    )


@router.get("/{kb_id}/wecom-docs", response_model=WecomDocSourceOut)
async def get_wecom_docs(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _require_kb(db, kb_id, user, manage=True)
    source = (
        await db.execute(select(KnowledgeWecomSource).where(KnowledgeWecomSource.knowledge_base_id == kb_id))
    ).scalar_one_or_none()
    return _wecom_out(source)


@router.put("/{kb_id}/wecom-docs", response_model=WecomDocSourceOut)
async def save_wecom_docs(
    kb_id: str,
    payload: WecomDocSourceIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.core.data_ask.credentials import encrypt_secret

    await _require_kb(db, kb_id, user, manage=True)
    source = (
        await db.execute(select(KnowledgeWecomSource).where(KnowledgeWecomSource.knowledge_base_id == kb_id))
    ).scalar_one_or_none()
    if source is None:
        source = KnowledgeWecomSource(id=generate_uuid(), knowledge_base_id=kb_id)
        db.add(source)
    source.enabled = payload.enabled
    source.corp_id = payload.corp_id.strip()
    if payload.secret.strip():
        source.secret_encrypted = encrypt_secret(payload.secret.strip())
    source.doc_ids = [item.strip() for item in payload.doc_ids if item.strip()][:20]
    await db.flush()
    return _wecom_out(source)


@router.post("/{kb_id}/wecom-docs/sync", response_model=WecomDocSourceOut)
async def sync_wecom_docs(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.knowledge.wecom_docs import sync_source

    await _require_kb(db, kb_id, user, manage=True)
    source = (
        await db.execute(select(KnowledgeWecomSource).where(KnowledgeWecomSource.knowledge_base_id == kb_id))
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=400, detail="请先保存企业微信文档配置")
    await sync_source(db, source)
    await db.flush()
    return _wecom_out(source)
