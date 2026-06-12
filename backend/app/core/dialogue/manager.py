"""
DialogueManager - manages multi-turn conversations with agents.
Supports RAG-augmented responses, memory injection, and streaming.
"""
from typing import AsyncIterator, Optional, Any
import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory.manager import MemoryManager

logger = structlog.get_logger(__name__)

_OPEN_TAG = "<" + "think" + ">"
_CLOSE_TAG = "</" + "think" + ">"


def _extract_thinking_and_content(text: str) -> tuple[str, str]:
    """Split Qwen-style `` blocks from visible assistant text."""
    thinking_parts: list[str] = []
    remainder = text
    while _OPEN_TAG in remainder:
        start = remainder.find(_OPEN_TAG)
        prefix = remainder[:start]
        inner = remainder[start + len(_OPEN_TAG):]
        end = inner.find(_CLOSE_TAG)
        if end == -1:
            if inner:
                thinking_parts.append(inner)
            remainder = prefix
            break
        thinking_parts.append(inner[:end])
        remainder = prefix + inner[end + len(_CLOSE_TAG):]
    thinking = "\n\n".join(part.strip() for part in thinking_parts if part.strip())
    return thinking, remainder.strip()


def _strip_thinking(text: str) -> str:
    """Remove thinking blocks; keep only user-visible content."""
    _, content = _extract_thinking_and_content(text)
    return content


class DialogueManager:
    def __init__(
        self,
        memory_manager: MemoryManager,
        knowledge_retriever=None,
    ):
        self.memory = memory_manager
        self.retriever = knowledge_retriever

    async def chat(
        self,
        session_id: str,
        user_message: str,
        agent_definition=None,
        system_prompt: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
        extra_system_messages: Optional[list[SystemMessage]] = None,
        attachment_context: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Process a single user message and return the assistant's response.
        """
        from app.models_hub.router import ModelRouter

        log = logger.bind(session_id=session_id[:8])
        log.info("dialogue_chat", msg_len=len(user_message))

        llm_provider = None
        llm_model = None
        temperature = None
        if agent_definition:
            llm_provider = agent_definition.llm_provider
            llm_model = agent_definition.llm_model
            temperature = agent_definition.temperature
            if not system_prompt:
                system_prompt = agent_definition.system_prompt()

        llm = await ModelRouter.get_llm(
            provider=llm_provider,
            model=llm_model,
            temperature=temperature,
            db=db,
            user_id=user_id,
        )

        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        if extra_system_messages:
            messages.extend(extra_system_messages)
        if attachment_context:
            messages.append(SystemMessage(content=attachment_context))

        # RAG: retrieve relevant context
        rag_context = ""
        if self.retriever:
            try:
                docs = await self.retriever.aretrieve(user_message)
                if docs:
                    rag_context = "\n\n".join(d.page_content for d in docs[:3])
                    messages.append(SystemMessage(
                        content=f"Relevant knowledge base context:\n{rag_context}"
                    ))
            except Exception as e:
                log.warning("rag_retrieval_failed", error=str(e))

        # Inject memory history
        history = await self.memory.get_history(session_id)
        messages.extend(history)

        # Current user message
        messages.append(HumanMessage(content=user_message))

        response = await llm.ainvoke(messages)
        raw = response.content or ""
        thinking, assistant_message = _extract_thinking_and_content(raw)
        if not assistant_message:
            assistant_message = _strip_thinking(raw)

        token_usage = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            token_usage = {
                "input_tokens": response.usage_metadata.get("input_tokens", 0),
                "output_tokens": response.usage_metadata.get("output_tokens", 0),
            }

        await self.memory.add_exchange(
            session_id=session_id,
            human_message=user_message,
            ai_message=assistant_message,
        )

        return {
            "message": assistant_message,
            "thinking": thinking or None,
            "token_usage": token_usage,
            "rag_used": bool(rag_context),
        }

    async def stream(
        self,
        session_id: str,
        user_message: str,
        agent_definition=None,
        system_prompt: Optional[str] = None,
        extra_system_messages: Optional[list[SystemMessage]] = None,
        attachment_context: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        user_id: Optional[str] = None,
    ) -> AsyncIterator[dict[str, str]]:
        """Stream assistant output; yields ``thinking`` and/or ``token`` deltas."""
        from app.models_hub.router import ModelRouter

        llm_provider = None
        llm_model = None
        temperature = None
        if agent_definition:
            llm_provider = agent_definition.llm_provider
            llm_model = agent_definition.llm_model
            temperature = agent_definition.temperature
            if not system_prompt:
                system_prompt = agent_definition.system_prompt()

        llm = await ModelRouter.get_llm(
            provider=llm_provider,
            model=llm_model,
            temperature=temperature,
            db=db,
            user_id=user_id,
        )

        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        if extra_system_messages:
            messages.extend(extra_system_messages)
        if attachment_context:
            messages.append(SystemMessage(content=attachment_context))

        history = await self.memory.get_history(session_id)
        messages.extend(history)
        messages.append(HumanMessage(content=user_message))

        full_thinking = ""
        full_response = ""
        buffer = ""
        async for chunk in llm.astream(messages, config={"streaming": True}):
            extra = getattr(chunk, "additional_kwargs", None) or {}
            reasoning = extra.get("reasoning_content") or extra.get("reasoning")
            if reasoning:
                if isinstance(reasoning, str) and len(reasoning) > len(full_thinking):
                    delta = reasoning[len(full_thinking):]
                    full_thinking = reasoning
                    if delta:
                        yield {"thinking": delta}

            if chunk.content:
                buffer += chunk.content
                thinking, visible = _extract_thinking_and_content(buffer)

                if thinking != full_thinking:
                    delta = thinking[len(full_thinking):]
                    full_thinking = thinking
                    if delta:
                        yield {"thinking": delta}

                if visible != full_response:
                    delta = visible[len(full_response):]
                    full_response = visible
                    if delta:
                        yield {"token": delta}

        await self.memory.add_exchange(
            session_id=session_id,
            human_message=user_message,
            ai_message=full_response,
        )
