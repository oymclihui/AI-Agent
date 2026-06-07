"""
Node types for the workflow graph engine.
Each node is an async callable that receives and returns WorkflowState.
"""
from typing import Any, Callable, Optional
import asyncio
import json
import re
import structlog

from app.core.workflow.state import WorkflowState

logger = structlog.get_logger(__name__)


def _template_vars(state: WorkflowState, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build format() kwargs without duplicate keys (e.g. input in context)."""
    variables: dict[str, Any] = {"input": state.input}
    for src in (state.context, state.agent_outputs, extra or {}):
        for key, value in src.items():
            if key not in variables:
                variables[key] = value
    return variables


def resolve_value(value: Any, state: WorkflowState) -> Any:
    """Resolve n8n-style {{ $json.field }} and {input} templates."""
    if isinstance(value, str):
        if "{{" in value:
            ctx = _template_vars(state, {"$json": state.context, "$input": state.input})
            def replacer(match: re.Match) -> str:
                expr = match.group(1).strip()
                if expr.startswith("$json."):
                    key = expr[6:]
                    v = state.context.get(key, "")
                    return str(v)
                if expr == "$input":
                    return state.input
                return str(ctx.get(expr.lstrip("$"), match.group(0)))
            value = re.sub(r"\{\{\s*(.+?)\s*\}\}", replacer, value)
        if "{" in value:
            try:
                return value.format(**_template_vars(state))
            except (KeyError, ValueError):
                return value
    elif isinstance(value, dict):
        return {k: resolve_value(v, state) for k, v in value.items()}
    elif isinstance(value, list):
        return [resolve_value(v, state) for v in value]
    return value


def resolve_config(config: dict[str, Any], state: WorkflowState) -> dict[str, Any]:
    return {k: resolve_value(v, state) for k, v in config.items()}


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
            **_template_vars(
                state,
                {f"agent_{k}": v for k, v in state.agent_outputs.items()},
            ),
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
                if isinstance(result, bool):
                    return "true" if result else "false"
                return str(result) if result is not None else "default"
            except Exception as e:
                logger.warning("condition_eval_failed", error=str(e))
                return "false"
        if state.errors:
            return "false"
        return "true"


class LLMNode(BaseNode):
    node_type = "llm"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        from app.models_hub.router import ModelRouter

        state.current_node = self.node_id
        prompt_tpl = self.config.get("prompt", "请处理以下内容：{input}")
        prompt = prompt_tpl.format(**_template_vars(state))

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
        cfg = resolve_config(self.config, state)
        method = cfg.get("method", "GET").upper()
        url = cfg.get("url", "")
        if not url:
            state.errors.append(f"HttpNode {self.node_id}: missing url")
            return state
        headers = {}
        if cfg.get("sendHeaders") and isinstance(cfg.get("headerParameters"), dict):
            for param in cfg["headerParameters"].get("parameters", []):
                if isinstance(param, dict):
                    headers[param.get("name", "")] = param.get("value", "")
        params = {}
        if cfg.get("sendQuery") and isinstance(cfg.get("queryParameters"), dict):
            for param in cfg["queryParameters"].get("parameters", []):
                if isinstance(param, dict):
                    params[param.get("name", "")] = param.get("value", "")
        body = cfg.get("body") if cfg.get("sendBody", True) else None
        timeout = float(cfg.get("timeout", 30))
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=not cfg.get("ignoreSslIssues")) as client:
                resp = await client.request(method, url, json=body, headers=headers or None, params=params or None)
            try:
                body_json = resp.json()
            except Exception:
                body_json = resp.text[:5000]
            result = {"status": resp.status_code, "body": body_json, "headers": dict(resp.headers)}
            state.tool_results[self.node_id] = result
            state.context["http_response"] = result
            state.context["last_http_status"] = resp.status_code
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
        cfg = resolve_config(self.config, state)
        state.context["awaiting_human_input"] = True
        state.context["human_input_node"] = self.node_id
        prompt = cfg.get("prompt", "Workflow paused: awaiting human review/input.")
        state.context["human_prompt"] = prompt
        state.add_message("system", prompt, self.node_id)
        return state


class TriggerNode(BaseNode):
    """Trigger nodes pass through and attach trigger metadata."""
    node_type = "trigger"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        cfg = resolve_config(self.config, state)
        state.context["trigger"] = {"type": self.config.get("_catalog_id", "manual"), **cfg}
        state.add_message("system", f"Trigger activated: {self.config.get('_catalog_id', 'manual')}", self.node_id)
        return state


class SwitchNode(BaseNode):
    node_type = "switch"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        return state

    def evaluate(self, state: WorkflowState) -> str:
        cfg = resolve_config(self.config, state)
        if cfg.get("mode") == "expression" and cfg.get("expression"):
            try:
                ctx = {"state": state.context, "input": state.input, "errors": state.errors}
                result = eval(cfg["expression"], {"__builtins__": {}}, ctx)  # noqa: S307
                return str(result)
            except Exception as e:
                logger.warning("switch_eval_failed", error=str(e))
        rules = cfg.get("rules", {}).get("rules", [])
        for i, rule in enumerate(rules):
            expr = rule.get("expression", "")
            if expr:
                try:
                    ctx = {"state": state.context, "input": state.input}
                    if eval(expr, {"__builtins__": {}}, ctx):  # noqa: S307
                        return str(i)
                except Exception:
                    continue
        return "default"


class SetNode(BaseNode):
    node_type = "set"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        cfg = resolve_config(self.config, state)
        if cfg.get("mode") == "json" and isinstance(cfg.get("jsonOutput"), dict):
            state.context.update(cfg["jsonOutput"])
        else:
            for item in cfg.get("assignments", {}).get("assignments", []):
                if isinstance(item, dict):
                    state.context[item.get("name", "field")] = item.get("value", "")
        state.tool_results[self.node_id] = dict(state.context)
        return state


class MergeNode(BaseNode):
    node_type = "merge"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        cfg = resolve_config(self.config, state)
        branches = state.context.setdefault("_merge_buffers", {})
        branches.setdefault(self.node_id, []).append(dict(state.context))
        state.context["merge_mode"] = cfg.get("mode", "append")
        return state


class SplitNode(BaseNode):
    node_type = "split"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        cfg = resolve_config(self.config, state)
        batch_size = int(cfg.get("batchSize", 10))
        items = state.context.get("items", [state.input])
        if not isinstance(items, list):
            items = [items]
        batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
        state.context["batches"] = batches
        state.context["batch_count"] = len(batches)
        state.tool_results[self.node_id] = batches
        return state


class FilterNode(BaseNode):
    node_type = "filter"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        cfg = resolve_config(self.config, state)
        expr = cfg.get("expression", "")
        if expr:
            try:
                ctx = {"state": state.context, "input": state.input}
                passed = bool(eval(expr, {"__builtins__": {}}, ctx))  # noqa: S307
                if not passed:
                    state.context["filtered_out"] = True
            except Exception as e:
                state.errors.append(f"FilterNode {self.node_id}: {e}")
        return state


class WaitNode(BaseNode):
    node_type = "wait"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        cfg = resolve_config(self.config, state)
        amount = float(cfg.get("amount", 1))
        unit = cfg.get("unit", "seconds")
        multipliers = {"seconds": 1, "minutes": 60, "hours": 3600}
        seconds = amount * multipliers.get(unit, 1)
        if seconds > 0:
            await asyncio.sleep(min(seconds, 300))
        return state


class TransformNode(BaseNode):
    node_type = "transform"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        cfg = resolve_config(self.config, state)
        operation = cfg.get("operation", "parse")
        source = cfg.get("sourceField", "input")
        raw = state.context.get(source, state.input) if source != "input" else state.input
        try:
            if operation == "parse":
                state.context["parsed"] = json.loads(raw if isinstance(raw, str) else json.dumps(raw))
            elif operation == "stringify":
                state.context["json_string"] = json.dumps(raw, ensure_ascii=False)
            elif cfg.get("maxItems"):
                items = state.context.get("items", [])
                if isinstance(items, list):
                    state.context["items"] = items[: int(cfg["maxItems"])]
        except Exception as e:
            state.errors.append(f"TransformNode {self.node_id}: {e}")
        state.tool_results[self.node_id] = state.context.get("parsed", state.context)
        return state


class IntegrationNode(BaseNode):
    """Generic n8n app/integration node — executes via HTTP template or stores intent."""
    node_type = "integration"

    _ENDPOINTS: dict[str, dict[str, str]] = {
        "slack": {"base": "https://slack.com/api", "path": "/chat.postMessage"},
        "discord": {"base": "https://discord.com/api/v10", "path": "/channels/{channel_id}/messages"},
        "github": {"base": "https://api.github.com", "path": "/repos/{owner}/{repo}/issues"},
        "telegram": {"base": "https://api.telegram.org", "path": "/bot{token}/sendMessage"},
    }

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        import httpx

        state.current_node = self.node_id
        cfg = resolve_config(self.config, state)
        integration = cfg.get("_integration") or cfg.get("integration", "webhook")
        operation = cfg.get("operation", "get")
        resource = cfg.get("resource", "message")
        result = {
            "integration": integration,
            "operation": operation,
            "resource": resource,
            "status": "simulated",
            "input": state.input,
        }
        endpoint = self._ENDPOINTS.get(integration)
        creds = cfg.get("credentials") or {}
        token = creds.get("accessToken") or creds.get("apiKey") or creds.get("token")
        if endpoint and token and cfg.get("additionalFields"):
            try:
                url = endpoint["base"] + endpoint["path"]
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        url,
                        headers={"Authorization": f"Bearer {token}"},
                        json=cfg.get("additionalFields", {}),
                    )
                result = {"status": resp.status_code, "body": resp.text[:2000], "integration": integration}
            except Exception as e:
                state.errors.append(f"IntegrationNode {self.node_id} ({integration}): {e}")
                return state
        state.tool_results[self.node_id] = result
        state.context[f"{integration}_result"] = result
        state.agent_outputs[self.node_id] = json.dumps(result, ensure_ascii=False)
        return state


class SubWorkflowNode(BaseNode):
    node_type = "subworkflow"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        cfg = resolve_config(self.config, state)
        state.context["subworkflow"] = {
            "workflowId": cfg.get("workflowId"),
            "inputData": cfg.get("inputData", {}),
            "wait": cfg.get("waitForSubWorkflow", True),
            "status": "pending",
        }
        state.add_message("system", f"Sub-workflow queued: {cfg.get('workflowId')}", self.node_id)
        return state


class RespondWebhookNode(BaseNode):
    node_type = "respond_webhook"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        cfg = resolve_config(self.config, state)
        state.context["webhook_response"] = {
            "body": cfg.get("responseBody", {}),
            "statusCode": cfg.get("responseCode", 200),
            "respondWith": cfg.get("respondWith", "json"),
        }
        state.final_output = json.dumps(cfg.get("responseBody", {}), ensure_ascii=False)
        return state


class StopErrorNode(BaseNode):
    node_type = "stop_error"

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        state.current_node = self.node_id
        cfg = resolve_config(self.config, state)
        msg = cfg.get("errorMessage", "Workflow stopped")
        state.errors.append(msg)
        state.is_complete = True
        return state
