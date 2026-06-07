"""
Memory Manager - supports Buffer, Summary, and Vector memory backends.
Inspired by LangChain's memory system.
"""
from typing import Optional
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
import structlog

logger = structlog.get_logger(__name__)


class MemoryManager:
    def __init__(self, memory_type: str = "buffer", max_tokens: int = 4000, k: int = 10):
        self.memory_type = memory_type
        self.max_tokens = max_tokens
        self.k = k
        self._buffer: dict[str, list[dict]] = {}

    async def get_history(self, session_id: str) -> list[BaseMessage]:
        raw = self._buffer.get(session_id, [])
        messages = []
        for entry in raw[-self.k * 2:]:  # keep last k pairs
            if entry["role"] == "human":
                messages.append(HumanMessage(content=entry["content"]))
            elif entry["role"] == "ai":
                messages.append(AIMessage(content=entry["content"]))
        return messages

    async def add_exchange(self, session_id: str, human_message: str, ai_message: str) -> None:
        if session_id not in self._buffer:
            self._buffer[session_id] = []
        self._buffer[session_id].append({"role": "human", "content": human_message})
        self._buffer[session_id].append({"role": "ai", "content": ai_message})

        # Trim to prevent unbounded growth
        if len(self._buffer[session_id]) > self.k * 4:
            self._buffer[session_id] = self._buffer[session_id][-(self.k * 2):]

    async def clear(self, session_id: str) -> None:
        self._buffer.pop(session_id, None)

    async def get_context_string(self, session_id: str) -> str:
        messages = await self.get_history(session_id)
        lines = []
        for msg in messages:
            role = "Human" if isinstance(msg, HumanMessage) else "Assistant"
            lines.append(f"{role}: {msg.content}")
        return "\n".join(lines)


class RedisMemoryManager(MemoryManager):
    """
    Persistent memory backed by Redis.
    Each session is stored as a Redis list of JSON messages.
    """

    def __init__(self, redis_client, memory_type: str = "buffer", k: int = 20):
        super().__init__(memory_type=memory_type, k=k)
        self.redis = redis_client

    def _key(self, session_id: str) -> str:
        return f"aiagnet:memory:{session_id}"

    async def get_history(self, session_id: str) -> list[BaseMessage]:
        import json
        raw = await self.redis.lrange(self._key(session_id), -self.k * 2, -1)
        messages = []
        for item in raw:
            entry = json.loads(item)
            if entry["role"] == "human":
                messages.append(HumanMessage(content=entry["content"]))
            elif entry["role"] == "ai":
                messages.append(AIMessage(content=entry["content"]))
        return messages

    async def add_exchange(self, session_id: str, human_message: str, ai_message: str) -> None:
        import json
        key = self._key(session_id)
        pipe = self.redis.pipeline()
        pipe.rpush(key, json.dumps({"role": "human", "content": human_message}))
        pipe.rpush(key, json.dumps({"role": "ai", "content": ai_message}))
        pipe.ltrim(key, -self.k * 4, -1)
        await pipe.execute()

    async def clear(self, session_id: str) -> None:
        await self.redis.delete(self._key(session_id))
