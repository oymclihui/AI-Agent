"""
Generate workflow definitions from natural language using LLM.
"""
from __future__ import annotations

import json
import re
from typing import Any

import structlog

from app.core.workflow.node_catalog import _catalog_by_id, catalog_type_to_exec_type
from app.models_hub.router import ModelRouter

logger = structlog.get_logger(__name__)

LEGACY_TYPE_TO_CATALOG = {
    "startnode": "start", "endnode": "end", "agentnode": "aiAgent",
    "llmnode": "llmChain", "toolnode": "toolCall", "conditionnode": "if",
    "humannode": "humanInTheLoop", "httpnode": "httpRequest", "codenode": "code",
    "agent": "aiAgent", "llm": "llmChain", "tool": "toolCall", "condition": "if",
    "human": "humanInTheLoop", "http": "httpRequest", "code": "code",
}


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


def _catalog_hints() -> str:
    by_cat: dict[str, list[str]] = {}
    for n in _catalog_by_id().values():
        by_cat.setdefault(n.get("category", "app"), []).append(n["id"])
    lines = []
    limits = {"app": 25, "ai": 30, "trigger": 20, "core": 30, "data": 15, "flow": 10, "control": 5, "tools": 5}
    for cat in ("control", "trigger", "core", "flow", "ai", "data", "tools", "app"):
        ids = by_cat.get(cat, [])
        if not ids:
            continue
        sample = ids[: limits.get(cat, 20)]
        lines.append(f"- {cat}: {', '.join(sample)}")
    return "\n".join(lines)


def _resolve_catalog_id(raw_id: str, raw_type: str) -> str:
    catalog = _catalog_by_id()
    for candidate in (raw_id, raw_type):
        if not candidate:
            continue
        if candidate in catalog:
            return candidate
        key = candidate.lower().replace("_", "").replace("-", "")
        mapped = LEGACY_TYPE_TO_CATALOG.get(key)
        if mapped and mapped in catalog:
            return mapped
        if key.endswith("node"):
            mapped2 = LEGACY_TYPE_TO_CATALOG.get(key)
            if mapped2 and mapped2 in catalog:
                return mapped2
    for candidate in (raw_id, raw_type):
        if candidate:
            hit = next((cid for cid, n in catalog.items() if n.get("type") == candidate), None)
            if hit:
                return hit
    return raw_id or raw_type or "llmChain"


def _normalize_graph(graph: dict[str, Any]) -> dict[str, Any]:
    nodes_in = graph.get("nodes") or []
    edges_in = graph.get("edges") or []
    catalog = _catalog_by_id()

    nodes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for i, raw in enumerate(nodes_in):
        if not isinstance(raw, dict):
            continue
        nid = str(raw.get("id") or f"node_{i}")
        if nid in seen_ids:
            nid = f"{nid}_{i}"
        seen_ids.add(nid)

        catalog_id = _resolve_catalog_id(
            str(raw.get("catalog_id") or raw.get("catalogId") or ""),
            str(raw.get("type") or ""),
        )
        if catalog_id not in catalog:
            catalog_id = "llmChain" if catalog_id not in catalog else catalog_id

        defn = catalog.get(catalog_id, {})
        exec_type = defn.get("type", catalog_type_to_exec_type(catalog_id))
        pos = raw.get("position") or {}
        nodes.append({
            "id": nid,
            "type": exec_type,
            "catalog_id": catalog_id,
            "label": str(raw.get("label") or defn.get("name", catalog_id)),
            "config": raw.get("config") if isinstance(raw.get("config"), dict) else {},
            "position": {
                "x": float(pos.get("x", 250)),
                "y": float(pos.get("y", 40 + len(nodes) * 120)),
            },
        })

    node_ids = {n["id"] for n in nodes}
    if "start" not in node_ids:
        nodes.insert(0, {
            "id": "start", "type": "start", "catalog_id": "start", "label": "Start",
            "config": {}, "position": {"x": 250, "y": 40},
        })
    if "end" not in node_ids:
        nodes.append({
            "id": "end", "type": "end", "catalog_id": "end", "label": "End",
            "config": {}, "position": {"x": 250, "y": 40 + len(nodes) * 120},
        })

    node_ids = {n["id"] for n in nodes}
    edges: list[dict[str, Any]] = []
    for i, raw in enumerate(edges_in):
        if not isinstance(raw, dict):
            continue
        src, tgt = raw.get("source"), raw.get("target")
        if not src or not tgt or src not in node_ids or tgt not in node_ids:
            continue
        edge: dict[str, Any] = {
            "id": str(raw.get("id") or f"{src}->{tgt}_{i}"),
            "source": src,
            "target": tgt,
        }
        if raw.get("label"):
            edge["label"] = raw["label"]
        if raw.get("sourceHandle"):
            edge["sourceHandle"] = raw["sourceHandle"]
        edges.append(edge)

    if not edges and len(nodes) >= 2:
        for a, b in zip(nodes[:-1], nodes[1:]):
            edges.append({"id": f"{a['id']}->{b['id']}", "source": a["id"], "target": b["id"]})

    return {"nodes": nodes, "edges": edges}


class WorkflowGenerator:
    @classmethod
    async def generate_from_description(
        cls,
        description: str,
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        hints = _catalog_hints()
        system = (
            "You are an expert n8n workflow architect. Design automation workflows as JSON. "
            "Use n8n-style catalog_id for each node. Always include start and end nodes. "
            "Respond with JSON only, no markdown."
        )
        user = f"""Design a workflow for this requirement:
{description}

Available node catalog_id samples (pick appropriate ones):
{hints}

Output JSON schema:
{{
  "name": "workflow name",
  "description": "short description",
  "process_type": "sequential|hierarchical|parallel",
  "graph_definition": {{
    "nodes": [
      {{
        "id": "unique_id",
        "catalog_id": "start|httpRequest|llmChain|if|slack|...",
        "label": "display label",
        "config": {{}},
        "position": {{"x": 250, "y": 120}}
      }}
    ],
    "edges": [
      {{"source": "start", "target": "next_id", "label": "optional for IF branches"}}
    ]
  }}
}}

Rules:
- First node should connect from start; last should connect to end
- Use catalog_id values from the list above
- For IF/switch nodes, use edge label true/false or branch names
- Put meaningful config in nodes (prompt, url, tool_name, expression, etc.)
"""

        llm = await ModelRouter.get_llm(provider=provider, model=model, temperature=0.3)
        response = await llm.ainvoke([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        content = response.content if hasattr(response, "content") else str(response)
        spec = _extract_json(content)
        if not spec:
            raise ValueError("LLM did not return valid workflow JSON")

        graph = _normalize_graph(spec.get("graph_definition") or spec.get("graph") or {})
        process_type = spec.get("process_type", "sequential")
        if process_type not in ("sequential", "hierarchical", "parallel"):
            process_type = "sequential"

        result = {
            "name": str(spec.get("name") or "AI 生成工作流")[:255],
            "description": str(spec.get("description") or description)[:2000],
            "process_type": process_type,
            "graph_definition": graph,
        }
        logger.info(
            "workflow_generated",
            name=result["name"],
            nodes=len(graph.get("nodes", [])),
            edges=len(graph.get("edges", [])),
        )
        return result
