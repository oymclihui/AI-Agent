"""Multi-agent group chat orchestrator — visible discussion + synthesis."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Optional

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agents.base import AgentDefinition
from app.core.auth.agent_access import require_agent_use
from app.core.dialogue.manager import _extract_thinking_and_content
from app.core.group_chat.transcript import build_agent_prompt
from app.core.platform_identity import platform_identity_messages
from app.core.skills.injector import SkillInjector, merge_skill_bindings, collect_knowledge_base_ids
from app.db.base import generate_uuid
from app.db.models import Agent as AgentModel, Conversation, Message, MessageRole, User
from app.knowledge.retriever import build_multi_kb_retriever

logger = structlog.get_logger(__name__)


@dataclass
class GroupChatConfig:
    agent_ids: list[str]
    moderator_agent_id: str | None = None
    orchestration: str = "round_robin"
    max_rounds: int = 2
    auto_synthesize: bool = True
    mention_agent_id: str | None = None
    lang: str = "zh"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroupChatConfig:
        return cls(
            agent_ids=list(data.get("agent_ids") or []),
            moderator_agent_id=data.get("moderator_agent_id"),
            orchestration=str(data.get("orchestration") or "round_robin"),
            max_rounds=int(data.get("max_rounds") or 2),
            auto_synthesize=bool(data.get("auto_synthesize", True)),
            mention_agent_id=data.get("mention_agent_id"),
            lang=str(data.get("lang") or "zh"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_ids": self.agent_ids,
            "moderator_agent_id": self.moderator_agent_id,
            "orchestration": self.orchestration,
            "max_rounds": self.max_rounds,
            "auto_synthesize": self.auto_synthesize,
            "mention_agent_id": self.mention_agent_id,
            "lang": self.lang,
        }


def get_group_config_from_conversation(conv: Conversation) -> GroupChatConfig | None:
    meta = conv.metadata_ or {}
    if meta.get("chat_mode") != "group":
        return None
    group = meta.get("group") or {}
    if not group.get("agent_ids"):
        return None
    return GroupChatConfig.from_dict(group)


def parse_mention_agent_id(message: str, agents: dict[str, AgentModel]) -> str | None:
    for match in re.finditer(r"@([\w\u4e00-\u9fff\-]+)", message):
        token = match.group(1).strip()
        for aid, agent in agents.items():
            if token in (agent.name, agent.role):
                return aid
            if token.lower() in agent.role.lower() or token in agent.name:
                return aid
    return None


@dataclass
class AgentRuntime:
    model: AgentModel
    definition: AgentDefinition
    skill_messages: list[SystemMessage] = field(default_factory=list)


class GroupChatOrchestrator:
    def __init__(
        self,
        db: AsyncSession,
        conv: Conversation,
        user: User,
        config: GroupChatConfig,
        *,
        extra_skill_messages: Optional[list[SystemMessage]] = None,
    ):
        self.db = db
        self.conv = conv
        self.user = user
        self.config = config
        self.extra_skill_messages = extra_skill_messages or []
        self.agents: dict[str, AgentRuntime] = {}
        self.turns: list[dict[str, Any]] = []
        self._retriever = None

    async def load_agents(self) -> None:
        if len(self.config.agent_ids) < 2:
            raise ValueError("Group chat requires at least 2 agents")
        if len(self.config.agent_ids) > 6:
            raise ValueError("Group chat supports at most 6 agents")

        result = await self.db.execute(
            select(AgentModel).where(AgentModel.id.in_(self.config.agent_ids))
        )
        found = {a.id: a for a in result.scalars().all()}
        missing = [aid for aid in self.config.agent_ids if aid not in found]
        if missing:
            raise ValueError(f"Agents not found: {missing}")

        kb_ids = await collect_knowledge_base_ids(
            self.db, self.conv.knowledge_base_ids, self.conv.skills_config
        )
        self._retriever = await build_multi_kb_retriever(self.db, kb_ids, caller_user=self.user)

        for aid in self.config.agent_ids:
            model = found[aid]
            await require_agent_use(self.db, model, self.user)
            skills = merge_skill_bindings(self.conv.skills_config, model.skills_config)
            skill_messages = await SkillInjector.build_messages(self.db, skills)
            self.agents[aid] = AgentRuntime(
                model=model,
                definition=AgentDefinition(
                    id=model.id,
                    name=model.name,
                    role=model.role,
                    goal=model.goal,
                    backstory=model.backstory or "",
                    llm_provider=model.llm_provider,
                    llm_model=model.llm_model,
                    temperature=model.temperature,
                    max_iterations=min(model.max_iterations, 3),
                ),
                skill_messages=skill_messages,
            )

        if self.config.moderator_agent_id and self.config.moderator_agent_id not in self.agents:
            self.config.moderator_agent_id = self.config.agent_ids[0]
        if not self.config.moderator_agent_id:
            self.config.moderator_agent_id = self.config.agent_ids[0]

    async def _persist_message(
        self,
        content: str,
        *,
        kind: str,
        agent_id: str | None = None,
        round_num: int | None = None,
        turn_index: int | None = None,
        thinking: str | None = None,
    ) -> Message:
        meta: dict[str, Any] = {"kind": kind}
        if agent_id and agent_id in self.agents:
            rt = self.agents[agent_id]
            meta.update({
                "agent_id": agent_id,
                "agent_name": rt.model.name,
                "agent_role": rt.model.role,
            })
        if round_num is not None:
            meta["round"] = round_num
        if turn_index is not None:
            meta["turn_index"] = turn_index
        if thinking:
            meta["thinking"] = thinking

        msg = Message(
            id=generate_uuid(),
            conversation_id=self.conv.id,
            role=MessageRole.assistant,
            content=content,
            metadata_=meta,
        )
        self.db.add(msg)
        await self.db.flush()
        return msg

    async def _persist_round_divider(self, round_num: int) -> Message:
        label = f"第 {round_num} 轮讨论结束" if self.config.lang == "zh" else f"Round {round_num} complete"
        msg = Message(
            id=generate_uuid(),
            conversation_id=self.conv.id,
            role=MessageRole.assistant,
            content="",
            metadata_={"kind": "round_divider", "label": label, "round": round_num},
        )
        self.db.add(msg)
        await self.db.flush()
        return msg

    async def _stream_agent_response(
        self,
        runtime: AgentRuntime,
        user_prompt: str,
    ) -> AsyncIterator[dict[str, str]]:
        from app.models_hub.router import ModelRouter
        from app.models_hub.response_style import resolve_conversation_style

        meta = self.conv.metadata_ or {}
        style = resolve_conversation_style(
            meta, agent_temperature=runtime.definition.temperature,
        )

        llm = await ModelRouter.get_llm(
            provider=runtime.definition.llm_provider,
            model=runtime.definition.llm_model,
            response_style=style.value,
            db=self.db,
            user_id=self.user.id,
        )

        messages: list = [
            *platform_identity_messages(),
            SystemMessage(content=runtime.definition.system_prompt()),
            *runtime.skill_messages,
            *self.extra_skill_messages,
        ]

        if self._retriever:
            try:
                docs = await self._retriever.aretrieve(user_prompt)
                if docs:
                    rag = "\n\n".join(d.page_content for d in docs[:3])
                    messages.append(SystemMessage(content=f"Relevant knowledge:\n{rag}"))
            except Exception as exc:
                logger.warning("group_chat_rag_failed", error=str(exc))

        messages.append(HumanMessage(content=user_prompt))

        full = ""
        thinking_acc = ""
        buffer = ""
        async for chunk in llm.astream(messages, config={"streaming": True}):
            extra = getattr(chunk, "additional_kwargs", None) or {}
            reasoning = extra.get("reasoning_content") or extra.get("reasoning")
            if reasoning and isinstance(reasoning, str) and len(reasoning) > len(thinking_acc):
                delta = reasoning[len(thinking_acc):]
                thinking_acc = reasoning
                if delta:
                    yield {"type": "thinking", "thinking": delta}

            if chunk.content:
                buffer += chunk.content
                thinking, visible = _extract_thinking_and_content(buffer)
                if thinking and len(thinking) > len(thinking_acc):
                    delta = thinking[len(thinking_acc):]
                    thinking_acc = thinking
                    if delta:
                        yield {"type": "thinking", "thinking": delta}
                if visible != full:
                    delta = visible[len(full):]
                    full = visible
                    if delta:
                        yield {"type": "token", "token": delta}

    async def _run_agent_turn(
        self,
        agent_id: str,
        user_question: str,
        *,
        round_num: int,
        turn_index: int,
        is_synthesis: bool = False,
        disconnected: Callable[[], Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        runtime = self.agents[agent_id]
        subtask_id = generate_uuid()
        yield {
            "event": "agent_start",
            "subtask_id": subtask_id,
            "status": "running",
            "agent_id": agent_id,
            "agent_name": runtime.model.name,
            "agent_role": runtime.model.role,
            "round": round_num,
            "is_synthesis": is_synthesis,
        }

        prompt = build_agent_prompt(
            user_question=user_question,
            turns=self.turns,
            agent_name=runtime.model.name,
            agent_role=runtime.model.role,
            round_num=round_num,
            max_rounds=self.config.max_rounds,
            is_synthesis=is_synthesis,
            lang=self.config.lang,
        )

        full = ""
        thinking = ""
        async for part in self._stream_agent_response(runtime, prompt):
            if disconnected and await disconnected():
                break
            if part.get("type") == "token":
                full += part["token"]
                yield {"event": "token", "agent_id": agent_id, "token": part["token"]}
            elif part.get("type") == "thinking" and part.get("thinking"):
                thinking += part["thinking"]
                yield {"event": "thinking", "agent_id": agent_id, "thinking": part["thinking"]}

        if not full.strip():
            full = "（无内容）" if self.config.lang == "zh" else "(empty)"

        kind = "synthesis" if is_synthesis else "agent_turn"
        msg = await self._persist_message(
            full.strip(),
            kind=kind,
            agent_id=agent_id,
            round_num=round_num if not is_synthesis else None,
            turn_index=turn_index,
            thinking=thinking or None,
        )

        if not is_synthesis:
            self.turns.append({
                "agent_id": agent_id,
                "agent_name": runtime.model.name,
                "content": full.strip(),
                "round": round_num,
            })

        yield {
            "event": "agent_done",
            "subtask_id": subtask_id,
            "status": "completed",
            "agent_id": agent_id,
            "message_id": msg.id,
            "content": full.strip(),
            "is_synthesis": is_synthesis,
        }

    def _ordered_agents_for_round(self, round_num: int) -> list[str]:
        ids = list(self.config.agent_ids)
        if self.config.mention_agent_id and self.config.mention_agent_id in ids:
            return [self.config.mention_agent_id]
        if self.config.orchestration == "debate":
            return ids[:2] if round_num == 1 else [self.config.moderator_agent_id or ids[-1]]
        return ids

    async def stream(
        self,
        user_message: str,
        *,
        disconnected: Callable[[], Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        await self.load_agents()

        mention = parse_mention_agent_id(
            user_message, {aid: rt.model for aid, rt in self.agents.items()}
        )
        if mention:
            self.config.mention_agent_id = mention

        turn_index = 0

        if self.config.orchestration == "hierarchical":
            mod_id = self.config.moderator_agent_id or self.config.agent_ids[0]
            yield {"event": "round_start", "round": 0, "mode": "planning"}
            async for ev in self._run_agent_turn(
                mod_id, user_message, round_num=0, turn_index=turn_index,
                disconnected=disconnected,
            ):
                if disconnected and await disconnected():
                    await self.db.commit()
                    return
                yield ev
            turn_index += 1

        if self.config.orchestration == "parallel":
            yield {"event": "round_start", "round": 1, "mode": "parallel"}

            async def run_parallel(aid: str) -> list[dict]:
                subtask_id = generate_uuid()
                events: list[dict] = []
                events.append({
                    "event": "agent_start",
                    "subtask_id": subtask_id,
                    "status": "running",
                    "agent_id": aid,
                    "agent_name": self.agents[aid].model.name,
                    "agent_role": self.agents[aid].model.role,
                    "round": 1,
                    "is_synthesis": False,
                })
                prompt = build_agent_prompt(
                    user_question=user_message,
                    turns=[],
                    agent_name=self.agents[aid].model.name,
                    agent_role=self.agents[aid].model.role,
                    round_num=1,
                    max_rounds=1,
                    lang=self.config.lang,
                )
                full = ""
                async for part in self._stream_agent_response(self.agents[aid], prompt):
                    if part.get("type") == "token":
                        full += part["token"]
                        events.append({"event": "token", "agent_id": aid, "token": part["token"]})
                msg = await self._persist_message(
                    full.strip() or "（无内容）",
                    kind="agent_turn",
                    agent_id=aid,
                    round_num=1,
                    turn_index=0,
                )
                self.turns.append({
                    "agent_id": aid,
                    "agent_name": self.agents[aid].model.name,
                    "content": full.strip(),
                    "round": 1,
                })
                events.append({
                    "event": "agent_done",
                    "subtask_id": subtask_id,
                    "status": "completed",
                    "agent_id": aid,
                    "message_id": msg.id,
                })
                return events

            batches = await asyncio.gather(*[run_parallel(aid) for aid in self.config.agent_ids])
            for batch in batches:
                for ev in batch:
                    yield ev
            turn_index = len(self.config.agent_ids)
        else:
            for round_num in range(1, self.config.max_rounds + 1):
                if disconnected and await disconnected():
                    await self.db.commit()
                    return
                yield {"event": "round_start", "round": round_num}

                for agent_id in self._ordered_agents_for_round(round_num):
                    if disconnected and await disconnected():
                        await self.db.commit()
                        return
                    async for ev in self._run_agent_turn(
                        agent_id,
                        user_message,
                        round_num=round_num,
                        turn_index=turn_index,
                        disconnected=disconnected,
                    ):
                        yield ev
                    turn_index += 1

                if round_num < self.config.max_rounds:
                    divider = await self._persist_round_divider(round_num)
                    yield {"event": "round_divider", "round": round_num, "message_id": divider.id}

        if self.config.auto_synthesize and self.config.orchestration != "debate":
            if disconnected and await disconnected():
                await self.db.commit()
                return
            mod_id = self.config.moderator_agent_id or self.config.agent_ids[0]
            yield {"event": "synthesis_start", "agent_id": mod_id}
            async for ev in self._run_agent_turn(
                mod_id,
                user_message,
                round_num=self.config.max_rounds + 1,
                turn_index=turn_index,
                is_synthesis=True,
                disconnected=disconnected,
            ):
                yield ev
        elif self.config.orchestration == "debate":
            mod_id = self.config.moderator_agent_id or self.config.agent_ids[-1]
            yield {"event": "synthesis_start", "agent_id": mod_id}
            async for ev in self._run_agent_turn(
                mod_id,
                user_message,
                round_num=2,
                turn_index=turn_index,
                is_synthesis=True,
                disconnected=disconnected,
            ):
                yield ev

        await self.db.commit()
        yield {"event": "done"}
