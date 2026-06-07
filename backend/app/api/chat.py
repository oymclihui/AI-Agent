from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json

from app.db.session import get_db
from app.db.models import (
    Conversation, Message, Agent as AgentModel, MessageRole
)
from app.db.base import generate_uuid
from app.schemas.chat import (
    ConversationCreate, ConversationResponse,
    MessageResponse, ChatRequest,
)
from app.core.agents.base import AgentDefinition
from app.core.dialogue.manager import DialogueManager
from app.core.memory.manager import MemoryManager
from app.core.skills.injector import SkillInjector

router = APIRouter(prefix="/chat", tags=["Chat"])

# In-memory memory managers keyed by conversation_id
# In production use RedisMemoryManager
_memory_managers: dict[str, MemoryManager] = {}


def get_memory_manager(conversation_id: str, memory_type: str = "buffer") -> MemoryManager:
    if conversation_id not in _memory_managers:
        _memory_managers[conversation_id] = MemoryManager(memory_type=memory_type)
    return _memory_managers[conversation_id]


async def _ensure_memory_loaded(conv_id: str, memory_type: str, db: AsyncSession) -> MemoryManager:
    """Rehydrate in-memory conversation history from DB after server restart."""
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


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(payload: ConversationCreate, db: AsyncSession = Depends(get_db)):
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
async def list_conversations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Conversation).where(Conversation.is_active == True).order_by(Conversation.created_at.desc())
    )
    return result.scalars().all()


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageResponse])
async def get_messages(conv_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    return result.scalars().all()


@router.post("/conversations/{conv_id}/messages")
async def send_message(
    conv_id: str,
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Load agent if assigned
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

    memory = await _ensure_memory_loaded(conv_id, conv.memory_type, db)
    dialogue = DialogueManager(memory_manager=memory)

    # Save user message
    user_msg = Message(
        id=generate_uuid(),
        conversation_id=conv_id,
        role=MessageRole.user,
        content=payload.message,
    )
    db.add(user_msg)
    await db.flush()

    if payload.stream:
        async def sse_stream():
            async for token in dialogue.stream(
                session_id=conv_id,
                user_message=payload.message,
                agent_definition=agent_definition,
                extra_system_messages=skill_messages,
            ):
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(sse_stream(), media_type="text/event-stream")

    result = await dialogue.chat(
        session_id=conv_id,
        user_message=payload.message,
        agent_definition=agent_definition,
        extra_system_messages=skill_messages,
    )

    # Save assistant message
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
    }


@router.post("/quick")
async def quick_chat(payload: ChatRequest):
    """
    Stateless single-turn chat without creating a conversation.
    """
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
