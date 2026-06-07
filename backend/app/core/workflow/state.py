"""
LangGraph-inspired workflow state definitions.
"""
from typing import Any, Optional, Annotated
from dataclasses import dataclass, field
import operator


@dataclass
class WorkflowState:
    """
    Shared state that flows through all nodes in a workflow graph.
    Using Annotated with operator.add for messages allows LangGraph
    to automatically append rather than overwrite.
    """
    input: str = ""
    messages: Annotated[list[dict], operator.add] = field(default_factory=list)
    current_node: str = "start"
    agent_outputs: dict[str, str] = field(default_factory=dict)
    tool_results: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    errors: Annotated[list[str], operator.add] = field(default_factory=list)
    is_complete: bool = False
    final_output: Optional[str] = None
    iteration_count: int = 0
    token_usage: dict[str, int] = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})

    def add_message(self, role: str, content: str, node: Optional[str] = None) -> None:
        self.messages.append({
            "role": role,
            "content": content,
            "node": node or self.current_node,
        })

    def merge_token_usage(self, usage: dict[str, int]) -> None:
        self.token_usage["input_tokens"] += usage.get("input_tokens", 0)
        self.token_usage["output_tokens"] += usage.get("output_tokens", 0)
