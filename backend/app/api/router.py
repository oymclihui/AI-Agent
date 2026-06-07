from fastapi import APIRouter
from app.api import agents, workflows, chat, knowledge, models, tools, orchestrator, skills, employees

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(agents.router)
api_router.include_router(workflows.router)
api_router.include_router(chat.router)
api_router.include_router(knowledge.router)
api_router.include_router(models.router)
api_router.include_router(tools.router)
api_router.include_router(orchestrator.router)
api_router.include_router(skills.router)
api_router.include_router(employees.router)
