"""Export digital employee task run outputs to files or knowledge bases."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import generate_uuid
from app.db.models import (
    Document,
    EmployeeScheduledTask,
    EmployeeTaskRun,
    ExecutionStatus,
    KBStatus,
    KnowledgeBase,
)
from app.knowledge.pipeline import IngestionPipeline
from app.knowledge.storage import save_document_file

logger = structlog.get_logger(__name__)


def _run_markdown(run: EmployeeTaskRun, task: EmployeeScheduledTask | None, employee_name: str) -> str:
    output = (run.output_data or {}).get("output") or ""
    prompt = (run.input_data or {}).get("prompt") or ""
    task_name = task.name if task else "Task"
    lines = [
        f"# {employee_name} · {task_name}",
        "",
        f"- **Run ID**: {run.id}",
        f"- **Status**: {run.status.value if hasattr(run.status, 'value') else run.status}",
        f"- **Time**: {run.created_at.isoformat() if run.created_at else datetime.now(timezone.utc).isoformat()}",
        f"- **Duration**: {run.duration_ms or 0} ms",
        "",
        "## Task Prompt",
        "",
        prompt.strip() or "_(empty)_",
        "",
        "## Output",
        "",
        output.strip() or "_(empty)_",
    ]
    return "\n".join(lines)


def run_report_filename(run: EmployeeTaskRun, task: EmployeeScheduledTask | None) -> str:
    task_part = re.sub(r"[^A-Za-z0-9._-]+", "_", (task.name if task else "task"))[:40]
    date_part = (run.created_at or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M")
    return f"employee_{task_part}_{date_part}_{run.id[:8]}.md"


async def export_run_to_knowledge(
    db: AsyncSession,
    run: EmployeeTaskRun,
    task: EmployeeScheduledTask | None,
    employee_name: str,
    user_id: str,
    *,
    kb_id: Optional[str] = None,
    kb_name: Optional[str] = None,
) -> tuple[KnowledgeBase, Document]:
    if run.status != ExecutionStatus.completed:
        raise ValueError("Only completed runs can be saved to a knowledge base")
    output = (run.output_data or {}).get("output")
    if not output or not str(output).strip():
        raise ValueError("Run has no output content to save")

    markdown_body = _run_markdown(run, task, employee_name)
    filename = run_report_filename(run, task)
    file_bytes = markdown_body.encode("utf-8")

    if kb_id:
        kb = await db.get(KnowledgeBase, kb_id)
        if not kb or (kb.owner_id not in (None, user_id)):
            raise ValueError("Knowledge base not found")
        if kb.owner_id is None:
            raise ValueError("Cannot write to shared knowledge base")
        if str((kb.metadata_ or {}).get("source_type") or "") == "byd_kms":
            raise ValueError("API knowledge bases do not support local document upload")
    else:
        name = kb_name or f"数字员工报告-{employee_name[:20]}"
        kb = KnowledgeBase(
            id=generate_uuid(),
            owner_id=user_id,
            name=name[:255],
            description="由数字员工任务执行结果自动沉淀",
            status=KBStatus.processing,
            embedding_model=settings.DEFAULT_EMBEDDING_MODEL,
            chunk_size=1000,
            chunk_overlap=200,
            metadata_={"source": "employee-run-export"},
        )
        db.add(kb)
        await db.flush()

    doc_id = generate_uuid()
    doc = Document(
        id=doc_id,
        knowledge_base_id=kb.id,
        filename=filename,
        file_type="md",
        file_size=len(file_bytes),
        status=KBStatus.processing,
        storage_path=save_document_file(kb.id, doc_id, filename, file_bytes),
        metadata_={
            "source_employee_run_id": run.id,
            "source_task_id": run.task_id,
        },
    )
    db.add(doc)
    await db.flush()

    pipeline = IngestionPipeline(
        knowledge_base_id=kb.id,
        embedding_model=kb.embedding_model,
        chunk_size=kb.chunk_size,
        chunk_overlap=kb.chunk_overlap,
    )
    chunk_count = await pipeline.ingest_file(file_bytes, filename, doc.id)
    doc.status = KBStatus.ready
    doc.chunk_count = chunk_count
    kb.status = KBStatus.ready
    kb.document_count = (kb.document_count or 0) + 1

    meta = dict(run.output_data or {})
    meta["saved_to_kb_id"] = kb.id
    meta["saved_document_id"] = doc.id
    run.output_data = meta

    await db.flush()
    await db.refresh(kb)
    await db.refresh(doc)
    logger.info("employee_run_saved_to_kb", run_id=run.id, kb_id=kb.id, doc_id=doc.id)
    return kb, doc
