"""Skill display name / description localization."""
from __future__ import annotations

from typing import Any

from app.db.models import Skill


def normalize_lang(lang: str | None) -> str:
    if not lang or lang.lower() in {"source", "raw", "default"}:
        return "zh"
    code = lang.lower().split("-")[0]
    return "en" if code == "en" else "zh"


def pick_i18n_field(i18n: dict[str, Any] | None, field: str, lang: str, fallback: str) -> str:
    if not i18n or field not in i18n:
        return fallback
    block = i18n[field]
    if isinstance(block, str):
        return block or fallback
    if isinstance(block, dict):
        other = "en" if lang == "zh" else "zh"
        return (
            (block.get(lang) or "").strip()
            or (block.get(other) or "").strip()
            or fallback
        )
    return fallback


def get_skill_i18n(skill: Skill) -> dict[str, Any]:
    meta = skill.metadata_ or {}
    return meta.get("i18n") if isinstance(meta.get("i18n"), dict) else {}


def localize_skill_instructions(skill: Skill, lang: str | None) -> str:
    code = normalize_lang(lang)
    meta = skill.metadata_ or {}
    block = meta.get("instructions_i18n")
    if isinstance(block, dict):
        other = "en" if code == "zh" else "zh"
        return (
            (block.get(code) or "").strip()
            or (block.get(other) or "").strip()
            or skill.instructions_md
        )
    return skill.instructions_md


def localize_skill_text(skill: Skill, lang: str | None) -> tuple[str, str]:
    code = normalize_lang(lang)
    i18n = get_skill_i18n(skill)
    display_name = pick_i18n_field(i18n, "display_name", code, skill.display_name)
    description = pick_i18n_field(i18n, "description", code, skill.description)
    return display_name, description


def build_i18n_metadata(
    *,
    display_name_zh: str,
    display_name_en: str,
    description_zh: str,
    description_en: str,
) -> dict[str, Any]:
    return {
        "display_name": {"zh": display_name_zh, "en": display_name_en},
        "description": {"zh": description_zh, "en": description_en},
    }


def merge_skill_metadata_i18n(metadata: dict[str, Any] | None, i18n: dict[str, Any]) -> dict[str, Any]:
    base = dict(metadata or {})
    base["i18n"] = i18n
    return base


def localize_catalog_template(item: dict[str, Any], lang: str | None) -> dict[str, Any]:
    """Return catalog row with localized display_name / description."""
    code = normalize_lang(lang)
    i18n = item.get("i18n") if isinstance(item.get("i18n"), dict) else {}
    display_name = pick_i18n_field(
        i18n,
        "display_name",
        code,
        item.get("display_name_zh") if code == "zh" else item.get("display_name_en") or item.get("display_name", ""),
    )
    if not display_name:
        display_name = item.get("display_name") or item.get("slug") or ""
    description = pick_i18n_field(i18n, "description", code, item.get("description") or "")
    out = dict(item)
    out["display_name"] = display_name
    out["description"] = description
    return out


def skill_to_response_dict(skill: Skill, lang: str | None = None, *, localize: bool = True) -> dict[str, Any]:
    if localize:
        display_name, description = localize_skill_text(skill, lang)
        instructions_md = localize_skill_instructions(skill, lang)
    else:
        display_name, description = skill.display_name, skill.description
        instructions_md = skill.instructions_md
    return {
        "id": skill.id,
        "slug": skill.slug,
        "display_name": display_name,
        "description": description,
        "instructions_md": instructions_md,
        "status": skill.status,
        "scope": skill.scope,
        "auto_invoke": skill.auto_invoke,
        "version": skill.version,
        "resources": skill.resources or [],
        "tools_required": skill.tools_required or [],
        "knowledge_base_ids": skill.knowledge_base_ids or [],
        "tags": skill.tags or [],
        "metadata": skill.metadata_ or {},
        "created_at": skill.created_at,
        "updated_at": skill.updated_at,
    }
