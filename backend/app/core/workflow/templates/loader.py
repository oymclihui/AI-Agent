"""Load and upsert bundled workflow templates."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import generate_uuid
from app.db.models import ProcessType, Workflow, WorkflowStatus

logger = structlog.get_logger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent


def list_templates() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not TEMPLATES_DIR.exists():
        return items
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append({
                "template_id": data.get("template_id", path.stem),
                "name_zh": data.get("name_zh", ""),
                "name_en": data.get("name_en", ""),
                "description_zh": data.get("description_zh", ""),
                "description_en": data.get("description_en", ""),
            })
        except Exception as exc:
            logger.warning("workflow_template_load_failed", path=str(path), error=str(exc))
    return items


def get_template(template_id: str) -> dict[str, Any]:
    path = TEMPLATES_DIR / f"{template_id}.json"
    if not path.exists():
        raise ValueError(f"Workflow template not found: {template_id}")
    return json.loads(path.read_text(encoding="utf-8"))


async def ensure_workflow_templates(session: AsyncSession) -> int:
    """Upsert bundled workflow templates by template_id in metadata."""
    if not TEMPLATES_DIR.exists():
        return 0

    created = 0
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("workflow_template_skip", path=str(path), error=str(exc))
            continue

        template_id = str(data.get("template_id") or path.stem)
        name = str(data.get("name_zh") or data.get("name") or template_id)
        graph = data.get("graph") or {}
        if not graph.get("nodes"):
            logger.warning("workflow_template_empty_graph", template_id=template_id)
            continue

        result = await session.execute(select(Workflow))
        existing = None
        for wf in result.scalars().all():
            meta = wf.metadata_ or {}
            if meta.get("template_id") == template_id:
                existing = wf
                break

        description = data.get("description_zh") or data.get("description") or ""
        process_type = str(data.get("process_type") or "sequential")

        if existing:
            existing.name = name
            existing.description = description
            existing.process_type = ProcessType(process_type)
            existing.graph_definition = graph
            existing.status = WorkflowStatus.active
            existing.metadata_ = {
                **(existing.metadata_ or {}),
                "template_id": template_id,
                "input_schema": data.get("input_schema"),
                "input_example": data.get("input_example"),
            }
            continue

        session.add(Workflow(
            id=generate_uuid(),
            name=name,
            description=description,
            status=WorkflowStatus.active,
            process_type=ProcessType(process_type),
            graph_definition=graph,
            agents_config=[],
            triggers_config=[],
            metadata_={
                "template_id": template_id,
                "input_schema": data.get("input_schema"),
                "input_example": data.get("input_example"),
            },
        ))
        created += 1

    await session.commit()
    return created
