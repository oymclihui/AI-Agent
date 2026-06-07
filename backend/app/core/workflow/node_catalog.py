"""
n8n-style workflow node catalog — loaded from generated n8n_nodes_raw.json.
Regenerate: python scripts/generate_n8n_catalog.py
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_CATALOG_PATH = Path(__file__).parent / "n8n_nodes_raw.json"


def _load_raw_catalog() -> dict[str, Any]:
    if not _CATALOG_PATH.exists():
        return {"nodes": _fallback_nodes(), "categories": _fallback_categories(), "total": 0}
    with _CATALOG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _fallback_categories() -> list[dict[str, Any]]:
    return [
        {"id": "control", "name": "Control", "color": "#64748b"},
        {"id": "trigger", "name": "Triggers", "color": "#22c55e"},
        {"id": "core", "name": "Core", "color": "#3b82f6"},
        {"id": "app", "name": "Apps & Integrations", "color": "#ec4899"},
    ]


def _fallback_nodes() -> list[dict[str, Any]]:
    return [
        {"id": "start", "type": "start", "category": "control", "name": "Start",
         "description": "Workflow entry point", "icon": "play-circle", "color": "#22c55e",
         "properties": [], "outputs": ["main"]},
        {"id": "end", "type": "end", "category": "control", "name": "End",
         "description": "Workflow exit point", "icon": "stop-circle", "color": "#ef4444",
         "properties": [], "outputs": ["main"]},
    ]


def _text_pair(en: str, zh: str) -> dict[str, str]:
    return {"en": en, "zh": zh}


def _auto_name_zh(en: str, node_id: str, category: str) -> str:
    from app.core.workflow.node_catalog_i18n import NODE_ZH

    if node_id in NODE_ZH and NODE_ZH[node_id].get("name"):
        return NODE_ZH[node_id]["name"]
    if category == "trigger" and en.endswith("Trigger"):
        return en.replace("Trigger", "触发器").replace(" Trigger", "触发器")
    if category == "app":
        return f"{en} 集成" if not en.endswith("集成") else en
    return en


def _auto_desc_zh(en: str, node_id: str, category: str) -> str:
    from app.core.workflow.node_catalog_i18n import NODE_ZH

    if node_id in NODE_ZH and NODE_ZH[node_id].get("description"):
        return NODE_ZH[node_id]["description"]
    if category == "trigger":
        return f"触发器：{en}"
    if category == "ai":
        return f"AI 节点：{en}"
    if category == "core":
        return f"核心节点：{en}"
    if category == "app":
        return f"{en}（n8n 兼容集成）"
    return en


def _localize_property(prop: dict[str, Any]) -> dict[str, Any]:
    from app.core.workflow.node_catalog_i18n import PROPERTY_ZH, OPTION_ZH

    display_en = prop.get("displayName", prop.get("name", ""))
    if isinstance(display_en, dict):
        display_en = display_en.get("en", "")
    display_zh = PROPERTY_ZH.get(prop.get("name", ""), display_en)
    localized: dict[str, Any] = {
        **prop,
        "displayName": _text_pair(str(display_en), display_zh),
    }
    if prop.get("options"):
        localized["options"] = [
            {
                "name": _text_pair(o["name"], OPTION_ZH.get(o["name"], o["name"])),
                "value": o["value"],
            }
            for o in prop["options"]
        ]
    return localized


def _localize_node(node: dict[str, Any]) -> dict[str, Any]:
    name_en = node["name"] if isinstance(node["name"], str) else node["name"].get("en", "")
    desc_en = node["description"] if isinstance(node["description"], str) else node["description"].get("en", "")
    cat = node.get("category", "app")
    nid = node["id"]
    clean = {k: v for k, v in node.items() if not k.startswith("n8n_")}
    return {
        **clean,
        "name": _text_pair(name_en, _auto_name_zh(name_en, nid, cat)),
        "description": _text_pair(desc_en, _auto_desc_zh(desc_en, nid, cat)),
        "properties": [_localize_property(p) for p in node.get("properties", [])],
    }


def _localize_category(cat: dict[str, Any]) -> dict[str, Any]:
    from app.core.workflow.node_catalog_i18n import CATEGORY_ZH

    name_en = cat["name"]
    return {
        **cat,
        "name": _text_pair(name_en, CATEGORY_ZH.get(cat["id"], name_en)),
    }


@lru_cache(maxsize=1)
def _raw_catalog() -> dict[str, Any]:
    return _load_raw_catalog()


def _catalog_by_id() -> dict[str, dict[str, Any]]:
    return {n["id"]: n for n in _raw_catalog().get("nodes", [])}


def catalog_type_to_exec_type(catalog_id: str) -> str:
    defn = _catalog_by_id().get(catalog_id)
    return defn["type"] if defn else catalog_id


def get_node_catalog() -> dict[str, Any]:
    raw = _raw_catalog()
    nodes = [_localize_node(n) for n in raw.get("nodes", [])]
    return {
        "categories": [_localize_category(c) for c in raw.get("categories", _fallback_categories())],
        "nodes": nodes,
        "total": len(nodes),
    }


def get_node_definition(node_id: str) -> dict[str, Any] | None:
    raw = _catalog_by_id().get(node_id)
    return _localize_node(raw) if raw else None


def catalog_text(value: str | dict[str, str], lang: str = "en") -> str:
    if isinstance(value, dict):
        return value.get(lang) or value.get("en") or ""
    return str(value)
