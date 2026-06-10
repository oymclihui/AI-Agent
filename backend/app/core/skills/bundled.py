"""Bundled platform skills shipped with AI-AGENT (upsert on startup)."""
from __future__ import annotations

from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import generate_uuid
from app.db.models import Skill, SkillStatus
from app.core.skills.i18n import build_i18n_metadata, merge_skill_metadata_i18n

logger = structlog.get_logger(__name__)

BUNDLED_DIR = Path(__file__).with_name("bundled")

BUNDLED_SPECS: list[dict] = [
    {
        "slug": "data-qa-intent",
        "display_name": "数据问答意图识别",
        "description": (
            "识别 BI/数据类问题（KPI、趋势、归因、预测），推荐图表类型，"
            "并输出 [kpi]/[chart]/[choices] 结构化回复。适用于指标问答与数据分析数字员工。"
        ),
        "i18n": build_i18n_metadata(
            display_name_zh="数据问答意图识别",
            display_name_en="Data QA Intent",
            description_zh=(
                "识别 BI/数据类问题（KPI、趋势、归因、预测），推荐图表类型，"
                "并输出 [kpi]/[chart]/[choices] 结构化回复。适用于指标问答与数据分析数字员工。"
            ),
            description_en=(
                "Classifies BI/data questions (KPI, trend, attribution, forecast), "
                "suggests chart types, and formats structured [kpi]/[chart]/[choices] replies. "
                "Use for metrics Q&A and analytics digital employees."
            ),
        ),
        "tags": ["analytics", "data-qa", "intent", "smart-qa"],
        "auto_invoke": False,
        "file": "data-qa-intent.md",
    },
    {
        "slug": "huashu-design",
        "display_name": "花叔 Design（HTML 高保真设计）",
        "description": (
            "HTML 原生高保真原型、幻灯片、信息图与设计评审。"
            "含品牌资产协议、反 AI slop、设计方向顾问（三套逻辑）、40 种风格速查。"
            "改编自 huashu-design（MIT）。"
        ),
        "i18n": build_i18n_metadata(
            display_name_zh="花叔 Design（HTML 高保真设计）",
            display_name_en="Huashu Design (HTML Hi-Fi)",
            description_zh=(
                "HTML 原生高保真原型、幻灯片、信息图与设计评审。"
                "含品牌资产协议、反 AI slop、设计方向顾问与 5 维评审。"
            ),
            description_en=(
                "HTML-native hi-fi prototypes, slide decks, infographics, and design critique. "
                "Includes brand asset protocol, anti-AI-slop rules, design advisor, and 5-axis review."
            ),
        ),
        "tags": ["design", "html", "prototype", "slides", "huashu-design"],
        "auto_invoke": False,
        "file": "huashu-design.md",
        "resource_files": [
            {"path": "references/design-styles.md", "file": "huashu-design-styles.md"},
            {"path": "references/critique-guide.md", "file": "huashu-design-critique.md"},
        ],
        "metadata_extra": {
            "upstream": "https://github.com/alchaincyf/huashu-design",
            "upstream_license": "MIT",
        },
    },
    {
        "slug": "html2pptx",
        "display_name": "HTML 转可编辑 PPTX",
        "description": (
            "按 html2pptx 硬约束编写 960×540pt 幻灯片 HTML，"
            "导出可编辑 PowerPoint（需本地 Node + huashu-design 脚本）。"
        ),
        "i18n": build_i18n_metadata(
            display_name_zh="HTML 转可编辑 PPTX",
            display_name_en="HTML to Editable PPTX",
            description_zh=(
                "按 html2pptx 四条硬约束编写幻灯片 HTML，"
                "配合 pptxgenjs 导出可编辑 PPTX。"
            ),
            description_en=(
                "Write slide HTML under html2pptx constraints (960×540pt) "
                "for editable PowerPoint export via pptxgenjs."
            ),
        ),
        "tags": ["design", "pptx", "slides", "html2pptx", "huashu-design"],
        "auto_invoke": False,
        "file": "html2pptx.md",
        "metadata_extra": {
            "upstream": "https://github.com/alchaincyf/huashu-design",
            "upstream_ref": "references/editable-pptx.md",
            "upstream_license": "MIT",
        },
    },
    {
        "slug": "mailbox-assistant",
        "display_name": "企业邮箱助手",
        "description": (
            "通过 fetch_mail 工具读取用户已配置的 IMAP 邮箱，"
            "汇总最近邮件、提取待办并给出回复建议。需在设置中配置邮箱密码。"
        ),
        "i18n": build_i18n_metadata(
            display_name_zh="企业邮箱助手",
            display_name_en="Corporate Mailbox Assistant",
            description_zh=(
                "使用 fetch_mail 读取用户在设置中配置的 IMAP 邮箱，"
                "整理最近邮件摘要与行动建议。"
            ),
            description_en=(
                "Uses fetch_mail with the user's IMAP credentials from Settings "
                "to summarize recent emails and suggest actions."
            ),
        ),
        "tags": ["email", "imap", "mailbox", "byd"],
        "auto_invoke": False,
        "file": "mailbox-assistant.md",
    },
]

# i18n patches for skills seeded elsewhere (init_db templates)
I18N_PATCHES: dict[str, dict] = {
    "code-review": build_i18n_metadata(
        display_name_zh="代码审查",
        display_name_en="Code Review",
        description_zh="按团队规范审查代码质量、安全与可维护性。适用于 PR 审查或用户请求 code review。",
        description_en=(
            "Reviews code for quality, security, and maintainability following team standards. "
            "Use when reviewing pull requests, code changes, or when the user asks for a code review."
        ),
    ),
    "commit-message": build_i18n_metadata(
        display_name_zh="Git 提交信息",
        display_name_en="Git Commit Message",
        description_zh="分析 git diff 生成规范的 Conventional Commits 提交说明。",
        description_en=(
            "Generates descriptive commit messages by analyzing git diffs. "
            "Use when the user asks for help writing commit messages or reviewing staged changes."
        ),
    ),
}


def _read_instructions(filename: str) -> str:
    path = BUNDLED_DIR / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _load_resource_files(spec: dict) -> list[dict]:
    resources: list[dict] = []
    for item in spec.get("resource_files") or []:
        filename = item.get("file")
        if not filename:
            continue
        content = _read_instructions(filename)
        if not content:
            logger.warning("bundled_skill_resource_missing", slug=spec.get("slug"), file=filename)
            continue
        resources.append({
            "path": item.get("path") or filename,
            "kind": "markdown",
            "content": content,
        })
    return resources


def _bundled_metadata(spec: dict, i18n: dict) -> dict:
    base = {
        "bundled": True,
        "source": "ai-agent-bundled",
        **(spec.get("metadata_extra") or {}),
    }
    return merge_skill_metadata_i18n(base, i18n)


async def _apply_i18n_patches(session: AsyncSession) -> None:
    for slug, i18n in I18N_PATCHES.items():
        result = await session.execute(select(Skill).where(Skill.slug == slug).limit(1))
        skill = result.scalar_one_or_none()
        if not skill:
            continue
        skill.metadata_ = merge_skill_metadata_i18n(skill.metadata_, i18n)


async def ensure_bundled_skills(session: AsyncSession) -> list[str]:
    """Insert or refresh bundled skills by slug."""
    updated: list[str] = []
    for spec in BUNDLED_SPECS:
        instructions = _read_instructions(spec["file"])
        if not instructions:
            logger.warning("bundled_skill_missing_file", slug=spec["slug"], file=spec["file"])
            continue

        i18n = spec.get("i18n") or {}
        resources = _load_resource_files(spec)
        result = await session.execute(select(Skill).where(Skill.slug == spec["slug"]).limit(1))
        skill = result.scalar_one_or_none()
        if skill:
            skill.display_name = spec["display_name"]
            skill.description = spec["description"]
            skill.instructions_md = instructions
            skill.status = SkillStatus.active
            skill.tags = spec.get("tags") or []
            skill.auto_invoke = bool(spec.get("auto_invoke", False))
            skill.resources = resources
            skill.metadata_ = _bundled_metadata(spec, i18n)
        else:
            session.add(Skill(
                id=generate_uuid(),
                slug=spec["slug"],
                display_name=spec["display_name"],
                description=spec["description"],
                instructions_md=instructions,
                status=SkillStatus.active,
                scope="global",
                auto_invoke=bool(spec.get("auto_invoke", False)),
                tags=spec.get("tags") or [],
                resources=resources,
                metadata_= _bundled_metadata(spec, i18n),
            ))
        updated.append(spec["slug"])

    await _apply_i18n_patches(session)

    if updated:
        await session.commit()
        logger.info("bundled_skills_ensured", slugs=updated)
    else:
        await session.commit()
    return updated
