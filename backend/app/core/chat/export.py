"""Export a conversation to Skill or Knowledge Base."""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Optional

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Conversation, Message, Skill, SkillStatus,
    KnowledgeBase, Document, KBStatus, MessageRole,
)
from app.db.base import generate_uuid
from app.knowledge.pipeline import IngestionPipeline
from app.knowledge.storage import save_document_file

logger = structlog.get_logger(__name__)


def _format_transcript(messages: list[Message]) -> str:
    lines = []
    for msg in messages:
        role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        meta = msg.metadata_ or {}
        kind = meta.get("kind")
        if kind == "round_divider":
            lines.append(f"---\n*{meta.get('label', 'Round')}*\n")
            continue
        if role == "assistant" and kind == "synthesis":
            name = meta.get("agent_name") or "主持人"
            lines.append(f"### 【共识】{name}\n{msg.content.strip()}\n")
            continue
        if role == "assistant" and kind == "agent_turn":
            name = meta.get("agent_name") or "Agent"
            rnd = meta.get("round")
            suffix = f" R{rnd}" if rnd else ""
            lines.append(f"### {name}{suffix}\n{msg.content.strip()}\n")
            continue
        label = {"user": "用户", "assistant": "助手"}.get(role, role)
        lines.append(f"### {label}\n{msg.content.strip()}\n")
    return "\n".join(lines)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text.lower().strip())
    return slug.strip("-")[:48] or "chat-skill"


async def _unique_skill_slug(db: AsyncSession, base: str) -> str:
    slug = _slugify(base)
    candidate = slug
    n = 2
    while True:
        result = await db.execute(select(Skill).where(Skill.slug == candidate).limit(1))
        if not result.scalar_one_or_none():
            return candidate
        candidate = f"{slug}-{n}"[:64]
        n += 1


async def materialize_skill_from_spec(
    db: AsyncSession,
    conv: Conversation,
    user_id: str,
    skill_spec: dict,
    *,
    title: Optional[str] = None,
    knowledge_base_ids: Optional[list[str]] = None,
) -> Skill:
    """Create a Skill from deposit draft JSON; LLM fallback if body missing."""
    skill_title = title or skill_spec.get("display_name") or conv.title or "对话技能"
    instructions = (skill_spec.get("instructions_md") or skill_spec.get("instructions") or "").strip()
    if not instructions:
        skill = await export_conversation_to_skill(db, conv, user_id, title=skill_title)
        if knowledge_base_ids:
            skill.knowledge_base_ids = list(knowledge_base_ids)
            await db.flush()
        return skill

    slug = await _unique_skill_slug(db, skill_title)
    description = (skill_spec.get("description") or f"由对话「{conv.title or conv.id[:8]}」沉淀的技能 SOP").strip()
    skill = Skill(
        id=generate_uuid(),
        owner_id=user_id,
        slug=slug,
        display_name=str(skill_title)[:255],
        description=description[:2000],
        instructions_md=instructions,
        status=SkillStatus.active,
        scope="user",
        auto_invoke=False,
        tags=["from-chat"],
        knowledge_base_ids=list(knowledge_base_ids or []),
        metadata_={"source_conversation_id": conv.id, "from_deposit": True},
    )
    db.add(skill)
    await db.flush()
    await db.refresh(skill)
    return skill


async def _ingest_markdown_document(
    db: AsyncSession,
    conv: Conversation,
    user_id: str,
    markdown_body: str,
    *,
    kb_id: Optional[str] = None,
    kb_name: Optional[str] = None,
    filename: Optional[str] = None,
) -> tuple[KnowledgeBase, Document]:
    from app.config import settings

    if kb_id:
        kb = await db.get(KnowledgeBase, kb_id)
        if not kb or (kb.owner_id not in (None, user_id)):
            raise ValueError("Knowledge base not found")
        if kb.owner_id is None:
            raise ValueError("Cannot write to shared knowledge base")
    else:
        name = kb_name or f"对话沉淀-{conv.title or conv.id[:8]}"
        kb = KnowledgeBase(
            id=generate_uuid(),
            owner_id=user_id,
            name=name[:255],
            description="由对话自动沉淀的知识",
            status=KBStatus.processing,
            embedding_model=settings.DEFAULT_EMBEDDING_MODEL,
            chunk_size=1000,
            chunk_overlap=200,
            metadata_={"source": "chat-export"},
        )
        db.add(kb)
        await db.flush()

    doc_id = generate_uuid()
    safe_name = filename or f"chat-{conv.id[:8]}.md"
    file_bytes = markdown_body.encode("utf-8")
    doc = Document(
        id=doc_id,
        knowledge_base_id=kb.id,
        filename=safe_name,
        file_type="md",
        file_size=len(file_bytes),
        status=KBStatus.processing,
        storage_path=save_document_file(kb.id, doc_id, safe_name, file_bytes),
        metadata_={"source_conversation_id": conv.id, "from_deposit": True},
    )
    db.add(doc)
    await db.flush()

    pipeline = IngestionPipeline(
        knowledge_base_id=kb.id,
        embedding_model=kb.embedding_model,
        chunk_size=kb.chunk_size,
        chunk_overlap=kb.chunk_overlap,
    )
    chunk_count = await pipeline.ingest_file(file_bytes, safe_name, doc.id)
    doc.status = KBStatus.ready
    doc.chunk_count = chunk_count
    kb.status = KBStatus.ready
    kb.document_count = (kb.document_count or 0) + 1
    await db.flush()
    await db.refresh(kb)
    await db.refresh(doc)
    return kb, doc


async def materialize_knowledge_from_spec(
    db: AsyncSession,
    conv: Conversation,
    user_id: str,
    kb_spec: dict,
    *,
    kb_id: Optional[str] = None,
    kb_name: Optional[str] = None,
) -> tuple[KnowledgeBase, Document]:
    """Create KB document from deposit draft JSON; LLM fallback if body missing."""
    body = (kb_spec.get("document_md") or kb_spec.get("summary") or "").strip()
    if not body:
        return await export_conversation_to_knowledge(
            db, conv, user_id, kb_id=kb_id, kb_name=kb_name or kb_spec.get("kb_name"),
        )
    return await _ingest_markdown_document(
        db,
        conv,
        user_id,
        body,
        kb_id=kb_id,
        kb_name=kb_name or kb_spec.get("kb_name"),
    )


def export_conversation_md(
    title: str,
    messages: list[Message],
    *,
    lang: str = "zh",
) -> str:
    heading = title or ("对话导出" if lang == "zh" else "Chat Export")
    body = _format_transcript(messages)
    return f"# {heading}\n\n{body}".strip() + "\n"


async def export_conversation_document(
    db: AsyncSession,
    conv: Conversation,
    user_id: str,
    *,
    fmt: str = "md",
    lang: str = "zh",
    include_attachments: bool = False,
) -> tuple[bytes, str, str]:
    from app.config import settings
    from app.core.doc_export import FORMAT_MEDIA, convert_markdown, normalize_format, replace_extension

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()
    md = export_conversation_md(conv.title or "", messages, lang=lang)
    normalized = normalize_format(fmt)
    title = conv.title or ("对话" if lang == "zh" else "Chat")
    data = convert_markdown(md, normalized, title=title)
    filename = replace_extension(f"chat-{conv.id[:8]}.md", normalized)

    if include_attachments:
        upload_dir = Path(settings.LOCAL_UPLOADS_DIR) / "chat" / conv.id
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(filename, data)
            if upload_dir.is_dir():
                for path in upload_dir.rglob("*"):
                    if path.is_file():
                        arc = f"attachments/{path.relative_to(upload_dir).as_posix()}"
                        zf.write(path, arcname=arc)
        return buf.getvalue(), replace_extension(f"chat-{conv.id[:8]}.zip", "zip"), "application/zip"

    return data, filename, FORMAT_MEDIA[normalized]


async def export_conversation_to_skill(
    db: AsyncSession,
    conv: Conversation,
    user_id: str,
    *,
    title: Optional[str] = None,
) -> Skill:
    from app.core.chat.llm_context import get_llm_for_conversation

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()
    transcript = _format_transcript(messages)

    llm = await get_llm_for_conversation(db, conv, user_id, temperature=0.3)
    skill_title = title or conv.title or "对话技能"
    prompt = (
        "将以下对话提炼为可复用的 Agent Skill（SOP）。输出 Markdown，包含：\n"
        "## 适用场景\n## 操作步骤\n## 输出格式\n## 注意事项\n\n"
        f"技能名称参考：{skill_title}\n\n对话记录：\n{transcript[:120000]}"
    )
    response = await llm.ainvoke([
        SystemMessage(content="你是企业知识沉淀专家，输出清晰可执行的 SOP Markdown。"),
        HumanMessage(content=prompt),
    ])
    instructions = (response.content or "").strip()
    slug = await _unique_skill_slug(db, skill_title)

    skill = Skill(
        id=generate_uuid(),
        owner_id=user_id,
        slug=slug,
        display_name=skill_title[:255],
        description=f"由对话「{conv.title or conv.id[:8]}」沉淀的技能 SOP",
        instructions_md=instructions,
        status=SkillStatus.active,
        scope="user",
        auto_invoke=False,
        tags=["from-chat"],
        metadata_={"source_conversation_id": conv.id},
    )
    db.add(skill)
    await db.flush()
    await db.refresh(skill)
    return skill


async def export_conversation_to_knowledge(
    db: AsyncSession,
    conv: Conversation,
    user_id: str,
    *,
    kb_id: Optional[str] = None,
    kb_name: Optional[str] = None,
) -> tuple[KnowledgeBase, Document]:
    from app.core.chat.llm_context import get_llm_for_conversation
    from app.config import settings

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()
    transcript = _format_transcript(messages)

    llm = await get_llm_for_conversation(db, conv, user_id, temperature=0.3)
    response = await llm.ainvoke([
        SystemMessage(content="将对话整理为结构化 Markdown 知识文档，含摘要、要点、结论与可引用细节。"),
        HumanMessage(content=transcript[:120000]),
    ])
    markdown_body = (response.content or transcript).strip()
    filename = f"chat-{conv.id[:8]}.md"

    if kb_id:
        kb = await db.get(KnowledgeBase, kb_id)
        if not kb or (kb.owner_id not in (None, user_id)):
            raise ValueError("Knowledge base not found")
        if kb.owner_id is None:
            raise ValueError("Cannot write to shared knowledge base")
    else:
        name = kb_name or f"对话沉淀-{conv.title or conv.id[:8]}"
        kb = KnowledgeBase(
            id=generate_uuid(),
            owner_id=user_id,
            name=name[:255],
            description="由对话自动沉淀的知识",
            status=KBStatus.processing,
            embedding_model=settings.DEFAULT_EMBEDDING_MODEL,
            chunk_size=1000,
            chunk_overlap=200,
            metadata_={"source": "chat-export"},
        )
        db.add(kb)
        await db.flush()

    doc_id = generate_uuid()
    file_bytes = markdown_body.encode("utf-8")
    doc = Document(
        id=doc_id,
        knowledge_base_id=kb.id,
        filename=filename,
        file_type="md",
        file_size=len(file_bytes),
        status=KBStatus.processing,
        storage_path=save_document_file(kb.id, doc_id, filename, file_bytes),
        metadata_={"source_conversation_id": conv.id},
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
    await db.flush()
    await db.refresh(kb)
    await db.refresh(doc)
    return kb, doc
