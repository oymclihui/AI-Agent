from fastapi import APIRouter
from app.core.tools.registry import ToolRegistry

router = APIRouter(prefix="/tools", tags=["Tools"])


@router.get("/")
async def list_tools():
    """Returns all registered tools with name and description."""
    registry = ToolRegistry.get_instance()
    return registry.list_tools()
