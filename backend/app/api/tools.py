from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from app.core.tools.registry import ToolRegistry
from app.core.harness.policy import ToolPolicy

router = APIRouter(prefix="/tools", tags=["Tools"])


@router.get("/")
async def list_tools(category: str | None = Query(None, description="analysis=分析算子目录")):
    """Returns all registered tools with name, description, and harness risk level.

    category=analysis 时返回 8 个内置分析算子的名称、用途和参数说明（只读目录）。
    """
    if category == "analysis":
        from app.core.data_ask.analysis.operators import OPERATORS

        builtin = [
            {
                "name": spec.name,
                "display_name": spec.display_name,
                "description": spec.description,
                "category": "analysis",
                "parameters_schema": spec.parameters_schema,
                "implementation_type": "builtin",
            }
            for spec in OPERATORS.values()
        ]
        from app.core.data_ask.blueprint_finish import list_http_operators
        from app.db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            http_tools = await list_http_operators(session)
        return builtin + http_tools
    registry = ToolRegistry.get_instance()
    tools = registry.list_tools()
    for t in tools:
        t["risk_level"] = ToolPolicy.risk_for(t["name"]).value
    return tools


class HttpOperatorIn(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    description: str = ""
    url: str
    method: str = "POST"


@router.post("/http-operators")
async def create_http_operator(
    payload: HttpOperatorIn,
    db=Depends(__import__("app.db.session", fromlist=["get_db"]).get_db),
    user=Depends(__import__("app.core.auth.deps", fromlist=["get_current_user"]).get_current_user),
):
    """把一个 HTTP 接口登记为分析算子。管理员可用，拒绝回环地址。"""
    from app.core.auth.scoping import assert_admin_user
    from app.core.data_ask.blueprint_finish import register_http_operator
    assert_admin_user(user)
    try:
        created = await register_http_operator(
            db, name=payload.name, description=payload.description, url=payload.url, method=payload.method,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:300]) from exc
    await db.commit()
    return created
