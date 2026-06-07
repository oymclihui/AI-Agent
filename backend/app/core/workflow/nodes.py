"""
Node types for the workflow graph engine.
Each node is an async callable that receives and returns WorkflowState.
"""
from typing import Any, Callable, Optional
import structlog

from app.core.workflow.state import WorkflowState

logger = structlog.get_logger(__name__)


class BaseNode:
    node_type: str = "base"

    def __init__(self, node_id: str, config: dict[str, Any]):
        self.node_id = node_id
        self.config = config

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        raise NotImplementedError


class StartNode(BaseNode):
    node_type = "start"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        state.add_message("system", f"Workflow started. Input: {state.input}", self.node_id)
        logger.info("workflow_start", node_id=self.node_id)
        return state


class EndNode(BaseNode):
    node_type = "end"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        state.is_complete = True
        if not state.final_output:
            # Collect last agent output as final output
            if state.agent_outputs:
                state.final_output = list(state.agent_outputs.values())[-1]
            elif state.messages:
                state.final_output = state.messages[-1].get("content", "")
        logger.info("workflow_end", node_id=self.node_id, output_len=len(state.final_output or ""))
        return state


class AgentNode(BaseNode):
    """Executes a specific agent against the current workflow state."""
    node_type = "agent"

    def __init__(self, node_id: str, config: dict[str, Any], agent_executor=None):
        super().__init__(node_id, config)
        self.agent_executor = agent_executor

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        log = logger.bind(node_id=self.node_id)

        if not self.agent_executor:
            state.errors.append(f"AgentNode {self.node_id}: no agent configured")
            return state

        task_template = self.config.get("task", state.input)
        task_description = task_template.format(
            input=state.input,
            **state.context,
            **{f"agent_{k}": v for k, v in state.agent_outputs.items()},
        )

        from app.core.agents.base import Task
        task = Task(description=task_description)

        context = {**state.agent_outputs, **state.context}

        try:
            result = await self.agent_executor.run(task, context=context)
            output = result["output"]
            state.agent_outputs[self.node_id] = output
            state.merge_token_usage(result.get("token_usage", {}))
            state.add_message("assistant", output, self.node_id)
            log.info("agent_node_complete", output_len=len(output))
        except Exception as e:
            error_msg = f"AgentNode {self.node_id} failed: {e}"
            state.errors.append(error_msg)
            log.error("agent_node_error", error=str(e))

        return state


class ToolNode(BaseNode):
    """Calls a registered tool directly."""
    node_type = "tool"

    def __init__(self, node_id: str, config: dict[str, Any], tool=None):
        super().__init__(node_id, config)
        self.tool = tool

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        tool_input = self.config.get("input", state.input)

        if not self.tool:
            state.errors.append(f"ToolNode {self.node_id}: tool '{self.config.get('tool_name')}' not found")
            return state

        try:
            result = await self.tool.arun(tool_input)
            state.tool_results[self.node_id] = result
            state.add_message("tool", str(result), self.node_id)
        except Exception as e:
            state.errors.append(f"ToolNode {self.node_id} failed: {e}")

        return state


class ConditionNode(BaseNode):
    """
    Evaluates a condition and routes to one of multiple branches.
    Returns a routing key used by the graph engine to select the next edge.
    """
    node_type = "condition"

    def __init__(self, node_id: str, config: dict[str, Any], condition_fn: Optional[Callable] = None):
        super().__init__(node_id, config)
        self.condition_fn = condition_fn

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        return state

    def evaluate(self, state: WorkflowState) -> str:
        """Returns the routing key for the next edge."""
        if self.condition_fn:
            return self.condition_fn(state)
        expression = self.config.get("expression", "")
        if expression:
            try:
                ctx = {
                    "state": {**state.context, **state.agent_outputs, **state.tool_results},
                    "errors": state.errors,
                    "input": state.input,
                }
                result = eval(expression, {"__builtins__": {}}, ctx)  # noqa: S307
                return str(result) if result is not None else "default"
            except Exception as e:
                logger.warning("condition_eval_failed", error=str(e))
                return "default"
        return "error" if state.errors else "success"


class LLMNode(BaseNode):
    node_type = "llm"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        from app.models_hub.router import ModelRouter

        state.current_node = self.node_id
        prompt_tpl = self.config.get("prompt", "请处理以下内容：{input}")
        prompt = prompt_tpl.format(input=state.input, **state.context, **state.agent_outputs)

        model = self.config.get("model")
        provider = self.config.get("provider")
        llm = await ModelRouter.get_llm(provider=provider, model=model)
        response = await llm.ainvoke(prompt)
        output = response.content if hasattr(response, "content") else str(response)
        state.agent_outputs[self.node_id] = output
        state.add_message("assistant", output, self.node_id)
        return state


class HttpNode(BaseNode):
    node_type = "http"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        import httpx

        state.current_node = self.node_id
        method = self.config.get("method", "GET").upper()
        url = self.config.get("url", "")
        if not url:
            state.errors.append(f"HttpNode {self.node_id}: missing url")
            return state
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.request(method, url, json=self.config.get("body"))
            result = {"status": resp.status_code, "body": resp.text[:2000]}
            state.tool_results[self.node_id] = result
            state.context["http_response"] = result
        except Exception as e:
            state.errors.append(f"HttpNode {self.node_id} failed: {e}")
        return state


class CodeNode(BaseNode):
    node_type = "code"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        code = self.config.get("code", "result = {}")
        local_vars = {
            "input_data": state.context,
            "state": state.context,
            "input": state.input,
            "result": None,
        }
        try:
            exec(code, {"__builtins__": {}}, local_vars)  # noqa: S102
            result = local_vars.get("result", local_vars)
            state.tool_results[self.node_id] = result
            state.context.update(result if isinstance(result, dict) else {"code_result": result})
        except Exception as e:
            state.errors.append(f"CodeNode {self.node_id} failed: {e}")
        return state


class NoteNode(BaseNode):
    """Visual annotation only — passes state through unchanged."""
    node_type = "note"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        return state


class HumanNode(BaseNode):
    """
    Pauses execution and waits for human input.
    In practice this suspends the workflow and resumes via API.
    """
    node_type = "human"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        state.context["awaiting_human_input"] = True
        state.context["human_input_node"] = self.node_id
        state.add_message("system", "Workflow paused: awaiting human review/input.", self.node_id)
        return state
