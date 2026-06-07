"""
LLM-powered workflow node configuration assistant.
Generates or refines node config based on natural language descriptions.
"""
from __future__ import annotations

import json
import re
from typing import Any

import structlog

from app.core.workflow.node_catalog import get_node_definition
from app.models_hub.router import ModelRouter

logger = structlog.get_logger(__name__)


def _default_config(defn: dict[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for prop in defn.get("properties", []):
        name = prop["name"]
        if prop.get("default") is not None:
            config[name] = prop["default"]
        elif prop.get("required"):
            config[name] = ""
    return config


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


class NodeConfigAssistant:
    @classmethod
    async def suggest_config(
        cls,
        node_id: str,
        user_prompt: str,
        current_config: dict[str, Any] | None = None,
        workflow_context: dict[str, Any] | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        defn = get_node_definition(node_id)
        if not defn:
            raise ValueError(f"Unknown node type: {node_id}")

        from app.core.workflow.node_catalog import catalog_text
        node_name = catalog_text(defn.get("name", node_id), "en")

        current = current_config or _default_config(defn)
        properties_desc = []
        for prop in defn.get("properties", []):
            display = catalog_text(prop.get("displayName", prop.get("name", "")), "en")
            line = f"- {prop['name']} ({prop['type']}) — {display}"
            if prop.get("required"):
                line += " [required]"
            if prop.get("description"):
                line += f": {prop['description']}"
            if prop.get("options"):
                opts = ", ".join(o["value"] for o in prop["options"][:8])
                line += f" options=[{opts}]"
            if prop.get("default") is not None:
                line += f" default={json.dumps(prop['default'], ensure_ascii=False)}"
            properties_desc.append(line)

        context_block = ""
        if workflow_context:
            context_block = f"\nWorkflow context:\n{json.dumps(workflow_context, ensure_ascii=False, indent=2)[:2000]}"

        system = (
            "You are an expert n8n workflow automation engineer. "
            "Generate precise node configuration JSON based on user requirements. "
            "Use n8n expression syntax where helpful: {{ $json.field }}, {{ $input }}, {{ $node[\"NodeName\"].json }}. "
            "Return ONLY valid JSON object matching the property names exactly. No markdown explanation."
        )

        user_message = f"""Node: {node_name} ({node_id})
Category: {defn['category']}
Description: {catalog_text(defn.get('description', ''), 'en')}
Execution type: {defn['type']}

Available properties:
{chr(10).join(properties_desc) or '(no properties)'}

Current config:
{json.dumps(current, ensure_ascii=False, indent=2)}
{context_block}

User request:
{user_prompt}

Return the complete updated config JSON object."""

        llm = await ModelRouter.get_llm(provider=provider, model=model, temperature=0.2)
        response = await llm.ainvoke([
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ])
        content = response.content if hasattr(response, "content") else str(response)
        suggested = _extract_json(content)

        if not suggested:
            logger.warning("node_config_assist_parse_failed", node_id=node_id)
            return {"config": current, "explanation": content, "parsed": False}

        merged = {**current, **suggested}
        logger.info("node_config_assisted", node_id=node_id, keys=list(merged.keys()))
        return {
            "config": merged,
            "explanation": content if len(content) < 500 else content[:500] + "...",
            "parsed": True,
            "node": {"id": node_id, "name": node_name, "type": defn["type"]},
        }
