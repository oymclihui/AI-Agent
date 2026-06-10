from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json

from app.db.session import get_db
from app.db.models import (
    Conversation, Message, Agent as AgentModel, MessageRole, User,
)
from app.db.base import generate_uuid
from app.schemas.chat import (
    ConversationCreate, ConversationResponse,
    MessageResponse, ChatRequest, SuggestQuestionsResponse,
    SaveAsSkillRequest, SaveToKnowledgeRequest,
)
from app.core.auth.deps import get_current_user
from app.core.auth.scoping import scope_owned_only, assert_mutable_by_user
from app.core.chat.cleanup import cleanup_stale_conversations
from app.core.chat.export import export_conversation_to_skill, export_conversation_to_knowledge
from app.core.agents.base import AgentDefinition
from app.core.dialogue.manager import DialogueManager
from app.core.memory.manager import MemoryManager
from app.core.skills.injector import SkillInjector
from app.core.chat.attachments import build_attachment_context
from app.core.chat.storage import save_attachment_bytes, delete_conversation_uploads
from app.core.chat.suggestions import generate_attachment_questions

router = APIRouter(prefix="/chat", tags=["Chat"])

_memory_managers: dict[str, MemoryManager] = {}


def get_memory_manager(conversation_id: str, memory_type: str = "buffer") -> MemoryManager:
    if conversation_id not in _memory_managers:
        _memory_managers[conversation_id] = MemoryManager(memory_type=memory_type)
    return _memory_managers[conversation_id]


async def _ensure_memory_loaded(conv_id: str, memory_type: str, db: AsyncSession) -> MemoryManager:
    memory = get_memory_manager(conv_id, memory_type)
    if getattr(memory, "_loaded_from_db", False):
        return memory

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()
    for i in range(0, len(messages) - 1, 2):
        if messages[i].role == MessageRole.user and messages[i + 1].role == MessageRole.assistant:
            await memory.add_exchange(
                session_id=conv_id,
                human_message=messages[i].content,
                ai_message=messages[i + 1].content,
            )
    memory._loaded_from_db = True  # type: ignore[attr-defined]
    return memory


async def _resolve_agent_context(db: AsyncSession, conv: Conversation):
    agent_definition = None
    skill_messages = []
    if conv.agent_id:
        agent_model = await db.get(AgentModel, conv.agent_id)
        if agent_model:
            agent_definition = AgentDefinition(
                id=agent_model.id,
                name=agent_model.name,
                role=agent_model.role,
                goal=agent_model.goal,
                backstory=agent_model.backstory or "",
                llm_provider=agent_model.llm_provider,
                llm_model=agent_model.llm_model,
                temperature=agent_model.temperature,
            )
            skill_messages = await SkillInjector.build_messages(db, agent_model.skills_config)
    return agent_definition, skill_messages


async def _get_user_conversation(db: AsyncSession, conv_id: str, user: User) -> Conversation:
    conv = await db.get(Conversation, conv_id)
    if not conv or not conv.is_active or conv.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


async def _parse_request_body(request: Request) -> tuple[str, bool, list[tuple[str, bytes]]]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        message = str(form.get("message") or "").strip()
        stream = str(form.get("stream", "false")).lower() in ("true", "1", "yes")
        file_items: list[tuple[str, bytes]] = []
        for item in form.getlist("files"):
            if hasattr(item, "read"):
                data = await item.read()
                if not data:
                    continue
                name = getattr(item, "filename", None) or "attachment"
                file_items.append((name, data))
        if not message and not file_items:
            raise HTTPException(status_code=400, detail="message or files required")
        if not message:
            message = "请分析以上附件内容，给出结构化的分析结论与建议。"
        return message, stream, file_items

    try:
        payload = ChatRequest(**await request.json())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc
    return payload.message.strip(), payload.stream, []


async def _parse_suggest_form(request: Request) -> tuple[str, str | None, list[tuple[str, bytes]]]:
    form = await request.form()
    lang = str(form.get("lang") or "zh").strip().lower()
    if lang not in ("zh", "en"):
        lang = "zh"
    agent_id = str(form.get("agent_id") or "").strip() or None
    file_items: list[tuple[str, bytes]] = []
    for item in form.getlist("files"):
        if hasattr(item, "read"):
            data = await item.read()
            if not data:
                continue
            name = getattr(item, "filename", None) or "attachment"
            file_items.append((name, data))
    if not file_items:
        raise HTTPException(status_code=400, detail="files required")
    return lang, agent_id, file_items


async def _agent_definition_from_id(db: AsyncSession, agent_id: str | None):
    if not agent_id:
        return None
    agent_model = await db.get(AgentModel, agent_id)
    if not agent_model:
        return None
    return AgentDefinition(
        id=agent_model.id,
        name=agent_model.name,
        role=agent_model.role,
        goal=agent_model.goal,
        backstory=agent_model.backstory or "",
        llm_provider=agent_model.llm_provider,
        llm_model=agent_model.llm_model,
        temperature=agent_model.temperature,
    )


@router.post("/suggest-questions", response_model=SuggestQuestionsResponse)
async def suggest_questions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Analyze uploaded attachments and return 3 suggested user questions."""
    lang, agent_id, file_items = await _parse_suggest_form(request)
    attachment_context, attachment_meta = await build_attachment_context(file_items)
    agent_definition = await _agent_definition_from_id(db, agent_id)
    result = await generate_attachment_questions(
        attachment_context,
        attachment_meta,
        lang=lang,
        agent_definition=agent_definition,
        db=db,
        user_id=user.id,
    )
    return SuggestQuestionsResponse(**result)


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    payload: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.agent_id:
        agent = await db.get(AgentModel, payload.agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent not found: {payload.agent_id}")
    if payload.workflow_id:
        from app.db.models import Workflow as WorkflowModel
        wf = await db.get(WorkflowModel, payload.workflow_id)
        if not wf:
            raise HTTPException(status_code=404, detail=f"Workflow not found: {payload.workflow_id}")

    conv = Conversation(
        id=generate_uuid(),
        owner_id=user.id,
        title=payload.title,
        agent_id=payload.agent_id or None,
        workflow_id=payload.workflow_id or None,
        knowledge_base_ids=payload.knowledge_base_ids or [],
        memory_type=payload.memory_type,
    )
    db.add(conv)
    await db.flush()
    await db.refresh(conv)
    return conv


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await cleanup_stale_conversations()
    result = await db.execute(
        select(Conversation)
        .where(Conversation.is_active == True, scope_owned_only(Conversation, user.id))
        .order_by(Conversation.created_at.desc())
    )
    return result.scalars().all()


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageResponse])
async def get_messages(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_user_conversation(db, conv_id, user)
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    return result.scalars().all()


@router.delete("/conversations/{conv_id}", status_code=204)
async def delete_conversation(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = await _get_user_conversation(db, conv_id, user)
    _memory_managers.pop(conv_id, None)
    delete_conversation_uploads(conv_id)
    await db.delete(conv)
    await db.flush()


@router.delete("/conversations", status_code=204)
async def delete_all_conversations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.is_active == True,
            scope_owned_only(Conversation, user.id),
        )
    )
    convs = result.scalars().all()
    for conv in convs:
        _memory_managers.pop(conv.id, None)
        delete_conversation_uploads(conv.id)
        await db.delete(conv)
    await db.flush()


@router.post("/conversations/{conv_id}/messages")
async def send_message(
    conv_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = await _get_user_conversation(db, conv_id, user)

    message, stream, file_items = await _parse_request_body(request)
    agent_definition, skill_messages = await _resolve_agent_context(db, conv)
    memory = await _ensure_memory_loaded(conv_id, conv.memory_type, db)
    dialogue = DialogueManager(memory_manager=memory)

    attachment_context = ""
    attachment_meta: list[dict] = []
    if file_items:
        attachment_context, attachment_meta = await build_attachment_context(file_items)

    user_msg_id = generate_uuid()
    stored_attachments: list[dict] = []
    for filename, data in file_items:
        storage_key = save_attachment_bytes(
            conv_id,
            filename=filename,
            data=data,
            message_id=user_msg_id,
        )
        stored_attachments.append({
            **next((m for m in attachment_meta if m.get("filename") == filename), {"filename": filename}),
            "storage_key": storage_key,
        })

    user_msg = Message(
        id=user_msg_id,
        conversation_id=conv_id,
        role=MessageRole.user,
        content=message,
        metadata_={"attachments": stored_attachments} if stored_attachments else {},
    )
    db.add(user_msg)
    await db.flush()

    if stream:
        async def sse_stream():
            full = ""
            async for token in dialogue.stream(
                session_id=conv_id,
                user_message=message,
                agent_definition=agent_definition,
                extra_system_messages=skill_messages,
                attachment_context=attachment_context or None,
                db=db,
                user_id=user.id,
            ):
                full += token
                yield f"data: {json.dumps({'token': token})}\n\n"

            from app.db.session import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                assistant_msg = Message(
                    id=generate_uuid(),
                    conversation_id=conv_id,
                    role=MessageRole.assistant,
                    content=full,
                )
                session.add(assistant_msg)
                await session.commit()

            yield "data: [DONE]\n\n"

        return StreamingResponse(sse_stream(), media_type="text/event-stream")

    result = await dialogue.chat(
        session_id=conv_id,
        user_message=message,
        agent_definition=agent_definition,
        extra_system_messages=skill_messages,
        attachment_context=attachment_context or None,
        db=db,
        user_id=user.id,
    )

    assistant_msg = Message(
        id=generate_uuid(),
        conversation_id=conv_id,
        role=MessageRole.assistant,
        content=result["message"],
        token_usage=result.get("token_usage"),
    )
    db.add(assistant_msg)
    await db.flush()

    return {
        "message_id": assistant_msg.id,
        "content": assistant_msg.content,
        "token_usage": result.get("token_usage"),
        "rag_used": result.get("rag_used", False),
        "attachments": stored_attachments,
    }


@router.post("/conversations/{conv_id}/save-as-skill")
async def save_conversation_as_skill(
    conv_id: str,
    payload: SaveAsSkillRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = await _get_user_conversation(db, conv_id, user)
    try:
        skill = await export_conversation_to_skill(db, conv, user.id, title=payload.title)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"skill_id": skill.id, "slug": skill.slug, "display_name": skill.display_name}


@router.post("/conversations/{conv_id}/save-to-knowledge")
async def save_conversation_to_knowledge(
    conv_id: str,
    payload: SaveToKnowledgeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = await _get_user_conversation(db, conv_id, user)
    try:
        kb, doc = await export_conversation_to_knowledge(
            db, conv, user.id, kb_id=payload.kb_id, kb_name=payload.kb_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "knowledge_base_id": kb.id,
        "knowledge_base_name": kb.name,
        "document_id": doc.id,
        "filename": doc.filename,
    }


@router.post("/quick")
async def quick_chat(payload: ChatRequest):
    memory = MemoryManager()
    session_id = generate_uuid()
    dialogue = DialogueManager(memory_manager=memory)

    if payload.stream:
        async def sse_stream():
            async for token in dialogue.stream(
                session_id=session_id,
                user_message=payload.message,
            ):
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(sse_stream(), media_type="text/event-stream")

    result = await dialogue.chat(session_id=session_id, user_message=payload.message)
    return {"content": result["message"], "token_usage": result.get("token_usage")}
