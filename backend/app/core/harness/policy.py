from __future__ import annotations

from enum import Enum

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


class ToolRiskLevel(str, Enum):
    L0_READ = "L0"       # read-only, no gate
    L1_PLATFORM = "L1"   # writes platform data, audit only
    L2_EXTERNAL = "L2"   # external side-effects, harness confirm
    L3_CRITICAL = "L3"   # always confirm


# Tools that implement their own confirmation (e.g. desktop_replay → awaiting_confirmation)
_SELF_GATED_TOOLS = frozenset({"desktop_replay", "desktop_capture"})

TOOL_RISK: dict[str, ToolRiskLevel] = {
    "calculator": ToolRiskLevel.L0_READ,
    "get_datetime": ToolRiskLevel.L0_READ,
    "web_search": ToolRiskLevel.L0_READ,
    "desktop_list_demos": ToolRiskLevel.L0_READ,
    "create_presentation": ToolRiskLevel.L1_PLATFORM,
    "batch_parse_excel": ToolRiskLevel.L1_PLATFORM,
    "http_request": ToolRiskLevel.L2_EXTERNAL,
    "fetch_mail": ToolRiskLevel.L2_EXTERNAL,
    "desktop_replay": ToolRiskLevel.L2_EXTERNAL,
    "desktop_capture": ToolRiskLevel.L2_EXTERNAL,
}

# Declared scope for tools that touch the network, the desktop, or user files.
TOOL_SANDBOX: dict[str, str] = {
    "calculator": "read-only",
    "get_datetime": "read-only",
    "web_search": "read-only",
    "desktop_list_demos": "read-only",
    "create_presentation": "platform-files",
    "batch_parse_excel": "excel-frames-only",
    "http_request": "outbound-http-confirm",
    "fetch_mail": "mailbox-confirm",
    "desktop_replay": "desktop-confirm",
    "desktop_capture": "desktop-confirm",
}


class ToolPolicy:
    @staticmethod
    def risk_for(tool_name: str) -> ToolRiskLevel:
        # Unknown tools are external until someone classifies them.
        return TOOL_RISK.get(tool_name, ToolRiskLevel.L2_EXTERNAL)

    @staticmethod
    def sandbox_for(tool_name: str) -> str:
        return TOOL_SANDBOX.get(tool_name, "confirm-unknown")

    @staticmethod
    def requires_harness_confirmation(tool_name: str, *, auto_confirm: bool = False) -> bool:
        if auto_confirm:
            return False
        if not settings.HARNESS_REQUIRE_TOOL_CONFIRMATION:
            return False
        if tool_name in _SELF_GATED_TOOLS:
            return False
        level = ToolPolicy.risk_for(tool_name)
        return level in (ToolRiskLevel.L2_EXTERNAL, ToolRiskLevel.L3_CRITICAL)

    @staticmethod
    def list_tools_with_risk() -> list[dict[str, str]]:
        names = sorted(set(TOOL_RISK) | set(TOOL_SANDBOX))
        return [
            {
                "name": name,
                "risk_level": ToolPolicy.risk_for(name).value,
                "sandbox": ToolPolicy.sandbox_for(name),
            }
            for name in names
        ]
