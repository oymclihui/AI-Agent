"""Seed bundled workflow templates."""
import asyncio

from app.core.workflow.templates.loader import ensure_workflow_templates
from app.db.session import AsyncSessionLocal


async def main() -> None:
    async with AsyncSessionLocal() as session:
        created = await ensure_workflow_templates(session)
        print(f"bundled_workflows_created={created}")


if __name__ == "__main__":
    asyncio.run(main())
