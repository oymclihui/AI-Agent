"""
ui_render / ui_patch — declarative generative UI for AI Agent 对话

对标 deepseek-harness-intelligent-ui（MIT, 41 JS files）的核心协议：
- ui_render: { root: "id", components: [{ id, type, props, children }] } flat node list
- ui_patch: 4 ops { setProps, replaceNode, insertChild, removeNode } + baseVersion 并发保护
- validateTree: props spec + 跨节点引用 + cycle + LIMITS

后端 tool 负责 JSON schema 校验 + agent_events.deliverables/presented 落库；
前端渲染由 Next.js 组件 catalog 消费 SSE event 完成。
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 1. Component Catalog（精简自 intelligent-ui/src/catalog/catalog.js，先做 9 种常用）
# ---------------------------------------------------------------------------

COMPONENT_TYPES = [
    "Card", "Stack", "Grid", "Tabs",
    "Text", "Code", "Alert", "Badge", "Divider",
    "Stat", "Progress", "List", "Table", "Chart",
    "Timeline", "Choice", "Form", "JsonView", "CodeDiff", "Mermaid",
]

# Props spec language（对标 checkProps/checkSemantics）
# type: string | number | boolean | enum | array | object | any | scalar
# props values: { type, required?, values?, items?, max?, min? }
CATALOG_SPEC: dict[str, dict[str, Any]] = {
    "Card": {"children": True, "props": {"title": "string?", "subtitle": "string?", "footer": "string?"}},
    "Stack": {"children": True, "props": {"direction": "enum(vertical|horizontal)?", "gap": "number?"}},
    "Grid": {"children": True, "props": {"columns": "number(1-6)"}},
    "Tabs": {"children": True, "props": {"labels": "string[](max12)"}},
    "Text": {"children": False, "props": {"text": "string!", "tone": "enum(default|muted|info|success|warning|error)?"}},
    "Code": {"children": False, "props": {"code": "string!", "language": "string?"}},
    "Alert": {"children": False, "props": {"title": "string?", "text": "string!", "tone": "enum(default|muted|info|success|warning|error)?"}},
    "Stat": {"children": False, "props": {"label": "string!", "value": "scalar!", "delta": "string?", "trend": "enum(up|down|flat)?"}},
    "Progress": {"children": False, "props": {"value": "number!", "max": "number?", "label": "string?", "tone": "enum(default|muted|info|success|warning|error)?"}},
    "List": {"children": False, "props": {"items": "string[]!", "ordered": "boolean?"}},
    "Table": {"children": False, "props": {
        "columns": "string[]", "rows": "array[][]!", "columnTypes": "enum(text|number|date|boolean)[]?",
        "sortable": "boolean?", "searchable": "boolean?", "exportable": "boolean?", "caption": "string?",
        "pageSize": "number(1-100)?",
    }},
    "Chart": {"children": False, "props": {
        "kind": "enum(bar|line|area|pie)!", "labels": "array!", "series": "object[{name:string!,values:number[]}][]!",
        "title": "string?", "unit": "string?", "stacked": "boolean?", "height": "number(120-600)?",
    }},
    "Timeline": {"children": False, "props": {"items": "object[{title:string!,time:string?,text:string?,tone:enum!}][]!"}},
    "Choice": {"children": False, "props": {
        "question": "string!", "submitLabel": "string?", "recommended": "string?",
        "options": "object[{id:string?,label:string!,description:string?,prompt:string!}]!(2-8)",
    }},
    "Form": {"children": False, "props": {
        "title": "string?", "submitLabel": "string?", "prompt": "string!",
        "fields": "object[{name:string!,label:string!,type:enum(text|number|range|select|checkbox|date|textarea)!,options:string[]?,required:boolean?,placeholder:string?}]!()",
    }},
    "JsonView": {"children": False, "props": {"data": "any!", "title": "string?", "expandDepth": "number?"}},
    "CodeDiff": {"children": False, "props": {
        "title": "string?", "context": "number?",
        "files": "object[{path:string!,before:string?,after:string?,patch:string?,language:string?}]!()",
    }},
    "Mermaid": {"children": False, "props": {"code": "string!"}},
}

LIMITS = {
    "components": 300, "depth": 24,
    "tableRows": 500, "tableColumns": 24,
    "chartPoints": 500, "chartSeries": 12,
    "choiceOptions": 8, "formFields": 40,
    "timelineItems": 100, "diffFiles": 20,
}


# ---------------------------------------------------------------------------
# 2. Tree validation（对标 validateTree）
# ---------------------------------------------------------------------------

def _is_plain(v):
    return isinstance(v, dict)


def _parse_spec(spec_str: str) -> dict:
    """Parse compact spec string like 'string!' or 'number(1-6)?' or 'enum(bar|line)!'."""
    out = {"required": True}
    s = spec_str
    if s.endswith("?"):
        out["required"] = False
        s = s[:-1]
    if s.endswith("!"):
        out["required"] = True
        s = s[:-1]
    if s.startswith("enum("):
        out["type"] = "enum"
        out["values"] = s[5:-1].split("|")
    elif s.startswith("number("):
        # number(min-max)
        nums = s[7:-1].split("-")
        out["type"] = "number"
        if nums[0]:
            out["min"] = float(nums[0]) if "." in nums[0] else int(nums[0])
        if len(nums) > 1 and nums[1]:
            out["max"] = float(nums[1]) if "." in nums[1] else int(nums[1])
    elif s.startswith("string[]"):
        out["type"] = "array"
        out["items"] = {"type": "string"}
    elif s.startswith("object["):
        out["type"] = "array"
        out["items"] = {"type": "object"}
        if "()" in s:
            range_str = s[s.index("(") + 1:s.index(")")]
            if range_str and range_str[0].isdigit():
                out["max"] = int(range_str.split("-")[-1]) if "-" in range_str else int(range_str)
    elif s == "any":
        out["type"] = "any"
    elif s == "scalar":
        out["type"] = "scalar"
    elif s == "boolean":
        out["type"] = "boolean"
    else:
        out["type"] = s  # string | number | array
    return out


def _check_value(value, spec: dict, path: str, errors: list[str]) -> None:
    t = spec.get("type")
    if t == "any":
        return
    if spec.get("required") and value is None:
        errors.append(f"{path}: required but got null")
        return
    if value is None:
        return
    if t == "string":
        if not isinstance(value, str):
            errors.append(f"{path}: expected string, got {type(value).__name__}")
    elif t == "number":
        if not isinstance(value, (int, float)):
            errors.append(f"{path}: expected number")
        else:
            if "min" in spec and value < spec["min"]:
                errors.append(f"{path}: below min {spec['min']}")
            if "max" in spec and value > spec["max"]:
                errors.append(f"{path}: above max {spec['max']}")
    elif t == "boolean":
        if not isinstance(value, bool):
            errors.append(f"{path}: expected boolean")
    elif t == "scalar":
        if not isinstance(value, (str, int, float, bool)):
            errors.append(f"{path}: expected scalar")
    elif t == "enum":
        if value not in spec["values"]:
            errors.append(f"{path}: expected one of {spec['values']}, got {value}")
    elif t == "array":
        if not isinstance(value, list):
            errors.append(f"{path}: expected array")
        else:
            if "max" in spec and len(value) > spec["max"]:
                errors.append(f"{path}: too many items ({len(value)} > {spec['max']})")
            if "items" in spec and isinstance(spec["items"], dict):
                for i, item in enumerate(value):
                    _check_value(item, spec["items"], f"{path}[{i}]", errors)


def validate_tree(args: Any) -> dict:
    """Validate a ui_render payload. Returns {ok, errors, warnings}."""
    errors: list[str] = []
    warnings: list[str] = []

    if not _is_plain(args):
        return {"ok": False, "errors": ["arguments: expected object"], "warnings": []}

    root = args.get("root")
    components = args.get("components")
    if not root:
        errors.append("root: missing. Add 'root' field set to the id of the top component")
    if not isinstance(components, list) or not components:
        errors.append("components: expected non-empty array")
        return {"ok": False, "errors": errors, "warnings": warnings}
    if len(components) > LIMITS["components"]:
        errors.append(f"components: more than {LIMITS['components']}")

    by_id: dict[str, dict] = {}
    types: dict[str, int] = {}

    for i, node in enumerate(components):
        at = f"components[{i}]"
        if not _is_plain(node):
            errors.append(f"{at}: expected object")
            continue
        nid = node.get("id")
        ntype = node.get("type")
        if not nid or not isinstance(nid, str):
            errors.append(f"{at}.id: expected non-empty string")
            continue
        if nid in by_id:
            errors.append(f"{at}.id: duplicate id {nid}")
            continue
        if ntype not in CATALOG_SPEC:
            errors.append(f"{at}({nid}).type: unknown component {ntype}; use {COMPONENT_TYPES}")
            continue
        by_id[nid] = node
        types[ntype] = types.get(ntype, 0) + 1

        # Props check
        entry = CATALOG_SPEC[ntype]
        props_specs = entry.get("props", {})
        props = node.get("props") or {}
        for key, spec_str in props_specs.items():
            pspec = _parse_spec(spec_str)
            if pspec.get("required") and key not in props:
                errors.append(f"{at}({nid}).props.{key}: required")
            elif key in props:
                _check_value(props[key], pspec, f"{at}({nid}).props.{key}", errors)
        for key in props:
            if key not in props_specs:
                errors.append(f"{at}({nid}).props.{key}: unknown prop")

        # Children check
        children = node.get("children")
        if children is not None:
            if not isinstance(children, list):
                errors.append(f"{at}({nid}).children: expected array of ids")
            elif not entry.get("children") and children:
                errors.append(f"{at}({nid}).children: {ntype} cannot have children")

    # Cross-node references
    parent_of: dict[str, str] = {}
    for node in by_id.values():
        for c in node.get("children", []) or []:
            if c not in by_id:
                errors.append(f"{node['id']}.children: unknown id {c}")
            elif c == root:
                errors.append(f"{node['id']}.children: root cannot be a child")
            elif c in parent_of:
                errors.append(f"{c}: has two parents")
            else:
                parent_of[c] = node["id"]

    # Cycle detection
    if root in by_id:
        reached: set[str] = set()

        def walk(nid: str, depth: int, trail: set[str]) -> None:
            if nid in trail:
                errors.append(f"cycle through {nid}")
                return
            if depth > LIMITS["depth"]:
                errors.append(f"nesting deeper than {LIMITS['depth']}")
                return
            if nid in reached:
                return
            reached.add(nid)
            for c in by_id[nid].get("children", []) or []:
                if c in by_id:
                    walk(c, depth + 1, trail | {nid})

        walk(root, 0, set())
        orphans = [i for i in by_id if i not in reached]
        if orphans:
            warnings.append(f"not reachable from root (dropped): {orphans}")

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings, "types": types, "count": len(by_id)}


# ---------------------------------------------------------------------------
# 3. Catalog reference for model (inject into system prompt)
# ---------------------------------------------------------------------------

def catalog_reference() -> str:
    lines = []
    for name, entry in CATALOG_SPEC.items():
        props_str = ", ".join(f"{k}: {v}" for k, v in entry.get("props", {}).items())
        child_tag = " (children)" if entry.get("children") else ""
        lines.append(f"- {name}{child_tag} {{ {props_str} }}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. LangChain Tool — ui_render (StructuredTool.from_function 模式)
# ---------------------------------------------------------------------------

UI_TOOL_DESC = (
    "Show the user an interactive UI rendered natively in the chat. "
    "Use it when structured or visual presentation answers better than prose: "
    "comparisons, data, dashboards, choice decisions, processes.\n\n"
    "Send a FLAT list of components (NOT a nested tree). Each component is an object "
    "with id, type, props, and optional children (list of child ids). "
    "The top-level `root` field is REQUIRED and holds the top component's id.\n\n"
    "Components:\n" + catalog_reference() + "\n\n"
    "Only prompt Buttons and Form submissions send model messages; action Buttons call the host allowlist. "
    "Button clicks and Form submissions arrive later as user messages — do not wait for them in this turn.\n\n"
    "If the user asked for full analysis, write that prose after calling ui_render (max 1 short sentence); "
    "do not repeat the UI content in prose."
)


class _UiRenderArgs(BaseModel):
    root: str = Field(..., description="top component's id")
    components: list[dict[str, Any]] = Field(..., description="flat list of {id, type, props, children?}")
    title: str | None = Field(None, description="optional header title")


def _ui_render_func(root: str, components: list[dict[str, Any]], title: str | None = None) -> str:
    payload = {"root": root, "components": components or []}
    if title:
        payload["title"] = title
    result = validate_tree(payload)
    if not result["ok"]:
        return (
            f"UI not rendered: {len(result['errors'])} problem(s). Fix them and call ui_render again.\n"
            f"Errors:\n- " + "\n- ".join(result["errors"][:20])
        )
    kinds = ", ".join(
        f"{n}x {t}" if n > 1 else t
        for t, n in result["types"].items()
    )
    warn = f" Warning: {'; '.join(result['warnings'])}." if result["warnings"] else ""
    return (
        f"UI{' ' + title if title else ''} is now displayed to the user "
        f"({result['count']} components: {kinds}).{warn}"
    )


UiRenderTool = StructuredTool.from_function(
    func=_ui_render_func,
    name="ui_render",
    description=UI_TOOL_DESC,
    args_schema=_UiRenderArgs,
)



class _UiPatchArgs(BaseModel):
    ops: list[dict[str, Any]] = Field(..., description="patch operations: [{op, id?, parentId?, props?, node?, index?}]")
    base_version: int | None = Field(None, description="version of the UI currently shown to the user")
    title: str | None = Field(None, description="optional new header title")


UI_PATCH_GUIDE = """

### ui_patch 增量更新格式
如果上一轮已经渲染过 UI，本轮只需改动局部（改个数值、追加一行、删一个卡片），
调用 ui_patch 而不是重新 ui_render 整棵树：
```
ui_patch({ ops: [
  { op: "setProps",    id: "s1", props: { value: 123 } },
  { op: "setProps",    id: "t1", props: { rows: [["a", 1]] }, merge: false },
  { op: "replaceNode", id: "t2", node: { id: "t2", type: "Table", props: { columns: ["A"], rows: [["x"]] } } },
  { op: "insertChild", parentId: "grid1", node: { id: "c9", type: "Stat", props: { label: "新增", value: 9 } } },
  { op: "removeNode",  id: "c3" }
] })
```
- ops 必填，支持 setProps / replaceNode / insertChild / removeNode 四种操作。
- setProps 默认合并 props，merge: false 时整体替换。
- insertChild 需 parentId + node（node 必须带 id 和 type）。
- 只有确实存在上一轮 UI 时才用 ui_patch；首次展示一律用 ui_render。
"""


UI_PATCH_DESC = (
    "Patch the UI the user is already looking at, instead of re-sending the whole tree. "
    "Use when only part of a previously rendered ui_render view changes: update a value, "
    "append a row/card, remove a component.\n\n"
    "ops is a list of operations; each op is one of:\n"
    "- {op: 'setProps', id, props, merge?}   update props of an existing component\n"
    "- {op: 'replaceNode', id, node}         replace a component (node needs id, type, props)\n"
    "- {op: 'insertChild', parentId, node, index?}  add a component under a container (Card/Stack/Grid/Tabs)\n"
    "- {op: 'removeNode', id}                delete a component\n\n"
    "Do NOT use ui_patch for the first render of a view - call ui_render instead."
)


def _ui_patch_func(ops: list[dict[str, Any]], base_version: int | None = None, title: str | None = None) -> str:
    valid = {"setProps", "replaceNode", "insertChild", "removeNode"}
    errors: list[str] = []
    ops = ops or []
    if not ops:
        errors.append("ops: required but got empty list")
    if len(ops) > 50:
        errors.append(f"ops: too many operations ({len(ops)} > 50)")
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            errors.append(f"ops[{i}]: expected object")
            continue
        kind = op.get("op") or op.get("type")
        if kind not in valid:
            errors.append(f"ops[{i}]: op must be one of {sorted(valid)}, got {kind}")
            continue
        node = op.get("node")
        if kind in ("setProps", "replaceNode", "removeNode") and not op.get("id") and not (
            isinstance(node, dict) and node.get("id")
        ):
            errors.append(f"ops[{i}]: id required")
        if kind == "insertChild" and not (op.get("parentId") or op.get("id")):
            errors.append(f"ops[{i}]: parentId required")
        if kind in ("replaceNode", "insertChild"):
            if not isinstance(node, dict) or not node.get("id") or not node.get("type"):
                errors.append(f"ops[{i}]: node must contain id and type")
            elif node.get("type") not in COMPONENT_TYPES:
                errors.append(f"ops[{i}].node: unknown type {node.get('type')}")
    if errors:
        return (
            f"UI patch NOT applied: {len(errors)} problem(s). Fix them and call ui_patch again.\n"
            "Errors:\n- " + "\n- ".join(errors[:20])
        )
    return f"UI patch applied to the user's current view ({len(ops)} operation(s))."


UiPatchTool = StructuredTool.from_function(
    func=_ui_patch_func,
    name="ui_patch",
    description=UI_PATCH_DESC,
    args_schema=_UiPatchArgs,
)


# ---------------------------------------------------------------------------
# 5. Guidance (system prompt injection — 对标 guidanceText)
# ---------------------------------------------------------------------------

UI_GUIDANCE_STRONG = """
## 🎯 Intelligent UI — 必须掌握的技能

你拥有一个强大的工具叫 **ui_render**，可以在对话中原生渲染交互 UI 组件。**你应该主动使用它，而不是只输出纯文本。**

### 强制规则
- **任何需要展示结构化数据、对比、KPI、仪表盘、选择决策的回答，都必须调用 ui_render。**
- 调用 ui_render 后，最多再写 1 句简短的文字总结（不要在 prose 里重复 UI 已展示的内容）。
- 问候、简答、纯代码、原理讲解才用纯文本。
- 表格、图表、统计、卡片、选项 → **一律 ui_render**。
- 用户明确要求“用 ui_render / 渲染 / 看板 / 可视化”时，必须调用 ui_render；缺少真实数据时使用示例数据或“—”占位，并在文字里标注为示例，**不要反问用户要数据**。
- 不允许用 markdown 表格代替 ui_render（用户明确要纯文本时除外）。
- 所有组件必须能从 root 经 children 递归到达：根容器必须显式列出每个顶层子组件 id。
"""

UI_GUIDANCE_SPEC = """
### ui_render 调用格式
```
ui_render({
  root: "top_component_id",        // 必填！
  components: [
    { id: "top_component_id", type: "Card", props: { title: "今日销售" }, children: ["t1"] },
    { id: "t1", type: "Table", props: { columns: ["月份","金额"], rows: [["2025-01",177180.55]] } }
  ]
})
```

### 组件速查
""" + catalog_reference() + UI_PATCH_GUIDE


def ui_render_guidance_messages() -> list:
    """返回要注入 system prompt 的 SystemMessage（executor._build_system_messages 调用）。"""
    from langchain_core.messages import SystemMessage
    return [
        SystemMessage(content=UI_GUIDANCE_STRONG),
        SystemMessage(content=UI_GUIDANCE_SPEC),
    ]


# ---------------------------------------------------------------------------
# 6. 导出 (UiRenderTool 已是 StructuredTool 实例，可直接注册)
# ---------------------------------------------------------------------------

# UiRenderTool 就是 StructuredTool.from_function 返回的实例，已在第 330 行定义
