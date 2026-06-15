"""Agent display fields localization (name, role, goal, backstory)."""
from __future__ import annotations

from typing import Any

from app.core.skills.i18n import normalize_lang, pick_i18n_field
from app.db.models import Agent

_AGENT_FIELDS = ("name", "role", "goal", "backstory")


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def get_agent_i18n(agent: Agent) -> dict[str, Any]:
    meta = agent.metadata_ or {}
    return meta.get("i18n") if isinstance(meta.get("i18n"), dict) else {}


def build_agent_i18n_metadata(
    *,
    name_zh: str,
    name_en: str,
    role_zh: str,
    role_en: str,
    goal_zh: str,
    goal_en: str,
    backstory_zh: str = "",
    backstory_en: str = "",
) -> dict[str, Any]:
    block: dict[str, Any] = {
        "name": {"zh": name_zh, "en": name_en},
        "role": {"zh": role_zh, "en": role_en},
        "goal": {"zh": goal_zh, "en": goal_en},
    }
    if backstory_zh or backstory_en:
        block["backstory"] = {"zh": backstory_zh, "en": backstory_en}
    return block


def merge_agent_metadata_i18n(metadata: dict[str, Any] | None, i18n: dict[str, Any]) -> dict[str, Any]:
    base = dict(metadata or {})
    base["i18n"] = i18n
    return base


def _fallback_field(agent: Agent, field: str, lang: str) -> str:
    raw = str(getattr(agent, field, "") or "").strip()
    if not raw:
        return ""
    if lang == "zh":
        if _has_cjk(raw):
            return raw
        if field == "name" and _has_cjk(agent.role or ""):
            return agent.role
        if field == "role" and _has_cjk(agent.name or ""):
            return agent.name
        return raw
    # en
    if not _has_cjk(raw):
        return raw
    if field == "name" and not _has_cjk(agent.role or ""):
        return agent.role
    if field in ("goal", "backstory") and not _has_cjk(agent.role or ""):
        return agent.role
    return raw


def localize_agent_text(agent: Agent, lang: str | None) -> tuple[str, str, str, str]:
    code = normalize_lang(lang)
    i18n = get_agent_i18n(agent)
    if i18n:
        name = pick_i18n_field(i18n, "name", code, agent.name)
        role = pick_i18n_field(i18n, "role", code, agent.role)
        goal = pick_i18n_field(i18n, "goal", code, agent.goal)
        backstory = pick_i18n_field(i18n, "backstory", code, agent.backstory or "")
        return name, role, goal, backstory

    return tuple(_fallback_field(agent, f, code) for f in _AGENT_FIELDS)  # type: ignore[return-value]


def localize_catalog_agent(item: dict[str, Any], lang: str | None) -> dict[str, Any]:
    code = normalize_lang(lang)
    i18n = item.get("i18n") if isinstance(item.get("i18n"), dict) else {}
    name = pick_i18n_field(
        i18n,
        "name",
        code,
        item.get("name_zh") if code == "zh" else item.get("name_en") or item.get("name", ""),
    )
    if not name:
        name = item.get("name") or item.get("slug") or ""
    description = pick_i18n_field(
        i18n,
        "description",
        code,
        item.get("description_zh") if code == "zh" else item.get("description_en") or item.get("description", ""),
    )
    if not description:
        description = item.get("description") or name
    out = dict(item)
    out["name"] = name
    out["description"] = description
    return out


def apply_agent_name_update(agent: Agent, new_name: str) -> None:
    """Persist a user-edited display name on the agent row and i18n metadata."""
    from sqlalchemy.orm.attributes import flag_modified

    name = new_name.strip()
    if not name:
        return
    agent.name = name
    meta = dict(agent.metadata_ or {})
    i18n = dict(meta["i18n"]) if isinstance(meta.get("i18n"), dict) else {}
    i18n["name"] = {"zh": name, "en": name}
    meta["i18n"] = i18n
    agent.metadata_ = meta
    flag_modified(agent, "metadata_")


def agent_to_response_dict(agent: Agent, lang: str | None = None, *, localize: bool = True) -> dict[str, Any]:
    if localize:
        name, role, goal, backstory = localize_agent_text(agent, lang)
    else:
        name, role, goal, backstory = agent.name, agent.role, agent.goal, agent.backstory or ""

    return {
        "id": agent.id,
        "name": name,
        "role": role,
        "goal": goal,
        "backstory": backstory or None,
        "status": agent.status,
        "llm_provider": agent.llm_provider,
        "llm_model": agent.llm_model,
        "temperature": agent.temperature,
        "max_iterations": agent.max_iterations,
        "tools_config": agent.tools_config or [],
        "skills_config": agent.skills_config or [],
        "memory_config": agent.memory_config or {},
        "metadata": agent.metadata_ or {},
        "owner_id": agent.owner_id,
        "visibility": (
            agent.visibility
            if isinstance(agent.visibility, str)
            else (agent.visibility.value if agent.visibility else "private")
        ),
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
    }
