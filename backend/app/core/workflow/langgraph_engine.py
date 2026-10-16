"""
LangGraphWorkflowEngine - replaces custom WorkflowEngine with LangGraph StateGraph.

Converts a WorkflowGraph (defined by WorkflowBuilder) into a LangGraph StateGraph,
enabling native parallel branches, conditional routing, and checkpointing via
the PostgresCheckpointer (lg4).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional, TypedDict

import structlog
from langgraph.graph import StateGraph, START, END

from app.core.workflow.state import WorkflowState
from app.core.workflow.nodes import BaseNode, ConditionNode, SwitchNode, EndNode

logger = structlog.get_logger(__name__)


class LGWorkflowState(TypedDict, total=False):
    """LangGraph state schema for workflow execution.

    All fields use replace semantics (no operator.add) to match the
    existing BaseNode return-entire-state pattern.
    """
    input: str
    messages: list[dict]
    current_node: str
    agent_outputs: dict[str, str]
    tool_results: dict[str, Any]
    context: dict[str, Any]
    errors: list[str]
    is_complete: bool
    final_output: Optional[str]
    iteration_count: int
    token_usage: dict[str, int]
    # Track which nodes have been visited (for cycle detection)
    _visited: dict[str, int]


def _ws_to_dict(ws: WorkflowState) -> dict:
    """Convert WorkflowState dataclass to dict for LangGraph."""
    return {
        "input": ws.input,
        "messages": list(ws.messages),
        "current_node": ws.current_node,
        "agent_outputs": dict(ws.agent_outputs),
        "tool_results": dict(ws.tool_results),
        "context": dict(ws.context),
        "errors": list(ws.errors),
        "is_complete": ws.is_complete,
        "final_output": ws.final_output,
        "iteration_count": ws.iteration_count,
        "token_usage": dict(ws.token_usage),
    }


def _dict_to_ws(state: dict) -> WorkflowState:
    """Convert dict state back to WorkflowState for BaseNode execution."""
    return WorkflowState(
        input=state.get("input", ""),
        messages=list(state.get("messages", [])),
        current_node=state.get("current_node", ""),
        agent_outputs=dict(state.get("agent_outputs", {})),
        tool_results=dict(state.get("tool_results", {})),
        context=dict(state.get("context", {})),
        errors=list(state.get("errors", [])),
        is_complete=state.get("is_complete", False),
        final_output=state.get("final_output"),
        iteration_count=state.get("iteration_count", 0),
        token_usage=dict(state.get("token_usage", {"input_tokens": 0, "output_tokens": 0})),
    )


class LangGraphWorkflowEngine:
    """Executes a WorkflowGraph using LangGraph StateGraph.

    Replaces the custom BFS-queue engine with LangGraph's native graph
    execution, supporting:
    - Conditional routing (ConditionNode, SwitchNode)
    - Parallel branches (fan-out via multiple edges)
    - Cycle detection (max visits per node)
    - Human-in-the-loop pause
    - PostgresCheckpointer for persistent state
    """

    MAX_NODE_VISITS = 10

    def __init__(self, graph, max_steps: int = 100):
        """Initialize with a WorkflowGraph.

        Args:
            graph: WorkflowGraph instance from WorkflowBuilder.build()
            max_steps: Maximum total steps (safety limit)
        """
        self.graph = graph
        self.max_steps = max_steps
        self._compiled = None
        self._visited: dict[str, int] = {}

    def _build_node_fn(self, node_id: str, base_node: BaseNode):
        """Create a LangGraph node function that wraps a BaseNode."""
        is_end = isinstance(base_node, EndNode)

        async def node_fn(state: LGWorkflowState) -> dict:
            # Cycle detection
            visited = dict(state.get("_visited", {}))
            visited[node_id] = visited.get(node_id, 0) + 1
            if visited[node_id] > self.MAX_NODE_VISITS:
                ws = _dict_to_ws(state)
                ws.errors.append(f"Cycle detected at node {node_id}, aborting.")
                ws.is_complete = True
                result = _ws_to_dict(ws)
                result["_visited"] = visited
                return result

            # Execute the BaseNode
            ws = _dict_to_ws(state)
            ws.current_node = node_id
            try:
                ws = await base_node(ws)
            except Exception as e:
                ws.errors.append(f"Node '{node_id}' error: {e}")
                if is_end:
                    ws.is_complete = True

            result = _ws_to_dict(ws)
            result["_visited"] = visited
            return result

        return node_fn

    def _build_router(self, base_node: BaseNode, routing_map: dict[str, str]):
        """Create a conditional edge router for ConditionNode/SwitchNode."""
        def router(state: LGWorkflowState) -> str:
            # Check if complete first
            if state.get("is_complete", False):
                return END
            # Evaluate condition
            ws = _dict_to_ws(state)
            key = base_node.evaluate(ws)
            next_id = routing_map.get(key, routing_map.get("default"))
            return next_id if next_id else END

        return router

    def _build_completion_router(self, next_nodes: list[str]):
        """Create a router that checks is_complete before proceeding."""
        def router(state: LGWorkflowState) -> str:
            if state.get("is_complete", False):
                return END
            # Check for human input pause
            ctx = state.get("context", {})
            if ctx.get("awaiting_human_input"):
                return END
            # Return first next node (LangGraph handles parallel via separate edges)
            if next_nodes:
                return next_nodes[0]
            return END

        return router

    def _compile(self):
        """Build and compile the LangGraph StateGraph from WorkflowGraph."""
        if self._compiled is not None:
            return self._compiled

        lg = StateGraph(LGWorkflowState)

        # Add all nodes
        for node_id, node in self.graph.nodes.items():
            lg.add_node(node_id, self._build_node_fn(node_id, node))

        # Set entry point
        entry = self.graph.entry_point
        if entry:
            lg.add_edge(START, entry)

        # Add regular edges (with completion check)
        for from_node, to_nodes in self.graph.edges.items():
            if from_node in self.graph.conditional_edges:
                continue  # Conditional edges handle routing for this node

            if len(to_nodes) == 1:
                # Single edge: add completion check
                next_id = to_nodes[0]
                lg.add_conditional_edges(
                    from_node,
                    self._build_completion_router([next_id]),
                    {next_id: next_id, END: END},
                )
            elif len(to_nodes) > 1:
                # Parallel branches: fan-out to all next nodes
                # LangGraph supports this natively via multiple edges
                for to_node in to_nodes:
                    lg.add_edge(from_node, to_node)

        # Add conditional edges
        for from_node, routing_map in self.graph.conditional_edges.items():
            node = self.graph.nodes.get(from_node)
            if isinstance(node, (ConditionNode, SwitchNode)):
                router = self._build_router(node, routing_map)
                # Build path map: route_key -> node_id, plus default -> END
                path_map = dict(routing_map)
                path_map.setdefault(END, END)
                lg.add_conditional_edges(from_node, router, path_map)
            else:
                # Non-condition node with conditional edges: use completion check
                for key, target in routing_map.items():
                    lg.add_edge(from_node, target)

        # Attach PostgresCheckpointer (from lg4)
        from app.core.agents.executor import get_postgres_checkpointer
        import asyncio
        checkpointer = asyncio.get_event_loop().run_until_complete(
            get_postgres_checkpointer()
        ) if asyncio.get_event_loop().is_running() else None

        # Note: In async context, we can't use run_until_complete.
        # The checkpointer will be set separately via set_checkpointer().
        self._compiled = lg.compile()
        return self._compiled

    async def _async_compile(self):
        """Async version of compile that properly initializes the checkpointer."""
        if self._compiled is not None:
            return self._compiled

        lg = StateGraph(LGWorkflowState)

        # Add all nodes
        for node_id, node in self.graph.nodes.items():
            lg.add_node(node_id, self._build_node_fn(node_id, node))

        # Set entry point
        entry = self.graph.entry_point
        if entry:
            lg.add_edge(START, entry)

        # Add regular edges (with completion check)
        for from_node, to_nodes in self.graph.edges.items():
            if from_node in self.graph.conditional_edges:
                continue

            if len(to_nodes) == 1:
                next_id = to_nodes[0]
                lg.add_conditional_edges(
                    from_node,
                    self._build_completion_router([next_id]),
                    {next_id: next_id, END: END},
                )
            elif len(to_nodes) > 1:
                for to_node in to_nodes:
                    lg.add_edge(from_node, to_node)

        # Add conditional edges
        for from_node, routing_map in self.graph.conditional_edges.items():
            node = self.graph.nodes.get(from_node)
            if isinstance(node, (ConditionNode, SwitchNode)):
                router = self._build_router(node, routing_map)
                path_map = dict(routing_map)
                path_map.setdefault(END, END)
                lg.add_conditional_edges(from_node, router, path_map)
            else:
                for key, target in routing_map.items():
                    lg.add_edge(from_node, target)

        # Attach PostgresCheckpointer
        from app.core.agents.executor import get_postgres_checkpointer
        checkpointer = await get_postgres_checkpointer()
        self._compiled = lg.compile(checkpointer=checkpointer)
        return self._compiled

    async def execute(
        self,
        input_data: dict[str, Any],
        checkpoint_callback=None,
    ) -> WorkflowState:
        """Execute the workflow using LangGraph StateGraph.

        Args:
            input_data: Input dict with 'input' key and context
            checkpoint_callback: Optional async callback (for compatibility)

        Returns:
            WorkflowState with final results
        """
        log = logger.bind(workflow_id=self.graph.workflow_id)
        log.info("lg_workflow_execute_start", entry=self.graph.entry_point)

        compiled = await self._async_compile()

        # Build initial state
        initial_state: LGWorkflowState = {
            "input": str(input_data.get("input", "")),
            "messages": [],
            "current_node": self.graph.entry_point or "start",
            "agent_outputs": {},
            "tool_results": {},
            "context": dict(input_data),
            "errors": [],
            "is_complete": False,
            "final_output": None,
            "iteration_count": 0,
            "token_usage": {"input_tokens": 0, "output_tokens": 0},
            "_visited": {},
        }

        # Config with recursion limit + thread_id for checkpoint
        config = {
            "recursion_limit": self.max_steps * 2 + 1,
            "configurable": {"thread_id": f"workflow-{self.graph.workflow_id}"},
        }

        start_time = time.monotonic()
        try:
            result = await compiled.ainvoke(initial_state, config=config)
        except Exception as e:
            log.error("lg_workflow_execute_error", error=str(e))
            ws = _dict_to_ws(initial_state)
            ws.errors.append(f"LangGraph execution error: {e}")
            ws.is_complete = True
            return ws

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        log.info(
            "lg_workflow_execute_done",
            elapsed_ms=elapsed_ms,
            errors=len(result.get("errors", [])),
            is_complete=result.get("is_complete", False),
        )

        # Convert back to WorkflowState for compatibility
        return _dict_to_ws(result)
