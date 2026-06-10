#!/usr/bin/env python3
"""Diagnose employee task LLM connectivity."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from sqlalchemy import select

from app.config import settings
from app.db.models import Agent, DigitalEmployee, EmployeeScheduledTask, ModelConfig
from app.db.session import AsyncSessionLocal


async def main() -> None:
    print("OLLAMA_BASE_URL (settings):", settings.OLLAMA_BASE_URL)
    print("DEFAULT_LLM:", settings.DEFAULT_LLM_PROVIDER, settings.DEFAULT_LLM_MODEL)

    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
            print("Ollama reachable:", r.status_code == 200, "at", settings.OLLAMA_BASE_URL)
    except Exception as exc:
        print("Ollama NOT reachable at", settings.OLLAMA_BASE_URL, "->", exc)

    async with AsyncSessionLocal() as db:
        mc = await db.execute(select(ModelConfig).where(ModelConfig.is_active == True))
        configs = mc.scalars().all()
        print("\nActive ModelConfig rows:", len(configs))
        for c in configs[:5]:
            print(f"  - {c.provider}/{c.model_id} default={c.is_default} base_url={c.base_url or '(env)'}")

        task_row = await db.execute(
            select(EmployeeScheduledTask).where(EmployeeScheduledTask.name == "每日内容包").limit(1)
        )
        task = task_row.scalar_one_or_none()
        if not task:
            print("\nNo task named 每日内容包 found")
            return
        emp = await db.get(DigitalEmployee, task.employee_id)
        agent = await db.get(Agent, emp.agent_id) if emp else None
        print(f"\nTask: {task.name} employee={emp.name if emp else '?'}")
        if agent:
            print(f"Agent LLM: {agent.llm_provider}/{agent.llm_model}")


if __name__ == "__main__":
    asyncio.run(main())
