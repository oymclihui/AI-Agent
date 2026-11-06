"""分析技能路由：问数链路加载分析技能（蓝图《分析能力前台化》P0）。

技能约定存 Skill.metadata_（不改表结构，创建/编辑走现有技能 API）：

    {
      "category": "analysis",             # 标识为分析技能
      "trigger": {                        # 命中条件（任一命中即生效；全空 = 绑定即生效）
        "question_types": ["L3"],         # 可选：回答模式（L3=分析类问题，按问题文本预判）
        "keywords": ["分析", "诊断"],      # 可选：问题包含任一关键词
        "regex": "为什么|原因"             # 可选：正则
      },
      "answer_style": {                   # 结论风格覆盖（替换 nl2sql.py 硬编码三件套）
        "persona": "你是资深经营分析师…",
        "format_mode": "L3",              # 可选：沿用内置排版（L1/L2/L3）
        "format_template": "…",           # 可选：自由 Markdown 排版模板（优先于 format_mode）
        "grounding_extra": "金额保留2位…"
      }
    }

匹配优先级：显式 skill_id > 数字员工规则匹配（priority 高者胜）> 技能示例相似度 > 无命中（None，走原硬编码，零改动兜底）。
红线：技能只影响「结论人设/排版/口径约束」，不参与 SQL 生成与治理链。
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DigitalEmployee, Skill

# 注入提示词的方法论文档上限（沿用 SkillInjector 的截断思想，防提示词膨胀）
_MAX_INSTRUCTIONS = 12000


def _is_active(skill: Skill) -> bool:
    status = getattr(skill.status, "value", skill.status)
    return str(status) == "active"


def _skill_ctx(skill: Skill) -> dict[str, Any]:
    meta = skill.metadata_ if isinstance(skill.metadata_, dict) else {}
    style = meta.get("answer_style") if isinstance(meta.get("answer_style"), dict) else {}
    steps = [s for s in (meta.get("steps") or []) if isinstance(s, dict)]
    return {
        "skill_id": skill.id,
        "slug": skill.slug,
        "display_name": skill.display_name,
        "version": skill.version or 1,
        "instructions_md": (skill.instructions_md or "")[:_MAX_INSTRUCTIONS],
        "answer_style": style,
        # 蓝图 P1-②：结构化步骤编排（非空时问数走算子编排，否则纯提示词技能）
        "steps": steps,
    }


def _question_matches_trigger(question: str, trigger: Any) -> bool:
    """trigger 任一条件命中即 True；未配置触发条件 = 绑定即生效。"""
    if not isinstance(trigger, dict):
        return True
    qtypes = [str(t) for t in (trigger.get("question_types") or [])]
    keywords = [str(k) for k in (trigger.get("keywords") or [])]
    pattern = str(trigger.get("regex") or "").strip()
    if not qtypes and not keywords and not pattern:
        return True

    text = question or ""
    if keywords and any(k and k in text for k in keywords):
        return True
    if pattern:
        try:
            if re.search(pattern, text):
                return True
        except re.error:
            pass
    if qtypes:
        if "any" in qtypes:
            return True
        if "L3" in qtypes:
            from app.core.data_ask.intelligence.answer_mode import analysis_keywords

            if any(k in text for k in analysis_keywords()):
                return True
    return False


async def match_analysis_skill(
    db: AsyncSession,
    *,
    question: str,
    employee_id: str | None = None,
    skill_id: str | None = None,
    data_source_id: str | None = None,
) -> dict[str, Any] | None:
    """问数入口调用：返回命中的分析技能上下文（skill_ctx），未命中返回 None。

    任何异常由调用方兜底（技能路由绝不阻塞问数主链路）。
    """
    # 1) 显式指定（对话里手动切换技能）：只要求 active
    if skill_id:
        skill = await db.get(Skill, skill_id)
        if skill and _is_active(skill):
            return _skill_ctx(skill)
        return None

    if not employee_id:
        return None

    # 2) 数字员工绑定技能：逐个检查 category=analysis + trigger 命中，priority 高者胜
    employee = await db.get(DigitalEmployee, employee_id)
    if not employee:
        return None
    config = employee.skills_config if isinstance(employee.skills_config, list) else []

    bound: list[tuple[int, Skill, bool]] = []
    for item in config:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("skill_id") or "").strip()
        if not sid:
            continue
        try:
            priority = int(item.get("priority") or 0)
        except (TypeError, ValueError):
            priority = 0
        skill = await db.get(Skill, sid)
        if not skill or not _is_active(skill):
            continue
        meta = skill.metadata_ if isinstance(skill.metadata_, dict) else {}
        if str(meta.get("category") or "") != "analysis":
            continue
        hit = _question_matches_trigger(question, meta.get("trigger"))
        bound.append((priority, skill, hit))

    # 2) 规则命中：priority 高者胜
    candidates = [(priority, skill) for priority, skill, hit in bound if hit]
    if candidates:
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return _skill_ctx(candidates[0][1])

    # 3) 示例检索（P1）：规则都未命中时，用技能记忆相似度裁决
    if bound:
        try:
            from app.core.data_ask.skill_memory import best_skill_by_examples

            winner = await best_skill_by_examples(
                db,
                question=question,
                skill_ids=[skill.id for _priority, skill, _hit in bound],
                data_source_id=data_source_id,
                priorities={skill.id: priority for priority, skill, _hit in bound},
            )
        except Exception:
            winner = None
        if winner:
            for _priority, skill, _hit in bound:
                if skill.id == winner:
                    return _skill_ctx(skill)
    from app.core.data_ask.blueprint_finish import match_trigger_skill, org_analysis_skills
    bound_skills = [skill for _priority, skill, _hit in bound]
    triggered = await match_trigger_skill(
        db, question=question, skills=bound_skills, data_source_id=data_source_id, floor=0.42,
    )
    if triggered:
        return _skill_ctx(triggered)
    extra = [
        skill for skill in await org_analysis_skills(db)
        if skill.id not in {item.id for item in bound_skills}
    ]
    triggered = await match_trigger_skill(
        db, question=question, skills=extra, data_source_id=data_source_id, floor=0.62,
    )
    if triggered:
        return _skill_ctx(triggered)
    return None


def skill_used_brief(skill_ctx: dict[str, Any] | None) -> dict[str, Any] | None:
    """响应/审计用的命中摘要（不带提示词正文）。"""
    if not skill_ctx:
        return None
    return {
        "skill_id": skill_ctx.get("skill_id"),
        "slug": skill_ctx.get("slug"),
        "display_name": skill_ctx.get("display_name"),
        "version": skill_ctx.get("version"),
    }
