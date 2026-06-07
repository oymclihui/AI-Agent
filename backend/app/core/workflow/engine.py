"""
WorkflowEngine - LangGraph-inspired graph-based workflow execution engine.

Executes directed graphs of nodes where each node transforms WorkflowState.
Supports conditional routing, parallel branches, and checkpointing.
"""
from typing import Any, Optional
import asyncio
import time
import structlog

from app.core.workflow.state import WorkflowState
from app.core.workflow.nodes import BaseNode, ConditionNode, EndNode, SwitchNode

logger = structlog.get_logger(__name__)


class WorkflowGraph:
    """
    Defines the structure (topology) of a workflow.
    Nodes and edges are registered here before execution.
    """

    def __init__(self, workflow_id: str):
        self.workflow_id = workflow_id
        self.nodes: dict[str, BaseNode] = {}
        self.edges: dict[str, list[str]] = {}       # node_id -> [next_node_ids]
        self.conditional_edges: dict[str, dict[str, str]] = {}  # node_id -> {key -> node_id}
        self.entry_point: Optional[str] = None

    def add_node(self, node: BaseNode) -> "WorkflowGraph":
        self.nodes[node.node_id] = node
        return self

    def add_edge(self, from_node: str, to_node: str) -> "WorkflowGraph":
        self.edges.setdefault(from_node, []).append(to_node)
        return self

    def add_conditional_edge(
        self, from_node: str, routing_map: dict[str, str]
    ) -> "WorkflowGraph":
        """
        routing_map: {"success": "node_a", "error": "node_b", ...}
        """
        self.conditional_edges[from_node] = routing_map
        return self

    def set_entry_point(self, node_id: str) -> "WorkflowGraph":
        self.entry_point = node_id
        return self

    def _get_next_nodes(self, current_node_id: str, state: WorkflowState) -> list[str]:
        node = self.nodes.get(current_node_id)

        # Conditional routing
        if current_node_id in self.conditional_edges:
            node = self.nodes.get(current_node_id)
            if isinstance(node, (ConditionNode, SwitchNode)):
                routing_key = node.evaluate(state)
                routing_map = self.conditional_edges[current_node_id]
                next_id = routing_map.get(routing_key, routing_map.get("default"))
                return [next_id] if next_id else []

        # Regular edges
        return self.edges.get(current_node_id, [])


class WorkflowEngine:
    """Executes a WorkflowGraph given an initial input."""

    def __init__(self, graph: WorkflowGraph, max_steps: int = 100):
        self.graph = graph
        self.max_steps = max_steps

    async def execute(
        self,
        input_data: dict[str, Any],
        checkpoint_callback=None,
    ) -> WorkflowState:
        state = WorkflowState(
            input=str(input_data.get("input", "")),
            context=input_data,
        )

        entry = self.graph.entry_point
        if not entry:
            raise ValueError("Workflow has no entry point set.")

        log = logger.bind(workflow_id=self.graph.workflow_id)
        log.info("workflow_execute_start", entry=entry)

        start_time = time.monotonic()
        visited_counts: dict[str, int] = {}
        queue = [entry]
        step = 0

        while queue and step < self.max_steps:
            # Execute nodes in queue (supports parallel branches)
            if len(queue) > 1:
                results = await asyncio.gather(
                    *[self._run_node(node_id, state) for node_id in queue],
                    return_exceptions=True,
                )
                # Merge results back into state (last-write-wins for simple fields)
                for result in results:
                    if isinstance(result, WorkflowState):
                        state = result
                    elif isinstance(result, Exception):
                        state.errors.append(str(result))
            else:
                state = await self._run_node(queue[0], state)

            if state.is_complete:
                break

            if state.context.get("awaiting_human_input"):
                log.info("workflow_paused_human_input")
                break

            # Checkpoint callback for persistence
            if checkpoint_callback:
                await checkpoint_callback(state)

            # Collect next nodes
            next_queue = []
            for node_id in queue:
                visited_counts[node_id] = visited_counts.get(node_id, 0) + 1
                if visited_counts[node_id] > 10:
                    state.errors.append(f"Cycle detected at node {node_id}, aborting.")
                    state.is_complete = True
                    break

                next_nodes = self.graph._get_next_nodes(node_id, state)
                next_queue.extend(next_nodes)

            queue = list(dict.fromkeys(next_queue))  # deduplicate preserving order
            step += 1

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        log.info("workflow_execute_done", steps=step, elapsed_ms=elapsed_ms, errors=len(state.errors))
        return state

    async def _run_node(self, node_id: str, state: WorkflowState) -> WorkflowState:
        node = self.graph.nodes.get(node_id)
        if not node:
            state.errors.append(f"Node '{node_id}' not found in graph.")
            return state
        return await node(state)


class WorkflowBuilder:
    """
    Constructs a WorkflowGraph from the JSON graph_definition stored in the database.
    """

    @classmethod
    async def build(
        cls,
        workflow_db,
        tool_registry,
        agent_registry,
    ) -> WorkflowGraph:
        from app.core.workflow.nodes import (
            StartNode, EndNode, AgentNode, ToolNode, ConditionNode, HumanNode,
            LLMNode, HttpNode, CodeNode, NoteNode, TriggerNode, SwitchNode,
            SetNode, MergeNode, SplitNode, FilterNode, WaitNode, TransformNode,
            IntegrationNode, SubWorkflowNode, RespondWebhookNode, StopErrorNode,
        )
        from app.core.workflow.node_catalog import get_node_definition, catalog_type_to_exec_type
        from app.core.agents.executor import AgentExecutor

        TYPE_MAP = {
            "startnode": "start", "endnode": "end", "agentnode": "agent",
            "toolnode": "tool", "conditionnode": "condition", "humannode": "human",
            "llmnode": "llm", "httpnode": "http", "codenode": "code", "notenode": "note",
            "triggernode": "trigger", "switchnode": "switch", "setnode": "set",
            "mergenode": "merge", "splitnode": "split", "filternode": "filter",
            "waitnode": "wait", "transformnode": "transform", "integrationnode": "integration",
            "subworkflownode": "subworkflow", "respondwebhooknode": "respond_webhook",
            "stoperrornode": "stop_error", "if": "condition", "httprequest": "http",
            "llmchain": "llm", "aiagent": "agent", "humansintheloop": "human",
            "executeworkflow": "subworkflow", "toolcall": "tool", "stickynote": "note",
            "noop": "note", "manualtrigger": "trigger", "webhooktrigger": "trigger",
            "crontrigger": "trigger", "scheduletrigger": "trigger", "emailtrigger": "trigger",
            "chattrigger": "trigger",
        }

        def _normalize_type(raw: str, catalog_id: str | None = None) -> str:
            if catalog_id:
                exec_type = catalog_type_to_exec_type(catalog_id)
                if exec_type:
                    return exec_type
            key = (raw or "").lower().replace("_", "").replace("-", "")
            return TYPE_MAP.get(key, raw.lower().removesuffix("node") if raw.endswith("Node") else raw.lower())

        def _resolve_agent(config: dict):
            for key in ("agent_id", "role", "name"):
                val = config.get(key)
                if val and val in agent_registry:
                    return agent_registry[val]
            return None

        graph_def = workflow_db.graph_definition or {}
        nodes_def = graph_def.get("nodes", [])
        edges_def = graph_def.get("edges", [])

        graph = WorkflowGraph(workflow_id=str(workflow_db.id))

        for node_def in nodes_def:
            nid = node_def.get("id")
            if not nid:
                continue
            catalog_id = node_def.get("catalog_id") or node_def.get("config", {}).get("_catalog_id")
            ntype = _normalize_type(node_def.get("type", ""), catalog_id)
            config = dict(node_def.get("config", {}))
            if catalog_id:
                config["_catalog_id"] = catalog_id
                defn = get_node_definition(catalog_id)
                if defn and defn.get("integration"):
                    config["_integration"] = defn["integration"]

            if ntype == "start":
                node = StartNode(nid, config)
                graph.set_entry_point(nid)
            elif ntype == "end":
                node = EndNode(nid, config)
            elif ntype == "agent":
                agent_def = _resolve_agent(config)
                tool_names = [t.get("tool_name") for t in config.get("tools", []) if isinstance(t, dict)]
                tool_names += [t for t in config.get("tools", []) if isinstance(t, str)]
                tools = [tool_registry.get(t) for t in tool_names if tool_registry.get(t)]
                executor = AgentExecutor(definition=agent_def, tools=tools) if agent_def else None
                node = AgentNode(nid, config, agent_executor=executor)
            elif ntype == "tool":
                tool = tool_registry.get(config.get("tool_name"))
                node = ToolNode(nid, config, tool=tool)
            elif ntype == "condition":
                node = ConditionNode(nid, config)
            elif ntype == "human":
                node = HumanNode(nid, config)
            elif ntype == "llm":
                node = LLMNode(nid, config)
            elif ntype == "http":
                node = HttpNode(nid, config)
            elif ntype == "code":
                node = CodeNode(nid, config)
            elif ntype == "note":
                node = NoteNode(nid, config)
            elif ntype == "trigger":
                node = TriggerNode(nid, config)
            elif ntype == "switch":
                node = SwitchNode(nid, config)
            elif ntype == "set":
                node = SetNode(nid, config)
            elif ntype == "merge":
                node = MergeNode(nid, config)
            elif ntype == "split":
                node = SplitNode(nid, config)
            elif ntype == "filter":
                node = FilterNode(nid, config)
            elif ntype == "wait":
                node = WaitNode(nid, config)
            elif ntype == "transform":
                node = TransformNode(nid, config)
            elif ntype == "integration":
                node = IntegrationNode(nid, config)
            elif ntype == "subworkflow":
                node = SubWorkflowNode(nid, config)
            elif ntype == "respond_webhook":
                node = RespondWebhookNode(nid, config)
            elif ntype == "stop_error":
                node = StopErrorNode(nid, config)
            else:
                logger.warning("unknown_workflow_node_type", node_id=nid, type=node_def.get("type"))
                continue

            graph.add_node(node)

        for edge_def in edges_def:
            source = edge_def.get("source")
            target = edge_def.get("target")
            if not source or not target:
                continue
            route_key = edge_def.get("label") or edge_def.get("condition")

            if route_key:
                existing = graph.conditional_edges.get(source, {})
                existing[route_key] = target
                graph.conditional_edges[source] = existing
            else:
                graph.add_edge(source, target)

        return graph
