from __future__ import annotations

from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)

BeforeToolHook = Callable[[str, dict[str, Any]], Awaitable[None]]
AfterToolHook = Callable[[str, dict[str, Any], str], Awaitable[None]]


class HarnessHooks:
    def __init__(self) -> None:
        self._before: list[BeforeToolHook] = []
        self._after: list[AfterToolHook] = []

    def before(self, hook: BeforeToolHook) -> None:
        self._before.append(hook)

    def after(self, hook: AfterToolHook) -> None:
        self._after.append(hook)

    async def run_before(self, tool_name: str, tool_args: dict[str, Any]) -> None:
        for hook in self._before:
            await hook(tool_name, tool_args)

    async def run_after(self, tool_name: str, tool_args: dict[str, Any], result: str) -> None:
        for hook in self._after:
            await hook(tool_name, tool_args, result)


def _preview(value: Any, limit: int = 500) -> str:
    text = str(value if value is not None else "")
    return text[:limit]


def audit_before_hook(ctx_getter) -> BeforeToolHook:
    async def _hook(tool_name: str, tool_args: dict[str, Any]) -> None:
        ctx = ctx_getter()
        if ctx:
            ctx.record(
                "tool/call",
                tool=tool_name,
                phase="pre-execute",
                arguments=_preview(tool_args),
            )
        logger.info("harness_tool_before", tool=tool_name, source=getattr(ctx, "source", None))

    return _hook


def audit_after_hook(ctx_getter) -> AfterToolHook:
    async def _hook(tool_name: str, tool_args: dict[str, Any], result: str) -> None:
        ctx = ctx_getter()
        if ctx:
            ctx.record(
                "tool/result",
                tool=tool_name,
                phase="post-execute",
                preview=_preview(result),
            )
        logger.info("harness_tool_after", tool=tool_name, result_len=len(result or ""))

    return _hook


_default_hooks: HarnessHooks | None = None


def get_default_hooks() -> HarnessHooks:
    global _default_hooks
    if _default_hooks is None:
        from app.core.harness.context import get_harness_context

        _default_hooks = HarnessHooks()
        _default_hooks.before(audit_before_hook(get_harness_context))
        _default_hooks.after(audit_after_hook(get_harness_context))
    return _default_hooks
