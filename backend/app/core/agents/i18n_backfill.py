"""Backfill metadata.i18n for agents already stored in the database."""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agents.agency_i18n import (
    build_agency_i18n,
    build_merged_agency_i18n,
    build_zh_only_i18n,
)
from app.core.agents.agency_library import (
    REPO_ZH,
    SOURCE_ZH,
    fetch_agency_md_optional,
    parse_agency_agent_md,
)
from app.core.agents.i18n import merge_agent_metadata_i18n
from app.core.agents.seed_i18n import seed_agent_i18n
from app.db.models import Agent, Skill


async def backfill_agency_skill_i18n(session: AsyncSession) -> dict[str, int]:
    from app.core.agents.agency_library import (
        AgencyAgentLibrary,
        ParsedAgencyAgent,
        REPO,
        SOURCE_ZH,
        fetch_agency_md,
        fetch_agency_md_optional,
        parse_agency_agent_md,
    )

    result = await session.execute(select(Skill))
    stats = {"updated": 0, "skipped": 0}
    for skill in result.scalars().all():
        meta = dict(skill.metadata_ or {})
        slug = meta.get("agency_slug")
        if not slug:
            stats["skipped"] += 1
            continue
        slug_str = str(slug)
        path = meta.get("library_path") or f"{slug_str.split('-', 1)[0]}/{slug_str}.md"
        zh_path = meta.get("zh_path") or path
        try:
            if meta.get("library_source") == SOURCE_ZH or meta.get("zh_only"):
                raw_zh = await fetch_agency_md(path, repo=REPO_ZH)
                parsed_zh = parse_agency_agent_md(raw_zh, path=path, source_id=SOURCE_ZH)
                name_en = slug_str.replace("-", " ").title()
                parsed_en = ParsedAgencyAgent(
                    slug=slug_str,
                    division=parsed_zh.division,
                    name=name_en,
                    role=name_en,
                    goal=parsed_zh.goal,
                    backstory="",
                    description=name_en,
                    tags=parsed_zh.tags,
                    path=path,
                    raw="",
                    workflow_md="",
                )
                skill.metadata_ = AgencyAgentLibrary._agency_skill_metadata(
                    slug=slug_str,
                    path=path,
                    parsed_en=parsed_en,
                    parsed_zh=parsed_zh,
                    library_source=str(meta.get("library_source") or SOURCE_ZH),
                )
                if parsed_zh.workflow_md:
                    skill.instructions_md = parsed_zh.workflow_md
            else:
                raw_en = await fetch_agency_md(path, repo=REPO)
                parsed_en = parse_agency_agent_md(raw_en, path=path)
                zh_raw = await fetch_agency_md_optional(zh_path, repo=REPO_ZH)
                parsed_zh = (
                    parse_agency_agent_md(zh_raw, path=zh_path, source_id=SOURCE_ZH)
                    if zh_raw else None
                )
                skill.display_name = f"{parsed_en.name} SOP"
                if parsed_en.workflow_md:
                    skill.instructions_md = parsed_en.workflow_md
                skill.metadata_ = AgencyAgentLibrary._agency_skill_metadata(
                    slug=slug_str,
                    path=path,
                    parsed_en=parsed_en,
                    parsed_zh=parsed_zh,
                    library_source=str(meta.get("library_source") or "agency-agents"),
                )
            stats["updated"] += 1
        except Exception:
            stats["skipped"] += 1

    await session.flush()
    return stats


async def backfill_all_agent_i18n(session: AsyncSession) -> dict[str, int | dict[str, int]]:
    result = await session.execute(select(Agent))
    agents = result.scalars().all()
    stats = {"agency": 0, "agency_zh": 0, "seed": 0, "skipped": 0}

    for agent in agents:
        meta = dict(agent.metadata_ or {})
        if meta.get("agency_slug"):
            slug = str(meta["agency_slug"])
            division = str(meta.get("division") or "engineering")
            path = meta.get("zh_path") or meta.get("library_path") or f"{division}/{slug}.md"

            stub = SimpleNamespace(
                slug=slug,
                division=division,
                name=agent.name,
                role=agent.role,
                goal=agent.goal,
                description=agent.role,
                backstory=agent.backstory or "",
            )

            if meta.get("zh_only") or meta.get("library_source") == SOURCE_ZH:
                zh_raw = await fetch_agency_md_optional(path, repo=REPO_ZH)
                if zh_raw:
                    zh_parsed = parse_agency_agent_md(zh_raw, path=path, source_id=SOURCE_ZH)
                    agent.metadata_ = merge_agent_metadata_i18n(
                        {**meta, "translation_source": SOURCE_ZH},
                        build_zh_only_i18n(zh_parsed),
                    )
                    stats["agency_zh"] += 1
                else:
                    agent.metadata_ = merge_agent_metadata_i18n(meta, build_agency_i18n(stub))
                    stats["agency"] += 1
                continue

            zh_raw = await fetch_agency_md_optional(path, repo=REPO_ZH)
            if zh_raw:
                zh_parsed = parse_agency_agent_md(zh_raw, path=path, source_id=SOURCE_ZH)
                agent.metadata_ = merge_agent_metadata_i18n(
                    {**meta, "translation_source": SOURCE_ZH, "zh_path": path},
                    build_merged_agency_i18n(stub, zh_parsed),
                )
                stats["agency_zh"] += 1
            else:
                agent.metadata_ = merge_agent_metadata_i18n(meta, build_agency_i18n(stub))
                stats["agency"] += 1
            continue

        seed_i18n = seed_agent_i18n(agent.name)
        if seed_i18n:
            agent.metadata_ = merge_agent_metadata_i18n(meta, seed_i18n)
            stats["seed"] += 1
            continue

        stats["skipped"] += 1

    await session.flush()
    skill_stats = await backfill_agency_skill_i18n(session)
    return {**stats, "skills": skill_stats}
