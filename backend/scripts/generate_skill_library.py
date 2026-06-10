"""
Build bundled skill_library_catalog.json from online sources.
Run: python scripts/generate_skill_library.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "core" / "skills" / "skill_library_catalog.json"

ANTHROPIC_SKILLS = [
    "algorithmic-art", "brand-guidelines", "canvas-design", "claude-api", "doc-coauthoring",
    "docx", "frontend-design", "internal-comms", "mcp-builder", "pdf", "pptx",
    "skill-creator", "slack-gif-creator", "theme-factory", "web-artifacts-builder",
    "webapp-testing", "xlsx",
]

CATEGORY = {
    "docx": "document", "pdf": "document", "pptx": "document", "xlsx": "document",
    "webapp-testing": "dev", "mcp-builder": "dev", "claude-api": "dev",
    "frontend-design": "dev", "web-artifacts-builder": "dev",
    "internal-comms": "enterprise", "brand-guidelines": "enterprise", "doc-coauthoring": "enterprise",
    "algorithmic-art": "creative", "canvas-design": "creative", "theme-factory": "creative",
    "slack-gif-creator": "creative", "skill-creator": "meta",
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "AIAGNET-skill-library-gen"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", "replace")


def parse_frontmatter(md: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", md, re.DOTALL)
    if not m:
        return meta
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta


def parse_hub_catalog(text: str) -> list[dict]:
    from app.core.skills.library import _parse_hub_catalog_md
    return _parse_hub_catalog_md(text)


def main() -> None:
    sys.path.insert(0, str(ROOT))
    templates: list[dict] = []

    for slug in ANTHROPIC_SKILLS:
        url = f"https://raw.githubusercontent.com/anthropics/skills/main/skills/{slug}/SKILL.md"
        try:
            md = fetch(url)
            meta = parse_frontmatter(md)
            templates.append({
                "source": "anthropic",
                "slug": slug,
                "path": f"skills/{slug}/SKILL.md",
                "display_name": meta.get("name", slug),
                "description": meta.get("description", ""),
                "category": CATEGORY.get(slug, "general"),
                "tags": [CATEGORY.get(slug, "general"), "anthropic"],
            })
            print(f"anthropic ok: {slug}")
        except Exception as exc:
            print(f"anthropic fail: {slug} -> {exc}")

    try:
        hub_md = fetch("https://raw.githubusercontent.com/agent-skills-hub/agent-skills-hub/main/CATALOG.md")
        hub_items = parse_hub_catalog(hub_md)
        templates.extend(hub_items)
        print(f"skills-hub ok: {len(hub_items)} templates")
    except Exception as exc:
        print(f"skills-hub fail: {exc}")

    data = {
        "sources": [
            {
                "id": "anthropic",
                "name": "Anthropic Official",
                "name_zh": "Anthropic 官方技能库",
                "repo": "anthropics/skills",
                "branch": "main",
                "base_path": "skills",
                "url": "https://github.com/anthropics/skills",
            },
            {
                "id": "skills-hub",
                "name": "Agent Skills Hub",
                "name_zh": "Agent Skills Hub 社区库",
                "repo": "agent-skills-hub/agent-skills-hub",
                "branch": "main",
                "base_path": "skills",
                "url": "https://github.com/agent-skills-hub/agent-skills-hub",
            },
            {
                "id": "skillhub-cn",
                "name": "SkillHub China",
                "name_zh": "SkillHub 中国社区",
                "repo": "",
                "branch": "",
                "base_path": "skillhub-cn",
                "url": "https://skillhub.cn/",
            },
        ],
        "templates": templates,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written {OUT} ({len(templates)} templates)")

    try:
        import asyncio
        from app.core.skills.library import SkillLibrary

        cn_result = asyncio.run(SkillLibrary.sync_catalog_from_skillhub_cn())
        print(f"skillhub-cn ok: {cn_result}")
        data = json.loads(OUT.read_text(encoding="utf-8"))
        print(f"catalog total: {len(data.get('templates', []))} templates")
    except Exception as exc:
        print(f"skillhub-cn fail: {exc}")


if __name__ == "__main__":
    main()
