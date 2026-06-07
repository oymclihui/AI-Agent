"""
AgentCore - inspired by CrewAI's role-based agent design.
Each agent has a role, goal, backstory, tools, and memory.
"""
from dataclasses import dataclass, field
from typing import Optional, Any
from enum import Enum


class AgentType(str, Enum):
    react = "react"                   # ReAct: Reasoning + Acting
    plan_and_execute = "plan_and_execute"
    tool_calling = "tool_calling"
    conversational = "conversational"


@dataclass
class AgentDefinition:
    """
    Declarative definition of an agent - analogous to CrewAI's Agent class
    but decoupled from execution runtime.
    """
    id: str
    name: str
    role: str
    goal: str
    backstory: str = ""
    agent_type: AgentType = AgentType.react
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    temperature: float = 0.7
    max_iterations: int = 10
    tools: list[str] = field(default_factory=list)
    memory_type: str = "buffer"
    verbose: bool = False

    def system_prompt(self) -> str:
        parts = [
            f"You are {self.name}.",
            f"Role: {self.role}",
            f"Goal: {self.goal}",
        ]
        if self.backstory:
            parts.append(f"Background: {self.backstory}")
        parts.extend([
            "",
            "Always respond in a structured, professional manner.",
            "When you have completed your task, summarize your findings clearly.",
        ])
        return "\n".join(parts)


@dataclass
class Task:
    """A task to be executed by an agent, analogous to CrewAI's Task."""
    description: str
    agent_id: Optional[str] = None
    expected_output: Optional[str] = None
    context_from_tasks: list[str] = field(default_factory=list)  # task ids
    tools: list[str] = field(default_factory=list)
    async_execution: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
