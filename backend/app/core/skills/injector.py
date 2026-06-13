"""
Load bound skills and inject instructions into agent / dialogue system prompts.
"""
from __future__ import annotations

from typing import Any

import structlog
from langchain_core.messages import SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Skill, SkillStatus

logger = structlog.get_logger(__name__)

MAX_INSTRUCTION_CHARS = 12000


class SkillInjector:
    @staticmethod
    def _skill_ids(skills_config: list[Any] | None) -> list[str]:
        ids: list[str] = []
        for item in skills_config or []:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict) and item.get("skill_id"):
                ids.append(str(item["skill_id"]))
        return ids

    @staticmethod
    def _binding_map(skills_config: list[Any] | None) -> dict[str, dict]:
        mapping: dict[str, dict] = {}
        for item in skills_config or []:
            if isinstance(item, dict) and item.get("skill_id"):
                mapping[str(item["skill_id"])] = item
        return mapping

    @classmethod
    async def load_skills(
        cls,
        db: AsyncSession,
        skills_config: list[Any] | None,
    ) -> list[Skill]:
        skill_ids = cls._skill_ids(skills_config)
        if not skill_ids:
            return []

        result = await db.execute(select(Skill).where(Skill.id.in_(skill_ids)))
        by_id = {s.id: s for s in result.scalars().all()}

        ordered: list[Skill] = []
        for sid in skill_ids:
            skill = by_id.get(sid)
            if skill and skill.status == SkillStatus.active:
                ordered.append(skill)
        return ordered

    @classmethod
    def _format_skill(cls, skill: Skill) -> str:
        parts = [
            f"# Skill: {skill.display_name} ({skill.slug})",
            "",
            skill.description.strip(),
            "",
            skill.instructions_md.strip(),
        ]

        inline_resources = [
            r for r in (skill.resources or [])
            if isinstance(r, dict) and r.get("content")
        ]
        for res in inline_resources:
            path = res.get("path") or "resource"
            parts.extend(["", f"## Resource: {path}", "", str(res.get("content", "")).strip()])

        ref_paths = [
            str(r.get("path"))
            for r in (skill.resources or [])
            if isinstance(r, dict) and r.get("path") and not r.get("content")
        ]
        if ref_paths:
            parts.extend(["", f"Additional resources (paths): {', '.join(ref_paths)}"])

        text = "\n".join(parts).strip()
        if len(text) > MAX_INSTRUCTION_CHARS:
            text = text[:MAX_INSTRUCTION_CHARS] + "\n\n[Skill content truncated]"
        return text

    @classmethod
    async def build_messages(
        cls,
        db: AsyncSession,
        skills_config: list[Any] | None,
    ) -> list[SystemMessage]:
        bindings = cls._binding_map(skills_config)
        skills = await cls.load_skills(db, skills_config)
        if not skills:
            return []

        def sort_key(skill: Skill) -> tuple[int, str]:
            binding = bindings.get(skill.id, {})
            priority = binding.get("priority", 0)
            if not isinstance(priority, int):
                priority = 0
            return (-priority, skill.display_name)

        skills.sort(key=sort_key)

        messages: list[SystemMessage] = []
        for skill in skills:
            binding = bindings.get(skill.id, {})
            always_load = binding.get("always_load", True)
            if always_load is False:
                continue
            body = cls._format_skill(skill)
            messages.append(SystemMessage(
                content=(
                    "Follow the skill instructions below when relevant to the user's task. "
                    "These are procedural guidelines (how to work), not optional suggestions.\n\n"
                    f"{body}"
                )
            ))
            logger.debug("skill_injected", skill_id=skill.id, slug=skill.slug)

        return messages


def merge_skill_bindings(
    primary: list[Any] | None,
    secondary: list[Any] | None,
) -> list[dict[str, Any]]:
    """Merge skill bindings; primary list order wins, dedupe by skill_id."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _append(item: Any) -> None:
        if isinstance(item, str):
            sid = item
            binding: dict[str, Any] = {"skill_id": sid, "always_load": True, "priority": 0}
        elif isinstance(item, dict) and item.get("skill_id"):
            sid = str(item["skill_id"])
            binding = dict(item)
            binding["skill_id"] = sid
        else:
            return
        if sid in seen:
            return
        seen.add(sid)
        merged.append(binding)

    for config in (primary, secondary):
        for item in config or []:
            _append(item)
    return merged


async def collect_knowledge_base_ids(
    db: AsyncSession,
    conv_kb_ids: list[str] | None,
    skills_config: list[Any] | None,
) -> list[str]:
    """Union conversation KB ids with those linked from bound skills."""
    ordered: list[str] = []
    seen: set[str] = set()
    for kid in conv_kb_ids or []:
        if kid and kid not in seen:
            seen.add(kid)
            ordered.append(kid)
    skills = await SkillInjector.load_skills(db, skills_config)
    for skill in skills:
        for kid in skill.knowledge_base_ids or []:
            if kid and kid not in seen:
                seen.add(kid)
                ordered.append(kid)
    return ordered
