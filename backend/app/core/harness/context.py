from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class HarnessContext:
    user_id: str
    source: str = "agent"  # chat | agent | workflow | employee
    source_id: str | None = None
    auto_confirm: bool = False
    cancelled: bool = False
    working_directory: str | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)

    def append_trace(self, event: dict[str, Any]) -> None:
        if "at" not in event:
            event = {**event, "at": _now()}
        self.trace.append(event)

    def record(self, event: str, **payload: Any) -> None:
        self.append_trace({"event": event, **payload})

    def cancel(self, reason: str = "cancelled") -> None:
        """Stop this turn only. Does not change employee or desktop run rows."""
        if self.cancelled:
            return
        self.cancelled = True
        self.record("turn/cancel", reason=reason)

    def begin_turn(self, *, model: str | None = None) -> None:
        self.record(
            "turn/start",
            source=self.source,
            source_id=self.source_id,
            model=model,
            working_directory=self.working_directory,
        )

    def end_turn(self, *, status: str = "completed") -> None:
        if any(item.get("event") == "turn/end" for item in self.trace):
            return
        self.record("turn/end", status="cancelled" if self.cancelled else status)


def ensure_session_directory(source_id: str | None) -> str | None:
    """Per-session folder. Callers must not os.chdir; the process cwd stays put."""
    if not source_id:
        return None
    from app.config import settings

    root = Path(settings.LOCAL_UPLOADS_DIR) / "sessions" / source_id
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


_harness_ctx: ContextVar[HarnessContext | None] = ContextVar("harness_ctx", default=None)


def get_harness_context() -> HarnessContext | None:
    return _harness_ctx.get()


def set_harness_context(ctx: HarnessContext) -> Token:
    return _harness_ctx.set(ctx)


def reset_harness_context(token: Token) -> None:
    _harness_ctx.reset(token)
