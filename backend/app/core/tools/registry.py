"""
Tool Registry - central registry for all available tools (built-in + custom).
Inspired by LangChain's tool ecosystem.
"""
from typing import Optional
from langchain_core.tools import BaseTool
import structlog

logger = structlog.get_logger(__name__)


class ToolRegistry:
    """
    Singleton registry that holds all registered tools by name.
    Tools are loaded at startup and can be dynamically added.
    """
    _instance: Optional["ToolRegistry"] = None
    _tools: dict[str, BaseTool] = {}

    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._load_builtin_tools()
        return cls._instance

    def _load_builtin_tools(self) -> None:
        from app.core.tools.builtin.web_search import WebSearchTool
        from app.core.tools.builtin.calculator import CalculatorTool
        from app.core.tools.builtin.http_request import HttpRequestTool
        from app.core.tools.builtin.datetime_tool import DatetimeTool
        from app.core.tools.builtin.create_presentation import CreatePresentationTool
        from app.core.tools.builtin.fetch_mail import FetchMailTool
        from app.core.tools.builtin.desktop_automation import (
            DesktopListDemosTool,
            DesktopReplayTool,
            DesktopCaptureTool,
        )

        builtins = [
            WebSearchTool,
            CalculatorTool,
            HttpRequestTool,
            DatetimeTool,
            CreatePresentationTool,
            FetchMailTool,
            DesktopListDemosTool,
            DesktopReplayTool,
            DesktopCaptureTool,
        ]
        for tool in builtins:
            self.register(tool)
        logger.info("builtin_tools_loaded", count=len(builtins))

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        logger.debug("tool_registered", name=tool.name)

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        return [
            {"name": t.name, "description": t.description}
            for t in self._tools.values()
        ]

    def get_tools_for_agent(self, tool_names: list[str]) -> list[BaseTool]:
        tools = []
        for name in tool_names:
            tool = self.get(name)
            if tool:
                tools.append(tool)
            else:
                logger.warning("tool_not_found", name=name)
        return tools
