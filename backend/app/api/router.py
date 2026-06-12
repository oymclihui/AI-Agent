from fastapi import APIRouter
from app.api import agents, workflows, chat, knowledge, models, tools, orchestrator, skills, employees, dashboard, artifacts, auth, desktop_automation, harness, organization

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)

api_router.include_router(organization.router)

api_router.include_router(agents.router)
api_router.include_router(workflows.router)
api_router.include_router(chat.router)
api_router.include_router(knowledge.router)
api_router.include_router(models.router)
api_router.include_router(tools.router)
api_router.include_router(orchestrator.router)
api_router.include_router(skills.router)
api_router.include_router(employees.router)
api_router.include_router(dashboard.router)
api_router.include_router(artifacts.router)
api_router.include_router(desktop_automation.router)
api_router.include_router(harness.router)
