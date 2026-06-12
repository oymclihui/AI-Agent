from fastapi import APIRouter
from app.core.tools.registry import ToolRegistry
from app.core.harness.policy import ToolPolicy

router = APIRouter(prefix="/tools", tags=["Tools"])


@router.get("/")
async def list_tools():
    """Returns all registered tools with name, description, and harness risk level."""
    registry = ToolRegistry.get_instance()
    tools = registry.list_tools()
    for t in tools:
        t["risk_level"] = ToolPolicy.risk_for(t["name"]).value
    return tools
