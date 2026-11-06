"""技能 YAML 导入导出（蓝图 P2，config as code）。

导出的文本是 YAML 1.2 兼容的 JSON。导入不拷贝知识库权限，新技能默认草稿，
避免把测试环境的权限带进生产。每次导入在 config_versions 留一版。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import generate_uuid
from app.db.models import ConfigVersion, Skill

_DOC_KEYS = (
    "kind", "slug", "display_name", "description", "instructions_md",
    "tags", "tools_required", "metadata",
)
# 这些字段即使出现在文件里也不生效，避免导入放大权限或直接上架。
_IGNORED_KEYS = {"knowledge_base_ids", "status", "id", "owner_id"}


def skill_document(skill: Skill) -> dict[str, Any]:
    meta = skill.metadata_ if isinstance(skill.metadata_, dict) else {}
    return {
        "kind": "analysis-skill",
        "slug": skill.slug,
        "display_name": skill.display_name,
        "description": skill.description or "",
        "instructions_md": skill.instructions_md or "",
        "tags": list(skill.tags or []),
        "tools_required": list(skill.tools_required or []),
        "metadata": meta,
    }


def dump_yaml(document: dict[str, Any]) -> str:
    try:
        import yaml
        return yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
    except Exception:
        return json.dumps(document, ensure_ascii=False, indent=2)


def load_yaml(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("YAML 为空")
    if raw[0] in "{[":
        data = json.loads(raw)
    else:
        import yaml
        data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError("技能文档必须是对象")
    for key in _IGNORED_KEYS:
        data.pop(key, None)
    unknown = [k for k in data.keys() if k not in _DOC_KEYS]
    if unknown:
        raise ValueError("不支持的字段：" + "、".join(unknown[:8]))
    if not str(data.get("display_name") or "").strip():
        raise ValueError("缺少 display_name")
    return data


async def next_config_version(db: AsyncSession, key: str) -> int:
    current = (await db.execute(
        select(func.max(ConfigVersion.version)).where(ConfigVersion.key == key)
    )).scalar()
    return int(current or 0) + 1


async def record_skill_version(
    db: AsyncSession,
    *,
    slug: str,
    document: dict[str, Any],
    actor: str,
    note: str,
) -> int:
    """只写入 config_versions，不改 SystemSetting（技能正文在 skills 表）。"""
    key = f"skill:{slug}"[:120]
    version = await next_config_version(db, key)
    db.add(ConfigVersion(
        id=generate_uuid(),
        key=key,
        version=version,
        value=document,
        actor=(actor or "")[:120] or None,
        note=(note or "")[:1000] or None,
    ))
    await db.flush()
    return version
