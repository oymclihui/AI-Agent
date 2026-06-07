"""
DialogueManager - manages multi-turn conversations with agents.
Supports RAG-augmented responses, memory injection, and streaming.
"""
from typing import AsyncIterator, Optional, Any
import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.memory.manager import MemoryManager

logger = structlog.get_logger(__name__)
def _strip_thinking(text: str) -> str:
    """Remove Qwen-style thinking blocks from model output."""
    open_tag = "<" + "think" + ">"
    close_tag = "</" + "think" + ">"
    while open_tag in text:
        s = text.find(open_tag)
        e = text.find(close_tag, s)
        if e == -1:
            break
        text = text[:s] + text[e + len(close_tag):]
    return text.strip()


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
    ) -> dict[str, Any]:
        """
        Process a single user message and return the assistant's response.
        """
        from app.models_hub.router import ModelRouter

        log = logger.bind(session_id=session_id[:8])
        log.info("dialogue_chat", msg_len=len(user_message))

        llm_provider = None
        llm_model = None
        if agent_definition:
            llm_provider = agent_definition.llm_provider
            llm_model = agent_definition.llm_model
            if not system_prompt:
                system_prompt = agent_definition.system_prompt()

        llm = await ModelRouter.get_llm(provider=llm_provider, model=llm_model)

        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        if extra_system_messages:
            messages.extend(extra_system_messages)

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
        assistant_message = _strip_thinking(response.content or "")

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
    ) -> AsyncIterator[str]:
        """Stream the assistant's response token by token."""
        from app.models_hub.router import ModelRouter

        llm_provider = None
        llm_model = None
        if agent_definition:
            llm_provider = agent_definition.llm_provider
            llm_model = agent_definition.llm_model
            if not system_prompt:
                system_prompt = agent_definition.system_prompt()

        llm = await ModelRouter.get_llm(provider=llm_provider, model=llm_model)

        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        if extra_system_messages:
            messages.extend(extra_system_messages)

        history = await self.memory.get_history(session_id)
        messages.extend(history)
        messages.append(HumanMessage(content=user_message))

        full_response = ""
        buffer = ""
        async for chunk in llm.astream(messages, config={"streaming": True}):
            if chunk.content:
                buffer += chunk.content
                cleaned = _strip_thinking(buffer)
                if cleaned != full_response:
                    delta = cleaned[len(full_response):]
                    full_response = cleaned
                    if delta:
                        yield delta

        await self.memory.add_exchange(
            session_id=session_id,
            human_message=user_message,
            ai_message=full_response,
        )
