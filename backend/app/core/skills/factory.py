"""Build AgentExecutor with tools and skill injection from DB models."""
from typing import Optional

from app.core.agents.base import AgentDefinition
from app.core.agents.executor import AgentExecutor
from app.core.memory.manager import MemoryManager
from app.core.skills.injector import SkillInjector
from app.core.tools.registry import ToolRegistry
from app.db.models import Agent as AgentModel
from sqlalchemy.ext.asyncio import AsyncSession


async def build_agent_executor(
    db: AsyncSession,
    agent_model: AgentModel,
    memory_manager: Optional[MemoryManager] = None,
) -> AgentExecutor:
    tool_names = [t.get("tool_name") for t in (agent_model.tools_config or [])]
    registry = ToolRegistry.get_instance()
    tools = registry.get_tools_for_agent(tool_names)

    definition = AgentDefinition(
        id=agent_model.id,
        name=agent_model.name,
        role=agent_model.role,
        goal=agent_model.goal,
        backstory=agent_model.backstory or "",
        llm_provider=agent_model.llm_provider,
        llm_model=agent_model.llm_model,
        temperature=agent_model.temperature,
        max_iterations=agent_model.max_iterations,
        tools=tool_names,
    )
    skill_messages = await SkillInjector.build_messages(db, agent_model.skills_config)
    return AgentExecutor(
        definition=definition,
        tools=tools,
        memory_manager=memory_manager,
        skill_messages=skill_messages,
    )
