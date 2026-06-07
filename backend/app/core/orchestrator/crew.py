"""
Crew Orchestrator - inspired by CrewAI's Crew class.

Coordinates multiple agents working together on a shared goal,
supporting Sequential, Hierarchical, and Parallel execution modes.
"""
from typing import Any, Optional
import asyncio
import structlog

from app.core.agents.base import AgentDefinition, Task
from app.core.agents.executor import AgentExecutor

logger = structlog.get_logger(__name__)


class CrewResult:
    def __init__(self, final_output: str, task_outputs: dict[str, str], token_usage: dict[str, int]):
        self.final_output = final_output
        self.task_outputs = task_outputs
        self.token_usage = token_usage

    def __str__(self) -> str:
        return self.final_output


class Crew:
    """
    A crew is a collection of agents with a shared goal, executing a list of tasks.
    """

    def __init__(
        self,
        agents: list[AgentExecutor],
        tasks: list[Task],
        process: str = "sequential",   # sequential | hierarchical | parallel
        manager_agent: Optional[AgentExecutor] = None,
        verbose: bool = False,
    ):
        self.agents = agents
        self.tasks = tasks
        self.process = process
        self.manager_agent = manager_agent
        self.verbose = verbose

        # Map agent_id to executor for quick lookup
        self._agent_map: dict[str, AgentExecutor] = {
            a.definition.id: a for a in agents
        }

    async def kickoff(self, inputs: Optional[dict[str, Any]] = None) -> CrewResult:
        log = logger.bind(process=self.process, task_count=len(self.tasks))
        log.info("crew_kickoff_start")

        inputs = inputs or {}
        if self.process == "sequential":
            return await self._run_sequential(inputs)
        elif self.process == "parallel":
            return await self._run_parallel(inputs)
        elif self.process == "hierarchical":
            return await self._run_hierarchical(inputs)
        else:
            raise ValueError(f"Unknown process type: {self.process}")

    async def _run_sequential(self, inputs: dict[str, Any]) -> CrewResult:
        task_outputs: dict[str, str] = {}
        token_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

        for i, task in enumerate(self.tasks):
            executor = self._resolve_executor(task, i)
            context = {**inputs, **task_outputs}

            result = await executor.run(task, context=context)
            output_key = f"task_{i}_{task.agent_id or 'unknown'}"
            task_outputs[output_key] = result["output"]

            usage = result.get("token_usage", {})
            token_usage["input_tokens"] += usage.get("input_tokens", 0)
            token_usage["output_tokens"] += usage.get("output_tokens", 0)

            logger.info("sequential_task_done", task_idx=i, output_len=len(result["output"]))

        final_output = list(task_outputs.values())[-1] if task_outputs else ""
        return CrewResult(final_output=final_output, task_outputs=task_outputs, token_usage=token_usage)

    async def _run_parallel(self, inputs: dict[str, Any]) -> CrewResult:
        async def run_task(i: int, task: Task):
            executor = self._resolve_executor(task, i)
            result = await executor.run(task, context=inputs)
            return i, result

        results = await asyncio.gather(*[run_task(i, t) for i, t in enumerate(self.tasks)])
        results = sorted(results, key=lambda x: x[0])

        task_outputs = {}
        token_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

        for i, result in results:
            task_outputs[f"task_{i}"] = result["output"]
            usage = result.get("token_usage", {})
            token_usage["input_tokens"] += usage.get("input_tokens", 0)
            token_usage["output_tokens"] += usage.get("output_tokens", 0)

        # Aggregate parallel results
        combined = "\n\n---\n\n".join(
            f"[Task {i}]\n{v}" for i, v in task_outputs.items()
        )
        return CrewResult(final_output=combined, task_outputs=task_outputs, token_usage=token_usage)

    async def _run_hierarchical(self, inputs: dict[str, Any]) -> CrewResult:
        """
        Manager agent first decomposes the goal into sub-tasks,
        then delegates to worker agents sequentially.
        """
        if not self.manager_agent:
            logger.warning("hierarchical_no_manager_fallback_sequential")
            return await self._run_sequential(inputs)

        # Manager decomposes
        decompose_task = Task(
            description=(
                f"You are a project manager. Decompose the following goal into "
                f"specific sub-tasks for your team.\n\nGoal: {inputs.get('input', '')}\n\n"
                f"Available agents: {[a.definition.role for a in self.agents]}\n\n"
                f"Return a JSON list of sub-tasks with keys: description, agent_role."
            )
        )
        manager_result = await self.manager_agent.run(decompose_task, context=inputs)

        # Run worker tasks sequentially with decomposed instructions
        task_outputs: dict[str, str] = {"manager_plan": manager_result["output"]}
        token_usage = manager_result.get("token_usage", {})

        for i, task in enumerate(self.tasks):
            executor = self._resolve_executor(task, i)
            result = await executor.run(task, context={**inputs, **task_outputs})
            task_outputs[f"task_{i}"] = result["output"]
            usage = result.get("token_usage", {})
            token_usage["input_tokens"] = token_usage.get("input_tokens", 0) + usage.get("input_tokens", 0)
            token_usage["output_tokens"] = token_usage.get("output_tokens", 0) + usage.get("output_tokens", 0)

        final = list(task_outputs.values())[-1]
        return CrewResult(final_output=final, task_outputs=task_outputs, token_usage=token_usage)

    def _resolve_executor(self, task: Task, fallback_index: int) -> AgentExecutor:
        if task.agent_id and task.agent_id in self._agent_map:
            return self._agent_map[task.agent_id]
        idx = fallback_index % len(self.agents)
        return self.agents[idx]
