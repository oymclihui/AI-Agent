"""
AgentExecutor: runs a single agent against a task using LangChain's agent framework.
"""
from typing import Any, AsyncIterator, Optional
import structlog
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage
from langchain_core.tools import BaseTool

from app.core.agents.base import AgentDefinition, Task
from app.core.memory.manager import MemoryManager

logger = structlog.get_logger(__name__)


class AgentExecutor:
    def __init__(
        self,
        definition: AgentDefinition,
        tools: list[BaseTool],
        memory_manager: Optional[MemoryManager] = None,
        skill_messages: Optional[list[SystemMessage]] = None,
    ):
        self.definition = definition
        self.tools = tools
        self.memory_manager = memory_manager
        self.skill_messages = skill_messages or []
        self._llm = None

    async def _get_llm(self):
        if self._llm is None:
            from app.models_hub.router import ModelRouter
            self._llm = await ModelRouter.get_llm(
                provider=self.definition.llm_provider,
                model=self.definition.llm_model,
                temperature=self.definition.temperature,
            )
            if self.tools:
                self._llm = self._llm.bind_tools(self.tools)
        return self._llm

    async def run(self, task: Task, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Execute task and return structured result."""
        log = logger.bind(agent_id=self.definition.id, task=task.description[:80])
        log.info("agent_run_start")

        llm = await self._get_llm()
        messages: list[BaseMessage] = [SystemMessage(content=self.definition.system_prompt())]
        messages.extend(self.skill_messages)

        # Inject prior memory
        if self.memory_manager:
            history = await self.memory_manager.get_history(self.definition.id)
            messages.extend(history)

        # Inject context from upstream tasks
        if context:
            ctx_text = "\n".join(f"- {k}: {v}" for k, v in context.items())
            messages.append(SystemMessage(content=f"Context from previous tasks:\n{ctx_text}"))

        if task.expected_output:
            task_prompt = f"{task.description}\n\nExpected output format: {task.expected_output}"
        else:
            task_prompt = task.description

        messages.append(HumanMessage(content=task_prompt))

        steps = []
        final_output = ""
        token_usage: dict[str, int] = {}

        # ReAct loop with tool calling
        for iteration in range(self.definition.max_iterations):
            response = await llm.ainvoke(messages)

            if hasattr(response, "usage_metadata") and response.usage_metadata:
                token_usage = {
                    "input_tokens": response.usage_metadata.get("input_tokens", 0),
                    "output_tokens": response.usage_metadata.get("output_tokens", 0),
                }

            if not response.tool_calls:
                final_output = response.content
                steps.append({"iteration": iteration, "type": "final_answer", "content": final_output})
                break

            # Execute tool calls
            messages.append(response)
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]

                tool = next((t for t in self.tools if t.name == tool_name), None)
                if tool:
                    try:
                        tool_result = await tool.arun(tool_args)
                    except Exception as e:
                        tool_result = f"Tool error: {e}"
                else:
                    tool_result = f"Tool '{tool_name}' not found."

                steps.append({
                    "iteration": iteration,
                    "type": "tool_call",
                    "tool": tool_name,
                    "args": tool_args,
                    "result": str(tool_result)[:2000],
                })

                from langchain_core.messages import ToolMessage
                messages.append(ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_call["id"],
                ))

        # Save to memory
        if self.memory_manager:
            await self.memory_manager.add_exchange(
                session_id=self.definition.id,
                human_message=task.description,
                ai_message=final_output,
            )

        log.info("agent_run_complete", output_length=len(final_output))
        return {
            "output": final_output,
            "steps": steps,
            "token_usage": token_usage,
        }

    async def stream(self, task: Task, context: Optional[dict[str, Any]] = None) -> AsyncIterator[str]:
        """Stream the agent's response token by token."""
        llm = await self._get_llm()
        messages: list[BaseMessage] = [SystemMessage(content=self.definition.system_prompt())]
        messages.extend(self.skill_messages)
        messages.append(HumanMessage(content=task.description))

        async for chunk in llm.astream(messages):
            if chunk.content:
                yield chunk.content
