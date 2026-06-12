"""Export desktop demos to Skill or Knowledge Base."""
from __future__ import annotations

from typing import Optional

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.chat.export import _unique_skill_slug
from app.db.base import generate_uuid
from app.db.models import (
    DesktopDemo,
    Document,
    KBStatus,
    KnowledgeBase,
    Skill,
    SkillStatus,
)
from app.knowledge.pipeline import IngestionPipeline
from app.knowledge.storage import save_document_file

logger = structlog.get_logger(__name__)


def _demo_sop_markdown(demo: DesktopDemo) -> str:
    meta = demo.metadata_ or {}
    steps = meta.get("steps") or []
    step_lines = ""
    if isinstance(steps, list) and steps:
        step_lines = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
    else:
        step_lines = "\n".join(
            f"{i + 1}. （步骤 {i + 1}）"
            for i in range(max(demo.step_count or 0, 3))
        )

    return f"""## 适用场景

在 **{demo.app_name or '目标桌面应用'}** 中重复执行「{demo.name}」相关 GUI 操作。

{demo.description or ''}

## 操作步骤

{step_lines}

## 前置条件

- 本机已启动 AI-AGENT Desktop Sidecar（`scripts/desktop_sidecar.py`）
- 演示状态：{demo.status.value if hasattr(demo.status, 'value') else demo.status}
- 记录步数：{demo.step_count or 0}

## 输出格式

- 回放完成后返回 Sidecar 执行日志与截图摘要（如有）
- 可通过数字员工 `desktop_automation` 任务定时执行

## 注意事项

- 界面布局变化可能导致回放失败，需重新录制演示
- 录屏涉及敏感数据时请启用脱敏与人工确认
- 关联演示 ID：`{demo.id}`
"""


async def export_demo_to_skill(
    db: AsyncSession,
    demo: DesktopDemo,
    user_id: str,
    *,
    use_llm: bool = True,
) -> Skill:
    from app.models_hub.router import ModelRouter

    instructions = _demo_sop_markdown(demo)
    if use_llm:
        try:
            llm = await ModelRouter.get_llm(db=db, user_id=user_id, temperature=0.3)
            response = await llm.ainvoke([
                SystemMessage(content="你是企业桌面自动化 SOP 专家，输出清晰可执行的 Markdown。"),
                HumanMessage(content=(
                    f"将以下桌面演示信息整理为 Agent Skill SOP（Markdown）：\n\n"
                    f"名称：{demo.name}\n应用：{demo.app_name}\n描述：{demo.description}\n"
                    f"步数：{demo.step_count}\n\n草稿：\n{instructions}"
                )[:80000]),
            ])
            body = (response.content or "").strip()
            if body:
                instructions = body
        except Exception as exc:
            logger.warning("demo_skill_llm_failed", demo_id=demo.id, error=str(exc))

    slug = await _unique_skill_slug(db, demo.name)
    skill = Skill(
        id=generate_uuid(),
        owner_id=user_id,
        slug=slug,
        display_name=demo.name[:255],
        description=f"由桌面演示「{demo.name}」沉淀的 GUI 操作 SOP",
        instructions_md=instructions,
        status=SkillStatus.active,
        scope="user",
        auto_invoke=False,
        tags=["desktop-automation", "from-demo"],
        metadata_={"source_demo_id": demo.id, "app_name": demo.app_name},
    )
    db.add(skill)
    await db.flush()
    await db.refresh(skill)
    return skill


async def export_demo_to_knowledge(
    db: AsyncSession,
    demo: DesktopDemo,
    user_id: str,
    *,
    kb_id: Optional[str] = None,
    kb_name: Optional[str] = None,
    use_llm: bool = True,
) -> tuple[KnowledgeBase, Document]:
    from app.config import settings
    from app.models_hub.router import ModelRouter

    markdown_body = _demo_sop_markdown(demo)
    if use_llm:
        try:
            llm = await ModelRouter.get_llm(db=db, user_id=user_id, temperature=0.3)
            response = await llm.ainvoke([
                SystemMessage(content="将桌面 GUI 演示整理为结构化 Markdown 知识文档。"),
                HumanMessage(content=markdown_body[:80000]),
            ])
            body = (response.content or "").strip()
            if body:
                markdown_body = body
        except Exception as exc:
            logger.warning("demo_kb_llm_failed", demo_id=demo.id, error=str(exc))

    filename = f"desktop-demo-{demo.id[:8]}.md"

    if kb_id:
        kb = await db.get(KnowledgeBase, kb_id)
        if not kb or (kb.owner_id not in (None, user_id)):
            raise ValueError("Knowledge base not found")
        if kb.owner_id is None:
            raise ValueError("Cannot write to shared knowledge base")
    else:
        name = kb_name or f"桌面演示-{demo.name}"
        kb = KnowledgeBase(
            id=generate_uuid(),
            owner_id=user_id,
            name=name[:255],
            description=f"由桌面演示「{demo.name}」沉淀",
            status=KBStatus.processing,
            embedding_model=settings.DEFAULT_EMBEDDING_MODEL,
            chunk_size=1000,
            chunk_overlap=200,
            metadata_={"source": "desktop-demo-export"},
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
        metadata_={"source_demo_id": demo.id},
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
