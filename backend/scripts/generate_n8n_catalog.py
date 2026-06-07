"""
Generate full n8n node catalog (all .node.ts definitions) from n8n-io/n8n.
Run: python scripts/generate_n8n_catalog.py
"""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

TREE_URL = "https://api.github.com/repos/n8n-io/n8n/git/trees/master?recursive=1"
NODE_PATH_PREFIXES = (
    "packages/nodes-base/nodes/",
    "packages/@n8n/nodes-langchain/nodes/",
)

CORE_NODE_MAP: dict[str, tuple[str, str, str]] = {
    "manualTrigger": ("manualTrigger", "trigger", "trigger"),
    "webhook": ("webhookTrigger", "trigger", "trigger"),
    "cron": ("cronTrigger", "trigger", "trigger"),
    "emailReadImap": ("emailTrigger", "trigger", "trigger"),
    "httpRequest": ("httpRequest", "http", "core"),
    "code": ("code", "code", "core"),
    "if": ("if", "condition", "core"),
    "switch": ("switch", "switch", "core"),
    "merge": ("merge", "merge", "core"),
    "splitInBatches": ("splitInBatches", "split", "core"),
    "splitOut": ("splitOut", "split", "core"),
    "set": ("set", "set", "core"),
    "filter": ("filter", "filter", "core"),
    "wait": ("wait", "wait", "core"),
    "noOp": ("noOp", "note", "core"),
    "stopAndError": ("stopAndError", "stop_error", "core"),
    "executeWorkflow": ("executeWorkflow", "subworkflow", "flow"),
    "respondToWebhook": ("respondToWebhook", "respond_webhook", "core"),
    "function": ("function", "code", "core"),
    "functionItem": ("functionItem", "code", "core"),
    "openAi": ("openAi", "llm", "ai"),
    "anthropic": ("anthropic", "llm", "ai"),
    "aiTransform": ("aiTransform", "llm", "ai"),
    "agent": ("aiAgent", "agent", "ai"),
}

ICON_BY_CATEGORY = {
    "trigger": "webhook", "core": "globe", "flow": "workflow", "ai": "brain",
    "data": "braces", "tools": "wrench", "app": "box", "control": "box",
}
COLOR_BY_CATEGORY = {
    "trigger": "#22c55e", "core": "#3b82f6", "flow": "#6366f1", "ai": "#8b5cf6",
    "data": "#06b6d4", "tools": "#f97316", "app": "#ec4899", "control": "#64748b",
}


def fetch_node_paths() -> list[str]:
    req = urllib.request.Request(TREE_URL, headers={"User-Agent": "AIAGNET-catalog-generator"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        tree = json.loads(resp.read())["tree"]
    return [
        item["path"] for item in tree
        if item["path"].endswith(".node.ts")
        and any(item["path"].startswith(p) for p in NODE_PATH_PREFIXES)
    ]


def pascal_to_words(name: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return s.strip()


def file_base_to_id(base: str) -> str:
    return base[0].lower() + base[1:] if base else base


def infer_node(base: str, folder: str, package: str) -> tuple[str, str, str, str, str]:
    nid = file_base_to_id(base)
    if nid in CORE_NODE_MAP:
        cid, et, cat = CORE_NODE_MAP[nid]
        display = pascal_to_words(base)
        return cid, et, cat, display, f"{display} (n8n core node)"

    display = pascal_to_words(base)
    if base.endswith("Trigger") or "trigger" in base.lower():
        return nid, "trigger", "trigger", display, f"Trigger: {display}"

    if package == "langchain" or base.startswith((
        "Lm", "Chain", "Tool", "Memory", "VectorStore", "Embeddings",
        "Retriever", "Document", "TextSplitter", "OutputParser",
    )):
        et = "agent" if base.lower() == "agent" else "llm"
        return nid, et, "ai", display, f"AI node: {display}"

    if base in ("Json", "Xml", "Html", "HtmlExtract", "Sort", "Limit", "Aggregate", "ItemLists"):
        return nid, "transform", "data", display, f"Data node: {display}"

    return nid, "integration", "app", display, f"{display} (n8n integration)"


def integration_properties() -> list[dict]:
    return [
        {"name": "resource", "displayName": "Resource", "type": "options", "default": "default",
         "options": [{"name": "Default", "value": "default"}, {"name": "Create", "value": "create"},
                     {"name": "Get", "value": "get"}, {"name": "Get Many", "value": "getAll"}]},
        {"name": "operation", "displayName": "Operation", "type": "options", "default": "getAll",
         "options": [{"name": "Create", "value": "create"}, {"name": "Get", "value": "get"},
                     {"name": "Get Many", "value": "getAll"}, {"name": "Update", "value": "update"},
                     {"name": "Delete", "value": "delete"}]},
        {"name": "credentials", "displayName": "Credentials", "type": "credentials"},
        {"name": "additionalFields", "displayName": "Additional Fields", "type": "json", "default": {}},
    ]


def trigger_properties() -> list[dict]:
    return [
        {"name": "path", "displayName": "Path / Event", "type": "string", "default": ""},
        {"name": "additionalFields", "displayName": "Additional Fields", "type": "json", "default": {}},
    ]


def control_nodes() -> list[dict]:
    return [
        {"id": "start", "type": "start", "category": "control", "name": "Start",
         "description": "Workflow entry point", "icon": "play-circle", "color": "#22c55e",
         "integration": None, "properties": [], "outputs": ["main"]},
        {"id": "end", "type": "end", "category": "control", "name": "End",
         "description": "Workflow exit point", "icon": "stop-circle", "color": "#ef4444",
         "integration": None, "properties": [], "outputs": ["main"]},
        {"id": "stickyNote", "type": "note", "category": "control", "name": "Sticky Note",
         "description": "Visual annotation", "icon": "sticky-note", "color": "#eab308",
         "integration": None,
         "properties": [{"name": "content", "displayName": "Note Content", "type": "code", "default": ""}],
         "outputs": ["main"]},
    ]


def main() -> None:
    print("Fetching n8n git tree...")
    paths = fetch_node_paths()
    print(f"Found {len(paths)} node definition files")

    seen: set[str] = set()
    nodes: list[dict] = control_nodes()
    seen.update(n["id"] for n in nodes)

    for path in sorted(paths):
        parts = path.split("/")
        filename = parts[-1]
        folder = parts[-2]
        package = "langchain" if "nodes-langchain" in path else "nodes-base"
        base = filename.replace(".node.ts", "")

        nid, exec_type, category, display, desc = infer_node(base, folder, package)
        if nid in seen:
            nid = f"{nid}_{folder.lower()}"
        if nid in seen:
            nid = f"{nid}_2"
        if nid in seen:
            continue
        seen.add(nid)

        props: list[dict] = []
        if exec_type == "integration":
            props = integration_properties()
        elif exec_type == "trigger":
            props = trigger_properties()

        nodes.append({
            "id": nid,
            "type": exec_type,
            "category": category,
            "name": display,
            "description": desc,
            "icon": ICON_BY_CATEGORY.get(category, "box"),
            "color": COLOR_BY_CATEGORY.get(category, "#ec4899"),
            "integration": nid if exec_type == "integration" else None,
            "properties": props,
            "outputs": ["main"],
            "n8n_file": path,
            "n8n_folder": folder,
        })

    categories = [
        {"id": "control", "name": "Control", "color": "#64748b"},
        {"id": "trigger", "name": "Triggers", "color": "#22c55e"},
        {"id": "core", "name": "Core", "color": "#3b82f6"},
        {"id": "flow", "name": "Flow", "color": "#6366f1"},
        {"id": "ai", "name": "AI", "color": "#8b5cf6"},
        {"id": "data", "name": "Data", "color": "#06b6d4"},
        {"id": "tools", "name": "Tools", "color": "#f97316"},
        {"id": "app", "name": "Apps & Integrations", "color": "#ec4899"},
    ]

    payload = {"nodes": nodes, "categories": categories, "total": len(nodes)}
    out_path = Path(__file__).resolve().parents[1] / "app" / "core" / "workflow" / "n8n_nodes_raw.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(nodes)} nodes to {out_path}")


if __name__ == "__main__":
    main()
