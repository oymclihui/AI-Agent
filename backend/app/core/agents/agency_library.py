"""
Online agent library: browse and import role personas from Agency Agents repos.

- English: msitarzewski/agency-agents
- Chinese translations (+ China-only roles): jnMetaCode/agency-agents-zh
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

from app.config import settings
from app.core.agents.agency_i18n import (
    agency_name_zh,
    build_agency_i18n,
    build_merged_agency_i18n,
    build_zh_only_i18n,
)
from app.core.agents.i18n import merge_agent_metadata_i18n
from app.core.skills.i18n import build_i18n_metadata, merge_skill_metadata_i18n
from app.core.skills.library import parse_skill_md
from app.db.base import generate_uuid
from app.db.models import Agent, AgentStatus, Skill, SkillStatus

logger = structlog.get_logger(__name__)

CATALOG_PATH = Path(__file__).with_name("agent_library_catalog.json")

REPO = "msitarzewski/agency-agents"
REPO_ZH = "jnMetaCode/agency-agents-zh"
BRANCH = "main"
SOURCE_ID = "agency-agents"
SOURCE_ZH = "agency-agents-zh"

DIVISION_TOOLS: dict[str, list[str]] = {
    "engineering": ["calculator", "http_request", "datetime"],
    "security": ["web_search", "http_request"],
    "marketing": ["web_search"],
    "design": ["web_search"],
    "product": ["web_search", "datetime"],
    "data": ["calculator", "datetime"],
    "research": ["web_search", "datetime"],
    "support": ["web_search", "datetime"],
    "legal": ["web_search"],
    "finance": ["calculator", "datetime"],
    "hr": ["web_search", "datetime"],
    "operations": ["web_search", "datetime"],
    "sales": ["web_search"],
    "community": ["web_search"],
    "creative": ["web_search"],
    "executive": ["web_search", "datetime"],
}

DIVISION_TEMPERATURE: dict[str, float] = {
    "engineering": 0.25,
    "security": 0.2,
    "marketing": 0.8,
    "creative": 0.85,
    "design": 0.7,
    "data": 0.3,
    "research": 0.35,
}

# Agency personas whose workflow sections also belong in the Skill library.
SKILL_WORKFLOW_SLUGS = frozenset({
    "engineering-code-reviewer",
    "engineering-git-workflow-master",
    "engineering-prompt-engineer",
    "engineering-technical-writer",
    "engineering-minimal-change-engineer",
    "engineering-sre",
    "engineering-data-engineer",
    "security-appsec-engineer",
    "security-senior-secops",
    "marketing-seo-specialist",
    "marketing-content-creator",
})


@dataclass
class ParsedAgencyAgent:
    slug: str
    division: str
    name: str
    role: str
    goal: str
    backstory: str
    description: str
    tags: list[str]
    path: str
    raw: str
    workflow_md: str


def _load_catalog_file() -> dict[str, Any]:
    if not CATALOG_PATH.exists():
        return {"sources": [], "templates": []}
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _save_catalog_file(data: dict[str, Any]) -> None:
    CATALOG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _raw_url(path: str, *, repo: str = REPO, branch: str = BRANCH) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


def _extract_section(body: str, heading: str) -> str:
    pattern = rf"^##\s*{re.escape(heading)}\s*\n(.*?)(?=^##\s|\Z)"
    match = re.search(pattern, body, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _goal_from_body(body: str, description: str) -> str:
    for heading in (
        "🎯 Your Core Mission",
        "Your Core Mission",
        "🎯 你的核心使命",
        "你的核心使命",
        "🎯 核心使命",
        "核心使命",
    ):
        mission = _extract_section(body, heading)
        if mission:
            lines = [ln.strip() for ln in mission.splitlines() if ln.strip() and not ln.strip().startswith("#")]
            text = " ".join(lines[:6])
            return text[:2000] if text else description
    return description[:2000]


def _workflow_md(body: str) -> str:
    workflow = ""
    for heading in (
        "🔄 Your Workflow Process",
        "Your Workflow Process",
        "🔄 你的工作流程",
        "你的工作流程",
        "🔄 工作流程",
        "工作流程",
    ):
        workflow = _extract_section(body, heading)
        if workflow:
            break
    rules = ""
    for heading in (
        "🚨 Critical Rules You Must Follow",
        "Critical Rules You Must Follow",
        "🚨 你必须遵守的关键规则",
        "你必须遵守的关键规则",
        "🚨 关键规则",
        "关键规则",
    ):
        rules = _extract_section(body, heading)
        if rules:
            break
    parts = []
    if workflow:
        parts.append("## Workflow\n\n" + workflow)
    if rules:
        parts.append("## Critical Rules\n\n" + rules)
    return "\n\n".join(parts).strip()


def parse_agency_agent_md(
    content: str,
    *,
    path: str,
    source_id: str = SOURCE_ID,
) -> ParsedAgencyAgent:
    parsed = parse_skill_md(content)
    parts = path.strip("/").split("/")
    division = parts[0] if len(parts) > 1 else "general"
    filename = parts[-1].replace(".md", "")
    slug = filename

    name = parsed.name or slug.replace("-", " ").title()
    description = parsed.description or name
    body = parsed.body or content
    goal = _goal_from_body(body, description)
    role = description[:255] if len(description) <= 255 else description[:252] + "..."

    tags = [division, source_id]
    if parsed.metadata.get("emoji"):
        tags.append(str(parsed.metadata["emoji"]))

    return ParsedAgencyAgent(
        slug=slug,
        division=division,
        name=name[:255],
        role=role,
        goal=goal,
        backstory=body[:48000],
        description=description,
        tags=tags,
        path=path,
        raw=content,
        workflow_md=_workflow_md(body),
    )


def _tools_for_division(division: str) -> list[dict[str, str]]:
    names = DIVISION_TOOLS.get(division, ["web_search"])
    return [{"tool_name": t} for t in names]


def _temperature_for_division(division: str) -> float:
    return DIVISION_TEMPERATURE.get(division, 0.6)


async def fetch_agency_md(path: str, *, repo: str = REPO) -> str:
    import httpx

    url = _raw_url(path, repo=repo)
    async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "AIAGNET-agent-library"})
        resp.raise_for_status()
        return resp.text


async def fetch_agency_md_optional(path: str, *, repo: str = REPO) -> str | None:
    import httpx

    url = _raw_url(path, repo=repo)
    try:
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "AIAGNET-agent-library"})
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.text
    except Exception as exc:
        logger.debug("agency_md_fetch_skipped", path=path, repo=repo, error=str(exc))
        return None


async def _list_repo_md_paths(repo: str, *, branch: str = BRANCH) -> list[str]:
    import httpx

    url = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "AIAGNET-agent-library"})
        resp.raise_for_status()
        tree = resp.json().get("tree") or []

    skip_prefixes = (
        "scripts/", "integrations/", "docs/", ".github/",
        "converted/", "templates/", "examples/",
    )
    paths: list[str] = []
    for node in tree:
        path = str(node.get("path") or "")
        if node.get("type") != "blob" or not path.endswith(".md"):
            continue
        if path.lower() in ("readme.md", "contributing.md", "license.md"):
            continue
        if any(path.startswith(p) for p in skip_prefixes):
            continue
        if "/" not in path:
            continue
        paths.append(path)
    return paths


class AgencyAgentLibrary:
    @classmethod
    def get_sources(cls) -> list[dict[str, Any]]:
        catalog = _load_catalog_file()
        return catalog.get("sources", [])

    @classmethod
    def list_catalog(
        cls,
        source: str | None = None,
        division: str | None = None,
        query: str | None = None,
        lang: str | None = None,
    ) -> list[dict[str, Any]]:
        catalog = _load_catalog_file()
        items = catalog.get("templates", [])
        if source:
            items = [t for t in items if t.get("source") == source]
        if division:
            items = [t for t in items if t.get("division") == division]
        if query:
            q = query.lower()
            items = [
                t for t in items
                if q in (t.get("slug") or "").lower()
                or q in (t.get("name") or "").lower()
                or q in (t.get("description") or "").lower()
                or q in (t.get("division") or "").lower()
            ]
        if lang:
            from app.core.agents.i18n import localize_catalog_agent
            items = [localize_catalog_agent(t, lang) for t in items]
        return items

    @classmethod
    def list_divisions(cls, source: str | None = None) -> list[str]:
        items = cls.list_catalog(source=source)
        return sorted({t.get("division", "general") for t in items if t.get("division")})

    @classmethod
    def find_template(cls, source: str, slug: str) -> dict[str, Any] | None:
        for item in _load_catalog_file().get("templates", []):
            if item.get("source") == source and item.get("slug") == slug:
                return item
        return None

    @classmethod
    async def sync_catalog(cls) -> dict[str, Any]:
        en_paths = await _list_repo_md_paths(REPO)
        templates: list[dict[str, Any]] = []
        for path in en_paths:
            division = path.split("/", 1)[0]
            slug = Path(path).stem
            name_en = slug.replace("-", " ").title()
            stub = type("Stub", (), {
                "slug": slug,
                "division": division,
                "name": name_en,
                "role": name_en,
                "goal": name_en,
                "description": name_en,
                "backstory": "",
            })()
            name_zh = agency_name_zh(stub)
            templates.append({
                "source": SOURCE_ID,
                "slug": slug,
                "path": path,
                "division": division,
                "name": name_en,
                "name_zh": name_zh,
                "name_en": name_en,
                "description": name_en,
                "description_zh": name_zh,
                "description_en": name_en,
                "tags": [division, SOURCE_ID],
                "i18n": {
                    "name": {"zh": name_zh, "en": name_en},
                    "description": {"zh": name_zh, "en": name_en},
                },
            })

        data = _load_catalog_file()
        data["templates"] = [
            t for t in data.get("templates", []) if t.get("source") != SOURCE_ID
        ] + templates

        en_by_slug = {t["slug"]: t for t in templates}
        zh_only_templates: list[dict[str, Any]] = []
        zh_matched = 0
        try:
            zh_paths = await _list_repo_md_paths(REPO_ZH)
            for path in zh_paths:
                division = path.split("/", 1)[0]
                slug = Path(path).stem
                if slug in en_by_slug:
                    en_by_slug[slug]["zh_path"] = path
                    en_by_slug[slug]["has_official_zh"] = True
                    zh_matched += 1
                else:
                    name_en = slug.replace("-", " ").title()
                    zh_only_templates.append({
                        "source": SOURCE_ZH,
                        "slug": slug,
                        "path": path,
                        "division": division,
                        "name": name_en,
                        "name_en": name_en,
                        "description": name_en,
                        "tags": [division, SOURCE_ZH, "china"],
                        "zh_only": True,
                    })
        except Exception as exc:
            logger.warning("agency_zh_catalog_sync_failed", error=str(exc))
            zh_paths = []

        data["templates"] = [
            t for t in data.get("templates", []) if t.get("source") != SOURCE_ZH
        ] + zh_only_templates

        sources = {s["id"]: s for s in data.get("sources", [])}
        sources[SOURCE_ID] = {
            "id": SOURCE_ID,
            "name": "The Agency",
            "name_zh": "Agency Agents 角色库（英文）",
            "repo": REPO,
            "branch": BRANCH,
            "url": f"https://github.com/{REPO}",
        }
        sources[SOURCE_ZH] = {
            "id": SOURCE_ZH,
            "name": "Agency Agents 中文",
            "name_zh": "Agency Agents 中文角色库",
            "repo": REPO_ZH,
            "branch": BRANCH,
            "url": f"https://github.com/{REPO_ZH}",
        }
        data["sources"] = list(sources.values())
        _save_catalog_file(data)
        return {
            "agency_templates": len(templates),
            "zh_matched": zh_matched,
            "zh_only_templates": len(zh_only_templates),
            "divisions": len({t["division"] for t in templates}),
            "total_templates": len(data["templates"]),
        }

    @classmethod
    def _agency_skill_i18n(
        cls,
        parsed_en: ParsedAgencyAgent,
        parsed_zh: ParsedAgencyAgent | None = None,
    ) -> dict[str, Any]:
        display_en = f"{parsed_en.name} SOP"
        desc_en = (
            f"Procedural workflow from Agency agent «{parsed_en.name}». "
            f"Use when the user needs {parsed_en.name.lower()} style deliverables."
        )
        if parsed_zh:
            display_zh = f"{parsed_zh.name} SOP"
            desc_zh = parsed_zh.description or f"Agency 角色「{parsed_zh.name}」的标准作业流程。"
            return build_i18n_metadata(
                display_name_zh=display_zh[:255],
                display_name_en=display_en[:255],
                description_zh=desc_zh[:2000],
                description_en=desc_en[:2000],
            )
        return build_i18n_metadata(
            display_name_zh=display_en[:255],
            display_name_en=display_en[:255],
            description_zh=desc_en[:2000],
            description_en=desc_en[:2000],
        )

    @classmethod
    def _agency_skill_metadata(
        cls,
        *,
        slug: str,
        path: str,
        parsed_en: ParsedAgencyAgent,
        parsed_zh: ParsedAgencyAgent | None,
        library_source: str,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "library_source": library_source,
            "agency_slug": slug,
            "library_path": path,
        }
        if parsed_zh:
            meta["translation_source"] = SOURCE_ZH
            meta["zh_path"] = parsed_zh.path
            if parsed_en.workflow_md and parsed_zh.workflow_md:
                meta["instructions_i18n"] = {
                    "en": parsed_en.workflow_md,
                    "zh": parsed_zh.workflow_md,
                }
            elif parsed_zh.workflow_md and not parsed_en.workflow_md:
                meta["instructions_i18n"] = {
                    "zh": parsed_zh.workflow_md,
                    "en": parsed_zh.workflow_md,
                }
        return merge_skill_metadata_i18n(meta, cls._agency_skill_i18n(parsed_en, parsed_zh))

    @classmethod
    async def _upsert_agency_skill(
        cls,
        db: AsyncSession,
        *,
        slug: str,
        path: str,
        parsed_en: ParsedAgencyAgent,
        parsed_zh: ParsedAgencyAgent | None,
        overwrite: bool,
        library_source: str,
        imported_skills: list[str],
    ) -> None:
        if not parsed_en.workflow_md and not (parsed_zh and parsed_zh.workflow_md):
            return
        skill_slug = f"agency-{slug.split('-', 1)[-1]}"[:64]
        skill_result = await db.execute(select(Skill).where(Skill.slug == skill_slug))
        skill = skill_result.scalar_one_or_none()
        instructions_en = parsed_en.workflow_md or (parsed_zh.workflow_md if parsed_zh else "")
        display_en = f"{parsed_en.name} SOP"
        desc_en = (
            f"Procedural workflow from Agency agent «{parsed_en.name}». "
            f"Use when the user needs {parsed_en.name.lower()} style deliverables."
        )
        skill_meta = cls._agency_skill_metadata(
            slug=slug,
            path=path,
            parsed_en=parsed_en,
            parsed_zh=parsed_zh,
            library_source=library_source,
        )
        tags = parsed_en.tags + ["workflow", "agency-sop"]
        if skill and overwrite:
            skill.display_name = display_en
            skill.description = desc_en
            skill.instructions_md = instructions_en
            skill.tags = tags
            skill.metadata_ = skill_meta
        elif not skill:
            db.add(Skill(
                id=generate_uuid(),
                slug=skill_slug,
                display_name=display_en,
                description=desc_en,
                instructions_md=instructions_en,
                status=SkillStatus.active,
                scope="global",
                auto_invoke=False,
                tags=tags,
                metadata_=skill_meta,
            ))
            imported_skills.append(skill_slug)

    @classmethod
    async def _resolve_i18n(
        cls,
        parsed_en: ParsedAgencyAgent,
        *,
        path: str,
        zh_path: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        zh_file = zh_path or path
        zh_raw = await fetch_agency_md_optional(zh_file, repo=REPO_ZH)
        meta_extra: dict[str, Any] = {}
        if zh_raw:
            parsed_zh = parse_agency_agent_md(zh_raw, path=zh_file, source_id=SOURCE_ZH)
            meta_extra["translation_source"] = SOURCE_ZH
            meta_extra["zh_path"] = zh_file
            return build_merged_agency_i18n(parsed_en, parsed_zh), meta_extra
        return build_agency_i18n(parsed_en), meta_extra

    @classmethod
    async def _find_agent_by_agency_slug(cls, db: AsyncSession, slug: str) -> Agent | None:
        result = await db.execute(select(Agent))
        for agent in result.scalars().all():
            meta = agent.metadata_ or {}
            if meta.get("agency_slug") == slug:
                return agent
        return None

    @classmethod
    async def import_templates(
        cls,
        db: AsyncSession,
        items: list[dict[str, str]],
        *,
        overwrite: bool = False,
        import_skills: bool = True,
    ) -> dict[str, Any]:
        imported_agents: list[str] = []
        imported_skills: list[str] = []
        skipped: list[str] = []
        errors: list[dict[str, str]] = []

        for item in items:
            source = item.get("source", SOURCE_ID)
            slug = item.get("slug", "")
            if source not in (SOURCE_ID, SOURCE_ZH) or not slug:
                errors.append({"slug": slug or "?", "error": "Invalid source or slug"})
                continue

            template = cls.find_template(source, slug)
            path = (template or {}).get("path") or f"{slug.split('-', 1)[0]}/{slug}.md"

            existing = await cls._find_agent_by_agency_slug(db, slug)
            if existing and not overwrite:
                skipped.append(slug)
                continue

            try:
                if source == SOURCE_ZH:
                    await cls._import_zh_only_agent(
                        db,
                        slug=slug,
                        path=path,
                        template=template,
                        existing=existing,
                        imported_agents=imported_agents,
                        import_skills=import_skills,
                        overwrite=overwrite,
                        imported_skills=imported_skills,
                    )
                    continue

                raw = await fetch_agency_md(path, repo=REPO)
                parsed = parse_agency_agent_md(raw, path=path)
                zh_path = (template or {}).get("zh_path")
                i18n, i18n_meta = await cls._resolve_i18n(parsed, path=path, zh_path=zh_path)
                meta_base = {
                    "library_source": SOURCE_ID,
                    "agency_slug": slug,
                    "division": parsed.division,
                    "library_path": path,
                    **i18n_meta,
                }

                if existing:
                    existing.name = parsed.name
                    existing.role = parsed.role
                    existing.goal = parsed.goal
                    existing.backstory = parsed.backstory
                    existing.tools_config = _tools_for_division(parsed.division)
                    existing.temperature = _temperature_for_division(parsed.division)
                    existing.metadata_ = merge_agent_metadata_i18n(
                        {**(existing.metadata_ or {}), **meta_base},
                        i18n,
                    )
                else:
                    db.add(Agent(
                        id=generate_uuid(),
                        name=parsed.name,
                        role=parsed.role,
                        goal=parsed.goal,
                        backstory=parsed.backstory,
                        llm_provider=settings.DEFAULT_LLM_PROVIDER,
                        llm_model=settings.DEFAULT_LLM_MODEL,
                        temperature=_temperature_for_division(parsed.division),
                        max_iterations=10,
                        tools_config=_tools_for_division(parsed.division),
                        skills_config=[],
                        memory_config={},
                        status=AgentStatus.active,
                        metadata_=merge_agent_metadata_i18n(meta_base, i18n),
                    ))
                imported_agents.append(slug)

                if import_skills and slug in SKILL_WORKFLOW_SLUGS:
                    zh_parsed: ParsedAgencyAgent | None = None
                    zh_skill_raw = await fetch_agency_md_optional(
                        zh_path or path,
                        repo=REPO_ZH,
                    )
                    if zh_skill_raw:
                        zh_parsed = parse_agency_agent_md(
                            zh_skill_raw,
                            path=zh_path or path,
                            source_id=SOURCE_ZH,
                        )
                    await cls._upsert_agency_skill(
                        db,
                        slug=slug,
                        path=path,
                        parsed_en=parsed,
                        parsed_zh=zh_parsed,
                        overwrite=overwrite,
                        library_source=SOURCE_ID,
                        imported_skills=imported_skills,
                    )
            except Exception as exc:
                logger.warning("agency_import_failed", slug=slug, error=str(exc))
                errors.append({"slug": slug, "error": str(exc)})

        await db.flush()
        return {
            "imported_agents": imported_agents,
            "imported_skills": imported_skills,
            "skipped": skipped,
            "errors": errors,
        }

    @classmethod
    async def _import_zh_only_agent(
        cls,
        db: AsyncSession,
        *,
        slug: str,
        path: str,
        template: dict[str, Any] | None,
        existing: Agent | None,
        imported_agents: list[str],
        import_skills: bool = True,
        overwrite: bool = False,
        imported_skills: list[str] | None = None,
    ) -> None:
        raw = await fetch_agency_md(path, repo=REPO_ZH)
        parsed = parse_agency_agent_md(raw, path=path, source_id=SOURCE_ZH)
        i18n = build_zh_only_i18n(parsed)
        meta_base = {
            "library_source": SOURCE_ZH,
            "agency_slug": slug,
            "division": parsed.division,
            "library_path": path,
            "zh_path": path,
            "zh_only": True,
            "translation_source": SOURCE_ZH,
        }
        if existing:
            existing.name = parsed.name
            existing.role = parsed.role
            existing.goal = parsed.goal
            existing.backstory = parsed.backstory
            existing.tools_config = _tools_for_division(parsed.division)
            existing.temperature = _temperature_for_division(parsed.division)
            existing.metadata_ = merge_agent_metadata_i18n(
                {**(existing.metadata_ or {}), **meta_base},
                i18n,
            )
        else:
            db.add(Agent(
                id=generate_uuid(),
                name=parsed.name,
                role=parsed.role,
                goal=parsed.goal,
                backstory=parsed.backstory,
                llm_provider=settings.DEFAULT_LLM_PROVIDER,
                llm_model=settings.DEFAULT_LLM_MODEL,
                temperature=_temperature_for_division(parsed.division),
                max_iterations=10,
                tools_config=_tools_for_division(parsed.division),
                skills_config=[],
                memory_config={},
                status=AgentStatus.active,
                metadata_=merge_agent_metadata_i18n(meta_base, i18n),
            ))
        imported_agents.append(slug)

        if import_skills and imported_skills is not None and parsed.workflow_md:
            name_en = slug.replace("-", " ").title()
            parsed_en = ParsedAgencyAgent(
                slug=slug,
                division=parsed.division,
                name=name_en,
                role=name_en,
                goal=parsed.goal,
                backstory="",
                description=name_en,
                tags=[parsed.division, SOURCE_ZH, "china"],
                path=path,
                raw="",
                workflow_md="",
            )
            await cls._upsert_agency_skill(
                db,
                slug=slug,
                path=path,
                parsed_en=parsed_en,
                parsed_zh=parsed,
                overwrite=overwrite,
                library_source=SOURCE_ZH,
                imported_skills=imported_skills,
            )

    @classmethod
    async def import_all(cls, db: AsyncSession, *, overwrite: bool = False) -> dict[str, Any]:
        en_items = [
            {"source": SOURCE_ID, "slug": t["slug"]}
            for t in cls.list_catalog(source=SOURCE_ID)
        ]
        result = await cls.import_templates(db, en_items, overwrite=overwrite)
        zh_items = [
            {"source": SOURCE_ZH, "slug": t["slug"]}
            for t in cls.list_catalog(source=SOURCE_ZH)
        ]
        if zh_items:
            zh_result = await cls.import_templates(
                db,
                zh_items,
                overwrite=overwrite,
                import_skills=True,
            )
            result["imported_agents"] = result["imported_agents"] + zh_result["imported_agents"]
            result["imported_skills"] = result["imported_skills"] + zh_result["imported_skills"]
            result["skipped"] = result["skipped"] + zh_result["skipped"]
            result["errors"] = result["errors"] + zh_result["errors"]
        return result
