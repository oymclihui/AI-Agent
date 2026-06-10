"""Bilingual labels for Agency Agents (English source + Chinese UI copy)."""
from __future__ import annotations

from typing import Any

from app.core.agents.i18n import build_agent_i18n_metadata

DIVISION_ZH: dict[str, str] = {
    "engineering": "工程",
    "marketing": "营销",
    "design": "设计",
    "product": "产品",
    "security": "安全",
    "data": "数据",
    "research": "研究",
    "support": "支持",
    "legal": "法务",
    "finance": "财务",
    "hr": "人力资源",
    "operations": "运营",
    "sales": "销售",
    "community": "社区",
    "creative": "创意",
    "executive": "管理层",
    "specialized": "专项",
    "game-development": "游戏开发",
    "gis": "地理信息",
    "project-management": "项目管理",
}

TERM_ZH: dict[str, str] = {
    "ai": "AI",
    "api": "API",
    "app": "应用",
    "architect": "架构师",
    "architects": "架构师",
    "analyst": "分析师",
    "analytics": "分析",
    "automation": "自动化",
    "automator": "自动化专家",
    "backend": "后端",
    "builder": "构建师",
    "chief": "首席",
    "code": "代码",
    "commander": "指挥官",
    "consultant": "顾问",
    "content": "内容",
    "creator": "创作官",
    "curator": "策划",
    "cybersecurity": "网络安全",
    "data": "数据",
    "developer": "开发工程师",
    "devops": "DevOps",
    "engineer": "工程师",
    "engineering": "工程",
    "expert": "专家",
    "frontend": "前端",
    "full": "全栈",
    "growth": "增长",
    "hacker": "增长黑客",
    "intelligence": "情报",
    "manager": "经理",
    "marketing": "营销",
    "master": "大师",
    "mobile": "移动端",
    "ninja": "能手",
    "officer": "官",
    "optimization": "优化",
    "optimizer": "优化师",
    "product": "产品",
    "prompt": "提示词",
    "prototyper": "原型师",
    "reviewer": "审查员",
    "security": "安全",
    "senior": "资深",
    "seo": "SEO",
    "software": "软件",
    "specialist": "专家",
    "sre": "SRE",
    "strategist": "策略师",
    "technical": "技术",
    "writer": "文档工程师",
    "workflow": "工作流",
}


def _slug_tokens(slug: str) -> list[str]:
    base = slug.split("-", 1)[-1] if "-" in slug else slug
    return [t for t in base.split("-") if t]


def agency_name_zh(parsed: Any) -> str:
    tokens = _slug_tokens(parsed.slug)
    parts = [TERM_ZH.get(t, t) for t in tokens if t not in {parsed.division, "engineering", "marketing"}]
    label = "".join(parts) if parts else parsed.name
    div = DIVISION_ZH.get(parsed.division, parsed.division)
    if div and div not in label:
        return f"{div}{label}"
    return label[:255]


def agency_role_zh(parsed: Any) -> str:
    name_zh = agency_name_zh(parsed)
    div = DIVISION_ZH.get(parsed.division, "")
    if div and div in name_zh:
        return name_zh[:255]
    return f"{div}{name_zh}"[:255] if div else name_zh[:255]


def agency_goal_zh(parsed: Any) -> str:
    div = DIVISION_ZH.get(parsed.division, parsed.division)
    name_zh = agency_name_zh(parsed)
    en = (parsed.goal or parsed.description or "").strip()
    if en:
        return f"作为{name_zh}，在{div}领域完成专业交付与协作，遵循标准化工作流程。"
    return f"作为{name_zh}，负责{div}领域的专业交付与流程执行。"


def agency_backstory_zh(parsed: Any) -> str:
    return (
        f"Agency 角色库导入的{agency_name_zh(parsed)}，"
        f"具备完整人格、工作流程与交付物模板（{DIVISION_ZH.get(parsed.division, parsed.division)}）。"
    )


def build_agency_i18n(parsed: Any) -> dict:
    return build_agent_i18n_metadata(
        name_zh=agency_name_zh(parsed),
        name_en=parsed.name[:255],
        role_zh=agency_role_zh(parsed),
        role_en=parsed.role[:255],
        goal_zh=agency_goal_zh(parsed),
        goal_en=(parsed.goal or parsed.description)[:2000],
        backstory_zh=agency_backstory_zh(parsed),
        backstory_en=(parsed.backstory or parsed.description)[:48000],
    )


def build_merged_agency_i18n(en: Any, zh: Any) -> dict:
    """English persona from upstream + human Chinese from agency-agents-zh."""
    return build_agent_i18n_metadata(
        name_zh=zh.name[:255],
        name_en=en.name[:255],
        role_zh=(zh.role or zh.description or zh.name)[:255],
        role_en=en.role[:255],
        goal_zh=(zh.goal or zh.description)[:2000],
        goal_en=(en.goal or en.description)[:2000],
        backstory_zh=(zh.backstory or zh.description)[:48000],
        backstory_en=(en.backstory or en.description)[:48000],
    )


def build_zh_only_i18n(zh: Any) -> dict:
    """China-only agents that exist only in agency-agents-zh."""
    name_en = zh.slug.replace("-", " ").title()
    role_en = name_en[:255]
    goal_en = (zh.goal or zh.description or name_en)[:2000]
    return build_agent_i18n_metadata(
        name_zh=zh.name[:255],
        name_en=name_en[:255],
        role_zh=(zh.role or zh.description or zh.name)[:255],
        role_en=role_en,
        goal_zh=(zh.goal or zh.description)[:2000],
        goal_en=goal_en,
        backstory_zh=(zh.backstory or zh.description)[:48000],
        backstory_en=(zh.backstory or zh.description)[:48000],
    )
