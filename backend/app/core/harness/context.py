from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HarnessContext:
    user_id: str
    source: str = "agent"  # chat | agent | workflow | employee
    source_id: str | None = None
    auto_confirm: bool = False
    trace: list[dict[str, Any]] = field(default_factory=list)

    def append_trace(self, event: dict[str, Any]) -> None:
        self.trace.append(event)


_harness_ctx: ContextVar[HarnessContext | None] = ContextVar("harness_ctx", default=None)


def get_harness_context() -> HarnessContext | None:
    return _harness_ctx.get()


def set_harness_context(ctx: HarnessContext) -> Token:
    return _harness_ctx.set(ctx)


def reset_harness_context(token: Token) -> None:
    _harness_ctx.reset(token)
