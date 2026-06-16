"""Export group chat discussion to Markdown."""
from __future__ import annotations

from typing import Any


def export_group_discussion_md(
    title: str,
    messages: list[Any],
    *,
    lang: str = "zh",
) -> str:
    heading = title or ("群聊讨论导出" if lang == "zh" else "Group Chat Export")
    lines = [f"# {heading}", ""]

    for msg in messages:
        meta = getattr(msg, "metadata_", None) or getattr(msg, "metadata", None) or {}
        if isinstance(meta, dict) is False:
            meta = {}
        role = getattr(msg, "role", None)
        role_val = role.value if hasattr(role, "value") else str(role)
        content = getattr(msg, "content", "") or ""

        if role_val == "user":
            lines.append("## 用户" if lang == "zh" else "## User")
            lines.append(content.strip())
            lines.append("")
            continue

        kind = meta.get("kind", "assistant")
        if kind == "round_divider":
            lines.append(f"---\n\n*{meta.get('label', 'Round')}*\n")
            continue

        agent_name = meta.get("agent_name") or ("助手" if lang == "zh" else "Assistant")
        agent_role = meta.get("agent_role") or ""
        rnd = meta.get("round")
        suffix = f" · R{rnd}" if rnd and kind != "synthesis" else ""
        if kind == "synthesis":
            lines.append(f"## 【共识结论】{agent_name}" if lang == "zh" else f"## 【Consensus】 {agent_name}")
        else:
            lines.append(f"### {agent_name} ({agent_role}){suffix}")

        thinking = meta.get("thinking")
        if thinking:
            lines.append("")
            lines.append("<details><summary>思考过程</summary>\n")
            lines.append(str(thinking).strip())
            lines.append("\n</details>")

        lines.append("")
        lines.append(content.strip())
        lines.append("")

    return "\n".join(lines).strip() + "\n"
