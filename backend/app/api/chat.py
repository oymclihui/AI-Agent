from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
import json
import structlog

from app.db.session import get_db
from app.db.models import (
    Conversation, Message, Agent as AgentModel, MessageRole, User, ModelConfig,
)
from app.db.base import generate_uuid
from app.schemas.chat import (
    ConversationCreate, ConversationResponse, ConversationContextUpdate,
    MessageResponse, ChatRequest, SuggestQuestionsResponse, TranscribeResponse,
    SaveAsSkillRequest, SaveToKnowledgeRequest, DeleteOkResponse,
    DepositSuggestRequest, DepositSuggestResponse, DepositConfirmRequest, DepositConfirmResponse,
    DepositSuggestionItem, DepositDraftPreview, DepositTaskPreview,
)
from app.core.auth.deps import get_current_user
from app.core.auth.scoping import scope_owned_only, assert_mutable_by_user
from app.core.auth.agent_access import require_agent_use
from app.core.chat.cleanup import cleanup_stale_conversations
from app.core.chat.export import export_conversation_to_skill, export_conversation_to_knowledge
from app.core.agents.base import AgentDefinition, Task
from app.core.skills.factory import build_agent_executor
from app.core.dialogue.manager import DialogueManager
from app.core.memory.manager import MemoryManager
from app.core.skills.injector import SkillInjector, merge_skill_bindings, collect_knowledge_base_ids
from app.knowledge.retriever import build_multi_kb_retriever
from app.core.chat.attachments import build_attachment_context
from app.core.chat.storage import save_attachment_bytes, delete_conversation_uploads
from app.core.chat.suggestions import generate_attachment_questions
from app.core.speech.transcriber import transcribe_audio
from app.core.chat.connectors import build_connector_messages
from app.core.chat.web_context import build_web_search_messages
from app.core.chat.deposit import analyze_conversation_deposit, confirm_conversation_deposit as execute_deposit_confirm

router = APIRouter(prefix="/chat", tags=["Chat"])
logger = structlog.get_logger(__name__)


def _friendly_llm_error(exc: Exception) -> str:
    msg = str(exc).strip() or exc.__class__.__name__
    lower = msg.lower()
    if "getaddrinfo failed" in lower or "connection error" in lower or "connecterror" in lower:
        return (
            "无法连接大模型服务（请确认已接入公司内网/VPN，或在「模型配置」中将默认模型切换为 Ollama）。"
            f" 详情: {msg}"
        )
    return f"大模型调用失败: {msg}"

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


async def _resolve_effective_context(db: AsyncSession, conv: Conversation, user: User):
    """Merge conversation + agent skills/KBs for runtime injection."""
    agent_definition = None
    agent_model = None
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
                max_iterations=agent_model.max_iterations,
            )

    effective_skills = merge_skill_bindings(
        conv.skills_config,
        agent_model.skills_config if agent_model else None,
    )
    skill_messages = await SkillInjector.build_messages(db, effective_skills)

    kb_ids = await collect_knowledge_base_ids(db, conv.knowledge_base_ids, effective_skills)
    retriever = await build_multi_kb_retriever(db, kb_ids, caller_user=user)

    meta = conv.metadata_ or {}
    model_config_id = meta.get("model_config_id")
    if model_config_id:
        cfg = await db.get(ModelConfig, model_config_id)
        if cfg and cfg.is_active:
            if agent_definition:
                agent_definition.llm_provider = cfg.provider
                agent_definition.llm_model = cfg.model_id
            if agent_model:
                agent_model.llm_provider = cfg.provider
                agent_model.llm_model = cfg.model_id
            elif not agent_definition:
                agent_definition = AgentDefinition(
                    id="chat-session",
                    name="Assistant",
                    role="AI Assistant",
                    goal="Help the user with their questions and tasks",
                    llm_provider=cfg.provider,
                    llm_model=cfg.model_id,
                )

    return agent_definition, skill_messages, agent_model, retriever


def _agent_has_tools(agent_model: AgentModel | None) -> bool:
    if not agent_model:
        return False
    tools = agent_model.tools_config or []
    return any(isinstance(t, dict) and t.get("tool_name") for t in tools)


def _merge_conversation_preferences(
    conv: Conversation,
    *,
    model_config_id: str | None = None,
    connector_id: str | None = None,
    web_search_enabled: bool | None = None,
) -> None:
    meta = dict(conv.metadata_ or {})
    if model_config_id is not None:
        if model_config_id:
            meta["model_config_id"] = model_config_id
        else:
            meta.pop("model_config_id", None)
    if connector_id is not None:
        if connector_id:
            meta["connector_id"] = connector_id
        else:
            meta.pop("connector_id", None)
    if web_search_enabled is not None:
        if web_search_enabled:
            meta["web_search_enabled"] = True
        else:
            meta.pop("web_search_enabled", None)
    conv.metadata_ = meta


def _parse_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off", ""):
        return False
    return None


async def _get_user_conversation(db: AsyncSession, conv_id: str, user: User) -> Conversation:
    conv = await db.get(Conversation, conv_id)
    if not conv or not conv.is_active:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


async def _remove_conversation(db: AsyncSession, conv: Conversation) -> None:
    conv_id = conv.id
    _memory_managers.pop(conv_id, None)
    try:
        delete_conversation_uploads(conv_id)
    except Exception as exc:
        logger.warning("conversation_upload_cleanup_failed", conversation_id=conv_id, error=str(exc))
    await db.execute(delete(Message).where(Message.conversation_id == conv_id))
    await db.delete(conv)
    await db.flush()


async def _parse_request_body(
    request: Request,
) -> tuple[str, bool, list[tuple[str, bytes]], str | None, str | None, bool | None]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        message = str(form.get("message") or "").strip()
        stream = str(form.get("stream", "false")).lower() in ("true", "1", "yes")
        model_config_id = str(form.get("model_config_id") or "").strip() or None
        connector_id = str(form.get("connector_id") or "").strip() or None
        web_search_enabled = _parse_bool(form.get("web_search_enabled"))
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
        return message, stream, file_items, model_config_id, connector_id, web_search_enabled

    try:
        payload = ChatRequest(**await request.json())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc
    return (
        payload.message.strip(),
        payload.stream,
        [],
        payload.model_config_id,
        payload.connector_id,
        payload.web_search_enabled,
    )


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


async def _agent_definition_from_id(db: AsyncSession, agent_id: str | None, user: User | None = None):
    if not agent_id:
        return None
    agent_model = await db.get(AgentModel, agent_id)
    if not agent_model:
        return None
    if user is not None:
        try:
            await require_agent_use(db, agent_model, user)
        except HTTPException:
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
    agent_definition = await _agent_definition_from_id(db, agent_id, user)
    result = await generate_attachment_questions(
        attachment_context,
        attachment_meta,
        lang=lang,
        agent_definition=agent_definition,
        db=db,
        user_id=user.id,
    )
    return SuggestQuestionsResponse(**result)


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_voice(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Convert recorded speech to text (Ollama Whisper / OpenAI STT)."""
    del user
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        raise HTTPException(status_code=400, detail="multipart/form-data with audio file required")

    form = await request.form()
    lang = str(form.get("lang") or "").strip().lower()
    if lang not in ("zh", "en"):
        lang = "zh"

    audio_item = form.get("file")
    if audio_item is None or not hasattr(audio_item, "read"):
        raise HTTPException(status_code=400, detail="file required")

    data = await audio_item.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty audio file")
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="audio file too large (max 25MB)")

    filename = getattr(audio_item, "filename", None) or "recording.webm"
    try:
        text, source = await transcribe_audio(data, filename=filename, lang=lang)
    except Exception as exc:
        logger.exception("transcribe_failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return TranscribeResponse(text=text, source=source)


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    payload: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.agent_id:
        agent = await db.get(AgentModel, payload.agent_id)
        await require_agent_use(db, agent, user)
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
        skills_config=[s.model_dump() for s in payload.skills_config],
        memory_type=payload.memory_type,
        metadata_={},
    )
    _merge_conversation_preferences(
        conv,
        model_config_id=payload.model_config_id,
        connector_id=payload.connector_id,
        web_search_enabled=payload.web_search_enabled,
    )
    db.add(conv)
    await db.flush()
    await db.refresh(conv)
    return ConversationResponse.from_conversation(conv)


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
    return [ConversationResponse.from_conversation(c) for c in result.scalars().all()]


@router.get("/conversations/{conv_id}", response_model=ConversationResponse)
async def get_conversation(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = await _get_user_conversation(db, conv_id, user)
    return ConversationResponse.from_conversation(conv)


@router.patch("/conversations/{conv_id}/context", response_model=ConversationResponse)
async def update_conversation_context(
    conv_id: str,
    payload: ConversationContextUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = await _get_user_conversation(db, conv_id, user)
    unset = payload.model_dump(exclude_unset=True)

    if "agent_id" in unset:
        agent_id = unset["agent_id"]
        if agent_id:
            agent = await db.get(AgentModel, agent_id)
            await require_agent_use(db, agent, user)
        conv.agent_id = agent_id or None

    if "knowledge_base_ids" in unset:
        conv.knowledge_base_ids = unset["knowledge_base_ids"] or []

    if "skills_config" in unset:
        raw_skills = unset["skills_config"] or []
        conv.skills_config = [
            s.model_dump() if hasattr(s, "model_dump") else s for s in raw_skills
        ]

    if "model_config_id" in unset or "connector_id" in unset or "web_search_enabled" in unset:
        _merge_conversation_preferences(
            conv,
            model_config_id=unset.get("model_config_id") if "model_config_id" in unset else None,
            connector_id=unset.get("connector_id") if "connector_id" in unset else None,
            web_search_enabled=unset.get("web_search_enabled") if "web_search_enabled" in unset else None,
        )

    await db.flush()
    await db.refresh(conv)
    return ConversationResponse.from_conversation(conv)


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


@router.delete("/conversations/{conv_id}", response_model=DeleteOkResponse)
async def delete_conversation(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = await _get_user_conversation(db, conv_id, user)
    await _remove_conversation(db, conv)
    return DeleteOkResponse(ok=True, deleted=1)


@router.delete("/conversations", response_model=DeleteOkResponse)
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
        await _remove_conversation(db, conv)
    return DeleteOkResponse(ok=True, deleted=len(convs))


@router.post("/conversations/{conv_id}/messages")
async def send_message(
    conv_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = await _get_user_conversation(db, conv_id, user)

    message, stream, file_items, model_config_id, connector_id, web_search_enabled = await _parse_request_body(request)
    _merge_conversation_preferences(
        conv,
        model_config_id=model_config_id,
        connector_id=connector_id,
        web_search_enabled=web_search_enabled,
    )
    await db.flush()

    agent_definition, skill_messages, agent_model, retriever = await _resolve_effective_context(db, conv, user)
    meta = conv.metadata_ or {}
    connector_id_active = meta.get("connector_id")
    if connector_id_active:
        skill_messages = [
            *skill_messages,
            *await build_connector_messages(
                connector_id_active,
                user_id=user.id,
                db=db,
            ),
        ]

    web_search_active = bool(meta.get("web_search_enabled"))
    web_search_used = False
    if web_search_active:
        web_messages, web_search_used = await build_web_search_messages(message)
        skill_messages = [*skill_messages, *web_messages]
    memory = await _ensure_memory_loaded(conv_id, conv.memory_type, db)
    dialogue = DialogueManager(memory_manager=memory, knowledge_retriever=retriever)

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

    use_agent_tools = _agent_has_tools(agent_model)

    if use_agent_tools and agent_model:
        from app.core.auth.context import set_current_user_id, reset_current_user_id
        from app.core.harness.context import HarnessContext, reset_harness_context, set_harness_context

        ctx_token = set_current_user_id(user.id)
        harness_token = set_harness_context(
            HarnessContext(user_id=user.id, source="chat", source_id=conv_id)
        )
        try:
            executor = await build_agent_executor(db, agent_model, memory_manager=memory)
            if skill_messages:
                executor.skill_messages = [*executor.skill_messages, *skill_messages]
            task_prompt = message
            if attachment_context:
                task_prompt = f"{message}\n\n{attachment_context}"
            result = await executor.run(
                Task(description=task_prompt),
                memory_session_id=conv_id,
                db=db,
            )
            assistant_content = str(result.get("output") or "").strip()
            token_usage = result.get("token_usage", {})
            harness_trace = result.get("harness_trace", [])
        except Exception as exc:
            logger.exception("chat_agent_tools_failed", conversation_id=conv_id)
            raise HTTPException(status_code=502, detail=_friendly_llm_error(exc)) from exc
        finally:
            reset_current_user_id(ctx_token)
            reset_harness_context(harness_token)

        assistant_msg = Message(
            id=generate_uuid(),
            conversation_id=conv_id,
            role=MessageRole.assistant,
            content=assistant_content,
            token_usage=token_usage,
            metadata_={"harness_trace": harness_trace} if harness_trace else {},
        )
        db.add(assistant_msg)
        await db.flush()

        if stream:
            async def sse_agent_stream():
                yield f"data: {json.dumps({'token': assistant_content})}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(sse_agent_stream(), media_type="text/event-stream")

        return {
            "message_id": assistant_msg.id,
            "content": assistant_content,
            "token_usage": token_usage,
            "rag_used": False,
            "web_search_used": web_search_used,
            "attachments": stored_attachments,
            "agent_tools_used": True,
            "harness_trace": harness_trace,
        }

    if stream:
        async def sse_stream():
            full = ""
            thinking = ""
            try:
                async for event in dialogue.stream(
                    session_id=conv_id,
                    user_message=message,
                    agent_definition=agent_definition,
                    extra_system_messages=skill_messages,
                    attachment_context=attachment_context or None,
                    db=db,
                    user_id=user.id,
                ):
                    if event.get("thinking"):
                        thinking += event["thinking"]
                        yield f"data: {json.dumps({'thinking': event['thinking']})}\n\n"
                    if event.get("token"):
                        full += event["token"]
                        yield f"data: {json.dumps({'token': event['token']})}\n\n"
            except Exception as exc:
                detail = _friendly_llm_error(exc)
                logger.exception("chat_stream_failed", conversation_id=conv_id)
                yield f"data: {json.dumps({'error': detail})}\n\n"
                yield "data: [DONE]\n\n"
                return

            from app.db.session import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                meta = {"thinking": thinking} if thinking else {}
                assistant_msg = Message(
                    id=generate_uuid(),
                    conversation_id=conv_id,
                    role=MessageRole.assistant,
                    content=full,
                    metadata_=meta,
                )
                session.add(assistant_msg)
                await session.commit()

            yield "data: [DONE]\n\n"

        return StreamingResponse(sse_stream(), media_type="text/event-stream")

    try:
        result = await dialogue.chat(
            session_id=conv_id,
            user_message=message,
            agent_definition=agent_definition,
            extra_system_messages=skill_messages,
            attachment_context=attachment_context or None,
            db=db,
            user_id=user.id,
        )
    except Exception as exc:
        logger.exception("chat_failed", conversation_id=conv_id)
        raise HTTPException(status_code=502, detail=_friendly_llm_error(exc)) from exc

    thinking = result.get("thinking")
    assistant_msg = Message(
        id=generate_uuid(),
        conversation_id=conv_id,
        role=MessageRole.assistant,
        content=result["message"],
        token_usage=result.get("token_usage"),
        metadata_={"thinking": thinking} if thinking else {},
    )
    db.add(assistant_msg)
    await db.flush()

    return {
        "message_id": assistant_msg.id,
        "content": assistant_msg.content,
        "thinking": thinking,
        "token_usage": result.get("token_usage"),
        "rag_used": result.get("rag_used", False),
        "web_search_used": web_search_used,
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


@router.post("/conversations/{conv_id}/suggest-deposit", response_model=DepositSuggestResponse)
async def suggest_conversation_deposit(
    conv_id: str,
    payload: DepositSuggestRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = await _get_user_conversation(db, conv_id, user)
    lang = payload.lang if payload.lang in ("zh", "en") else "zh"
    try:
        raw = await analyze_conversation_deposit(db, conv, user.id, lang=lang)
    except Exception as exc:
        logger.exception("deposit_suggest_failed", conversation_id=conv_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    draft_preview = None
    if raw.get("draft"):
        d = raw["draft"]
        draft_preview = DepositDraftPreview(
            skill_title=d.get("skill_title"),
            knowledge_title=d.get("knowledge_title"),
            agent_name=d.get("agent_name"),
            employee_name=d.get("employee_name"),
            employee_title=d.get("employee_title"),
            employee_description=d.get("employee_description"),
            tasks=[DepositTaskPreview(**t) for t in d.get("tasks") or []],
        )

    suggestions = [
        DepositSuggestionItem(**s) for s in raw.get("suggestions") or []
        if isinstance(s, dict) and s.get("type")
    ]
    return DepositSuggestResponse(
        worth_deposit=bool(raw.get("worth_deposit")),
        draft_id=raw.get("draft_id"),
        suggestions=suggestions,
        draft=draft_preview,
    )


@router.post("/conversations/{conv_id}/deposit/confirm", response_model=DepositConfirmResponse)
async def confirm_conversation_deposit_route(
    conv_id: str,
    payload: DepositConfirmRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = await _get_user_conversation(db, conv_id, user)
    allowed = {"skill", "knowledge", "agent", "employee"}
    types = [t for t in payload.types if t in allowed]
    if not types:
        raise HTTPException(status_code=400, detail="At least one valid deposit type required")
    try:
        result = await execute_deposit_confirm(
            db,
            conv,
            user.id,
            draft_id=payload.draft_id,
            types=types,  # type: ignore[arg-type]
            activate_employee=payload.activate_employee,
            kb_id=payload.kb_id,
            kb_name=payload.kb_name,
            skill_title=payload.skill_title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("deposit_confirm_failed", conversation_id=conv_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return DepositConfirmResponse(**result)


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
