"""
Online skill library: browse bundled catalog and import SKILL.md from GitHub.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import generate_uuid
from app.db.models import Skill, SkillStatus

logger = structlog.get_logger(__name__)

CATALOG_PATH = Path(__file__).with_name("skill_library_catalog.json")

SKILLHUB_CN_API = "https://api.skillhub.cn"
SKILLHUB_CN_HEADERS = {
    "User-Agent": "AIAGNET-skill-library",
    "Accept": "application/json",
    "Origin": "https://skillhub.cn",
    "Referer": "https://skillhub.cn/",
}

SOURCE_CONFIG: dict[str, dict[str, str]] = {
    "anthropic": {
        "repo": "anthropics/skills",
        "branch": "main",
    },
    "skills-hub": {
        "repo": "agent-skills-hub/agent-skills-hub",
        "branch": "main",
    },
    "skillhub-cn": {
        "api_base": SKILLHUB_CN_API,
    },
}

SKILLHUB_CN_SHOWCASE = ("hot", "trending", "recommended", "newest")


@dataclass
class ParsedSkillMd:
    name: str
    description: str
    body: str
    metadata: dict[str, Any]


def _load_catalog_file() -> dict[str, Any]:
    if not CATALOG_PATH.exists():
        return {"sources": [], "templates": []}
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _save_catalog_file(data: dict[str, Any]) -> None:
    CATALOG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_skill_md(content: str) -> ParsedSkillMd:
    metadata: dict[str, Any] = {}
    body = content
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if match:
        front = match.group(1)
        body = content[match.end():]
        for line in front.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip().strip('"').strip("'")
    name = str(metadata.get("name") or "").strip()
    description = str(metadata.get("description") or "").strip()
    return ParsedSkillMd(name=name, description=description, body=body.strip(), metadata=metadata)


def _raw_url(source: str, path: str) -> str:
    cfg = SOURCE_CONFIG.get(source)
    if not cfg:
        raise ValueError(f"Unknown skill library source: {source}")
    if "repo" not in cfg:
        raise ValueError(f"Source {source} does not use GitHub raw URLs")
    return f"https://raw.githubusercontent.com/{cfg['repo']}/{cfg['branch']}/{path}"


def _skillhub_slug_from_path(path: str) -> str:
    parts = [p for p in path.strip("/").split("/") if p and p != "SKILL.md"]
    if parts and parts[0] == "skillhub-cn":
        parts = parts[1:]
    return parts[-1] if parts else path


async def fetch_skillhub_skill_md(slug: str) -> str:
    import io
    import zipfile

    import httpx

    url = f"{SKILLHUB_CN_API}/api/v1/download?slug={slug}"
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=SKILLHUB_CN_HEADERS)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = zf.namelist()
            for candidate in ("SKILL.md", "skill.md"):
                if candidate in names:
                    return zf.read(candidate).decode("utf-8")
            for name in names:
                if name.lower().endswith(".md"):
                    return zf.read(name).decode("utf-8")
        raise ValueError(f"No SKILL.md found in SkillHub download for {slug}")


async def fetch_skill_md(source: str, path: str) -> str:
    if source == "skillhub-cn":
        slug = _skillhub_slug_from_path(path)
        return await fetch_skillhub_skill_md(slug)

    import httpx

    url = _raw_url(source, path)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "AIAGNET-skill-library"})
        resp.raise_for_status()
        return resp.text


class SkillLibrary:
    @classmethod
    def get_sources(cls) -> list[dict[str, Any]]:
        catalog = _load_catalog_file()
        return catalog.get("sources", [])

    @classmethod
    def list_catalog(
        cls,
        source: str | None = None,
        category: str | None = None,
        query: str | None = None,
        lang: str | None = None,
    ) -> list[dict[str, Any]]:
        catalog = _load_catalog_file()
        items = catalog.get("templates", [])
        if source:
            items = [t for t in items if t.get("source") == source]
        if category:
            items = [t for t in items if t.get("category") == category]
        if query:
            q = query.lower()
            items = [
                t for t in items
                if q in (t.get("slug") or "").lower()
                or q in (t.get("display_name") or "").lower()
                or q in (t.get("description") or "").lower()
                or any(q in tag.lower() for tag in (t.get("tags") or []))
            ]
        if lang:
            from app.core.skills.i18n import localize_catalog_template
            items = [localize_catalog_template(t, lang) for t in items]
        return items

    @classmethod
    def list_categories(cls, source: str | None = None) -> list[str]:
        items = cls.list_catalog(source=source)
        cats = sorted({t.get("category", "general") for t in items if t.get("category")})
        return cats

    @classmethod
    def find_template(cls, source: str, slug: str) -> dict[str, Any] | None:
        for item in _load_catalog_file().get("templates", []):
            if item.get("source") == source and item.get("slug") == slug:
                return item
        return None

    @classmethod
    async def import_templates(
        cls,
        db: AsyncSession,
        items: list[dict[str, str]],
        overwrite: bool = False,
    ) -> dict[str, Any]:
        imported: list[str] = []
        skipped: list[str] = []
        errors: list[dict[str, str]] = []

        for item in items:
            source = item.get("source", "")
            slug = item.get("slug", "")
            if not source or not slug:
                errors.append({"source": source, "slug": slug, "error": "Missing source or slug"})
                continue

            template = cls.find_template(source, slug)
            if template:
                path = template.get("path") or ""
            elif source == "skillhub-cn":
                path = f"skillhub-cn/{slug}/SKILL.md"
            else:
                path = f"skills/{slug}/SKILL.md"

            result = await db.execute(select(Skill).where(Skill.slug == slug))
            existing = result.scalar_one_or_none()
            if existing and not overwrite:
                skipped.append(slug)
                continue

            try:
                raw = await fetch_skill_md(source, path)
                parsed = parse_skill_md(raw)
                display_name = parsed.name or slug.replace("-", " ").title()
                description = parsed.description or (template or {}).get("description") or display_name
                instructions_md = parsed.body or raw
                tags = list((template or {}).get("tags") or [])
                if source not in tags:
                    tags.append(source)

                if existing:
                    existing.display_name = display_name
                    existing.description = description
                    existing.instructions_md = instructions_md
                    existing.status = SkillStatus.active
                    existing.tags = tags
                    existing.metadata_ = {
                        **(existing.metadata_ or {}),
                        "library_source": source,
                        "library_path": path,
                    }
                    existing.version = (existing.version or 1) + 1
                else:
                    db.add(Skill(
                        id=generate_uuid(),
                        slug=slug,
                        display_name=display_name,
                        description=description,
                        instructions_md=instructions_md,
                        status=SkillStatus.active,
                        scope="global",
                        auto_invoke=False,
                        tags=tags,
                        metadata_={"library_source": source, "library_path": path},
                    ))
                imported.append(slug)
            except Exception as exc:
                logger.warning("skill_import_failed", source=source, slug=slug, error=str(exc))
                errors.append({"source": source, "slug": slug, "error": str(exc)})

        await db.flush()
        return {"imported": imported, "skipped": skipped, "errors": errors}

    @classmethod
    async def sync_catalog_from_hub(cls) -> dict[str, Any]:
        """Refresh skills-hub entries from CATALOG.md (metadata only)."""
        import httpx

        url = _raw_url("skills-hub", "CATALOG.md")
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "AIAGNET-skill-library"})
            resp.raise_for_status()
            catalog_md = resp.text

        hub_templates = _parse_hub_catalog_md(catalog_md)
        data = _load_catalog_file()
        data["templates"] = [
            t for t in data.get("templates", []) if t.get("source") != "skills-hub"
        ] + hub_templates

        sources = {s["id"]: s for s in data.get("sources", [])}
        sources["skills-hub"] = {
            "id": "skills-hub",
            "name": "Agent Skills Hub",
            "name_zh": "Agent Skills Hub 社区库",
            "repo": "agent-skills-hub/agent-skills-hub",
            "branch": "main",
            "base_path": "skills",
            "url": "https://github.com/agent-skills-hub/agent-skills-hub",
        }
        data["sources"] = list(sources.values())
        _save_catalog_file(data)
        return {"hub_templates": len(hub_templates), "total_templates": len(data["templates"])}

    @classmethod
    async def sync_catalog_from_skillhub_cn(cls) -> dict[str, Any]:
        """Refresh skillhub-cn entries from showcase APIs (hot / trending / recommended / newest)."""
        import httpx

        templates_by_slug: dict[str, dict[str, Any]] = {}
        section_counts: dict[str, int] = {}

        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
            for section in SKILLHUB_CN_SHOWCASE:
                resp = await client.get(
                    f"{SKILLHUB_CN_API}/api/v1/showcase/{section}",
                    headers=SKILLHUB_CN_HEADERS,
                )
                resp.raise_for_status()
                payload = resp.json()
                skills = payload.get("skills") or []
                section_counts[section] = len(skills)

                for rank, item in enumerate(skills, start=1):
                    slug = str(item.get("slug") or "").strip()
                    if not slug:
                        continue

                    category = str(item.get("category") or "general").strip() or "general"
                    display_name = str(item.get("name") or slug).strip()
                    description = str(
                        item.get("description_zh") or item.get("description") or display_name
                    ).strip()
                    section_tag = f"skillhub-{section}"

                    if slug in templates_by_slug:
                        tags = templates_by_slug[slug].setdefault("tags", [])
                        if section_tag not in tags:
                            tags.append(section_tag)
                        continue

                    tags = [category, "skillhub-cn", section_tag]
                    templates_by_slug[slug] = {
                        "source": "skillhub-cn",
                        "slug": slug,
                        "path": f"skillhub-cn/{slug}/SKILL.md",
                        "display_name": display_name,
                        "description": description,
                        "category": category,
                        "tags": tags,
                    }

        skillhub_templates = list(templates_by_slug.values())
        data = _load_catalog_file()
        data["templates"] = [
            t for t in data.get("templates", []) if t.get("source") != "skillhub-cn"
        ] + skillhub_templates

        sources = {s["id"]: s for s in data.get("sources", [])}
        sources["skillhub-cn"] = {
            "id": "skillhub-cn",
            "name": "SkillHub China",
            "name_zh": "SkillHub 中国社区",
            "repo": "",
            "branch": "",
            "base_path": "skillhub-cn",
            "url": "https://skillhub.cn/",
        }
        data["sources"] = list(sources.values())
        _save_catalog_file(data)
        return {
            "skillhub_templates": len(skillhub_templates),
            "section_counts": section_counts,
            "total_templates": len(data["templates"]),
        }


def _parse_hub_catalog_md(text: str) -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    current_category = "general"
    row_re = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|$")

    for line in text.splitlines():
        if line.startswith("## "):
            current_category = line[3:].strip().split(" ", 1)[0]
            continue
        m = row_re.match(line)
        if not m:
            continue
        slug, desc, tags_raw, _triggers = m.groups()
        if slug.lower() == "skill":
            continue
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        path = f"skills/{slug}/SKILL.md"
        templates.append({
            "source": "skills-hub",
            "slug": slug,
            "path": path,
            "display_name": slug.split("/")[-1],
            "description": desc.strip(),
            "category": current_category,
            "tags": tags[:8] + ["skills-hub"],
        })
    return templates
