"""Conversation deposit: suggest, draft preview, and confirmed publish to skill/KB/agent/employee."""
from __future__ import annotations

import json
from typing import Any, Literal, Optional

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm.exc import StaleDataError

from app.config import settings
from app.core.chat.export import (
    _format_transcript,
    materialize_knowledge_from_spec,
    materialize_skill_from_spec,
)
from app.core.employees.schedule import compute_next_run, validate_schedule
from app.db.base import generate_uuid
from app.db.models import (
    Agent as AgentModel,
    Conversation,
    DigitalEmployee,
    EmployeeScheduledTask,
    EmployeeStatus,
    EmployeeTaskType,
    Message,
    ScheduleType,
    Skill,
)

logger = structlog.get_logger(__name__)

DepositType = Literal["skill", "knowledge", "agent", "employee"]


def _set_conv_metadata(conv: Conversation, meta: dict[str, Any]) -> None:
    conv.metadata_ = meta
    flag_modified(conv, "metadata_")


def _get_deposit_draft(meta: dict[str, Any]) -> dict[str, Any] | None:
    draft = meta.get("deposit_draft")
    return draft if isinstance(draft, dict) and draft.get("draft_id") else None


def _append_skill_binding(conv: Conversation, skill_id: str) -> None:
    bindings = list(conv.skills_config or [])
    if any(isinstance(b, dict) and b.get("skill_id") == skill_id for b in bindings):
        return
    bindings.append({"skill_id": skill_id, "always_load": True, "priority": len(bindings)})
    conv.skills_config = bindings


def _append_kb_id(conv: Conversation, kb_id: str) -> None:
    ids = list(conv.knowledge_base_ids or [])
    if kb_id not in ids:
        ids.append(kb_id)
    conv.knowledge_base_ids = ids


def _merge_skill_id_lists(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for sid in group:
            if sid and sid not in seen:
                seen.add(sid)
                merged.append(sid)
    return merged


def _skill_ids_from_conv(conv: Conversation) -> list[str]:
    ids: list[str] = []
    for item in conv.skills_config or []:
        if isinstance(item, dict) and item.get("skill_id"):
            ids.append(str(item["skill_id"]))
        elif isinstance(item, str):
            ids.append(item)
    return ids


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None


async def _load_transcript(db: AsyncSession, conv_id: str) -> tuple[list[Message], str]:
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()
    return messages, _format_transcript(messages)


def _ensure_agent_spec(draft_body: dict[str, Any], conv: Conversation) -> dict[str, Any]:
    """Fill agent draft from employee / conversation when LLM omits the agent block."""
    agent = draft_body.get("agent") if isinstance(draft_body.get("agent"), dict) else {}
    if agent.get("name") and agent.get("role") and agent.get("goal"):
        return agent
    emp = draft_body.get("employee") if isinstance(draft_body.get("employee"), dict) else {}
    return {
        "name": agent.get("name") or emp.get("name") or conv.title or "对话智能体",
        "role": agent.get("role") or emp.get("title") or "Assistant",
        "goal": agent.get("goal") or emp.get("description") or conv.title or "协助完成对话中的工作任务",
        "backstory": agent.get("backstory") or emp.get("description") or "",
        "tools": agent.get("tools") or ["web_search", "datetime"],
        "temperature": float(agent.get("temperature", 0.7)),
    }


def _build_industry_domain_hints(transcript_lower: str) -> str:
    """Append industry-specific guidance for deposit draft generation."""
    hints: list[str] = []

    if any(
        k in transcript_lower
        for k in (
            "整车", "车企", "制造", "比亚迪", "oem", "总装", "车间", "产线",
            "cfo", "财务vp", "司库", "fp&a", "管报", "单车成本", "双积分",
        )
    ):
        hints.append("""
【行业上下文：制造业】
若对话涉及制造/车企/工厂，employee 草案应贴近真实岗位，例如：
- 生产运营：生产计划员（日排程）、车间主任助理（OEE/产能日报）、设备工程师（停机根因）
- 质量：IQC/PQC 工程师（来料/过程异常周报）、8D 跟踪员
- 集团财务：CFO（月报董事会）、财务 VP（周例会）、成本会计（单台/BOM/降本）、司库（资金/汇兑）
task_config.prompt 须含：多基地、班次、OEE、良率、BOM、出口汇兑等语境；
cron 建议：日监控 工作日 7:00、周例会 周一 8–10:00、月报 每月 3–5 日。
""")

    if any(
        k in transcript_lower
        for k in (
            "零售", "门店", "导购", "促销", "会员", "复购", "坪效", "连带率",
            "商超", "便利店", "连锁", "加盟", "巡店", "大促", "双11", "618",
        )
    ):
        hints.append("""
【行业上下文：零售业态】
employee 岗位示例：
- 门店：店长助理（日销售/客流复盘）、收银稽核（日结对账）
- 区域：督导（巡店周报、整改跟踪）、品类经理（滞销/补货/陈列）
- 会员运营：复购触达、券包 ROI 周报
task_config.prompt 须含：坪效、客单价、连带率、库存周转、促销 ROI、会员复购、SKU 动销；
cron 建议：日结 每日 22:00、巡店 每周五、品类 每周一 9:00。
""")

    if any(
        k in transcript_lower
        for k in (
            "物流", "仓配", "仓储", "配送", "在途", "wms", "tms", "供应链",
            "采购", "供应商", "到货", "履约", "库存周转",
        )
    ):
        hints.append("""
【行业上下文：物流与供应链】
employee 岗位示例：仓配调度员（日 KPI）、采购跟单（到货异常）、供应链计划（滚动补货）
task_config.prompt 须含：准时率、破损率、在途时效、安全库存、供应商 OTIF；
cron 建议：日 KPI 工作日 8:00、周报 周一 9:00。
""")

    if any(
        k in transcript_lower
        for k in ("餐饮", "后厨", "食安", "消杀", "外卖", "翻台", "备餐")
    ):
        hints.append("""
【行业上下文：餐饮服务】
employee 岗位示例：门店值班经理（日营业复盘）、食安巡检员（消杀/台账）、外卖履约专员
task_config.prompt 须含：营业额、客诉、食安台账、原料损耗、外卖准时率；
cron 建议：日结 每日 23:00、食安巡检 每日 10:00 与 16:00。
""")

    if any(
        k in transcript_lower
        for k in (
            "银行", "保险", "信贷", "风控", "理财", "网点", "金融", "aum",
            "不良", "贷后", "柜面", "反洗钱", "aml", "信用卡", "个贷",
        )
    ):
        hints.append("""
【行业上下文：银行与金融服务】
employee 岗位示例：
- 网点：网点运营助理（日业绩/客流/等候时长）、柜面合规抽检（双录/身份核验）
- 风控：贷后预警专员（异常交易/逾期周报）、反洗钱可疑交易初筛
- 财富：理财经理助理（客户分层触达、AUM 变动提醒、产品到期跟进）
task_config.prompt 须含：存款/贷款/理财/AUM、不良率、合规检查项、VIP 客户触达；
cron 建议：网点日结 工作日 18:00、风控周报 周一 9:00、贷后巡检 工作日 8:30。
""")

    if any(
        k in transcript_lower
        for k in (
            "医疗", "医院", "诊所", "随访", "患者", "门诊", "住院", "护理",
            "处方", "医保", "drg", "病案", "慢病", "体检",
        )
    ):
        hints.append("""
【行业上下文：医疗健康】
employee 岗位示例：
- 临床运营：出院随访专员（7天/30天随访清单）、门诊预约提醒
- 质控：病案质控助理（编码/DRG 完整性抽检周报）
- 健康管理：慢病管理助手（血压/血糖异常患者触达）
task_config.prompt 须含：科室、患者分层、随访节点、未接通重试、医保/自费口径；
cron 建议：随访提醒 工作日 9:00、质控周报 周五 17:00、预约提醒 每日 8:00。
""")

    if any(
        k in transcript_lower
        for k in (
            "教育", "学校", "培训", "教务", "学情", "续费", "到课", "退课",
            "k12", "高校", "招生", "排课", "教师", "学员", "教培",
        )
    ):
        hints.append("""
【行业上下文：教育与教培】
employee 岗位示例：
- 教务：学情周报助手（到课/完课/作业提交）、排课冲突检查
- 运营：续费预警专员（到期前 30/14/7 天触达）、退课原因汇总
- 招生：线索跟进助理（试听转化、渠道 ROI 周报）
task_config.prompt 须含：校区/班级/科目、到课率、续费率、退费率、教师课时、渠道转化；
cron 建议：学情周报 周日 20:00、续费提醒 工作日 10:00、招生日报 工作日 18:00。
""")

    if any(
        k in transcript_lower
        for k in ("sidecar", "桌面", "录制", "回放", "sap gui", "openadapt", "desktop", "gui")
    ):
        hints.append("""
【桌面自动化上下文】
若对话涉及桌面 GUI 录制/回放/SAP/Excel 桌面操作：
- 推荐 skill（GUI 操作 SOP）+ knowledge（演示步骤文档）
- agent 工具应含 desktop_list_demos, desktop_replay, desktop_capture
- employee 任务可用 task_type: "desktop_automation"，task_config 示例：
  {"demo_name": "演示名称", "instructions": "可选补充说明", "timeout_s": 120}
- 需提醒用户在本机运行 scripts/desktop_sidecar.py
""")

    return "\n".join(hints)


async def analyze_conversation_deposit(
    db: AsyncSession,
    conv: Conversation,
    user_id: str,
    *,
    lang: str = "zh",
) -> dict[str, Any]:
    """Analyze transcript and store a deposit draft on the conversation metadata."""
    from app.core.chat.llm_context import get_llm_for_conversation

    messages, transcript = await _load_transcript(db, conv.id)
    if len(messages) < 2:
        return {"worth_deposit": False, "suggestions": [], "draft_id": None, "draft": None}

    llm = await get_llm_for_conversation(db, conv, user_id, temperature=0.2)
    lang_hint = "中文" if lang == "zh" else "English"
    system = (
        "你是企业 AI 上岗顾问。根据对话判断用户是否完成了可复用的工作（SOP、知识、岗位、定时任务）。"
        "只输出 JSON，不要 Markdown。"
    )
    transcript_lower = transcript.lower()
    domain_hint = _build_industry_domain_hints(transcript_lower)
    user_prompt = f"""分析以下对话，判断值得沉淀的内容。输出语言：{lang_hint}。
{domain_hint}
对话记录：
{transcript[:80000]}

JSON schema:
{{
  "worth_deposit": true/false,
  "suggestions": [
    {{
      "type": "skill|knowledge|agent|employee",
      "recommended": true/false,
      "title": "简短标题",
      "reason": "推荐理由（一句话）",
      "confidence": 0.0-1.0
    }}
  ],
    "draft": {{
    "skill": {{"display_name": "...", "description": "...", "instructions_md": "完整 SOP Markdown"}},
    "knowledge": {{"kb_name": "...", "summary": "...", "document_md": "完整知识 Markdown"}},
    "agent": {{
      "name": "中文名",
      "role": "English role",
      "goal": "中文目标",
      "backstory": "中文背景",
      "tools": ["web_search", "fetch_mail"],
      "temperature": 0.7
    }},
    "employee": {{
      "name": "员工名",
      "title": "岗位",
      "description": "职责描述",
      "timezone": "Asia/Shanghai",
      "tasks": [
        {{
          "name": "任务名",
          "schedule_type": "cron",
          "cron_expression": "0 9 * * 1",
          "schedule_label": "每周一 09:00",
          "task_type": "agent|desktop_automation",
          "task_config": {{"prompt": "定时执行的完整指令"}} 或 {{"demo_name": "...", "instructions": "..."}}
        }}
      ]
    }}
  }}
}}

规则：
- 若对话只是一次性简单问答，worth_deposit=false，suggestions 为空。
- 若出现重复性工作、岗位描述、周报/日报、定时需求，推荐 employee 并给出合理 cron（工作日 9:00 等）。
- employee 的 task_config.prompt 必须可独立执行（agent 任务）；desktop_automation 任务用 demo_name/demo_id。
- cron_expression 使用标准 5 段 cron（分 时 日 月 周）。
- skill.instructions_md 与 knowledge.document_md 必须可直接发布，无需二次生成。
"""
    response = await llm.ainvoke([
        SystemMessage(content=system),
        HumanMessage(content=user_prompt),
    ])
    spec = _extract_json(response.content or "") or {}
    worth = bool(spec.get("worth_deposit"))
    suggestions = spec.get("suggestions") if isinstance(spec.get("suggestions"), list) else []
    draft_body = spec.get("draft") if isinstance(spec.get("draft"), dict) else {}

    ds_id = (conv.metadata_ or {}).get("data_source_id")
    if ds_id:
        suggestions.append({
            "type": "employee",
            "title": "沉淀为问数数字员工",
            "summary": "基于问数数据源创建定时报告数字员工（DataAsk）",
            "confidence": 0.9,
        })
        worth = True

    if not worth or not suggestions:
        # Do not clear an existing draft — a follow-up message may re-analyze as
        # "not worth depositing" while the user still has the panel open.
        existing = _get_deposit_draft(conv.metadata_ or {})
        if existing:
            draft_body = existing.get("draft") if isinstance(existing.get("draft"), dict) else {}
            emp = draft_body.get("employee") if isinstance(draft_body.get("employee"), dict) else {}
            skill = draft_body.get("skill") if isinstance(draft_body.get("skill"), dict) else {}
            kb = draft_body.get("knowledge") if isinstance(draft_body.get("knowledge"), dict) else {}
            agent = draft_body.get("agent") if isinstance(draft_body.get("agent"), dict) else {}
            tasks_preview = []
            for t in emp.get("tasks") or []:
                if isinstance(t, dict):
                    prompt = (t.get("task_config") or {}).get("prompt", "")
                    tasks_preview.append({
                        "name": t.get("name", ""),
                        "schedule_type": t.get("schedule_type", "cron"),
                        "cron_expression": t.get("cron_expression"),
                        "schedule_label": t.get("schedule_label"),
                        "prompt_preview": (prompt[:200] + "…") if len(prompt) > 200 else prompt,
                    })
            return {
                "worth_deposit": True,
                "draft_id": existing.get("draft_id"),
                "suggestions": existing.get("suggestions") or [],
                "draft": {
                    "skill_title": skill.get("display_name"),
                    "knowledge_title": kb.get("kb_name"),
                    "agent_name": agent.get("name"),
                    "employee_name": emp.get("name"),
                    "employee_title": emp.get("title"),
                    "employee_description": emp.get("description"),
                    "tasks": tasks_preview,
                },
            }
        return {"worth_deposit": False, "suggestions": [], "draft_id": None, "draft": None}

    suggestion_types = {
        str(s.get("type"))
        for s in suggestions
        if isinstance(s, dict) and s.get("type")
    }
    if suggestion_types & {"employee", "agent"}:
        draft_body["agent"] = _ensure_agent_spec(draft_body, conv)

    draft_id = generate_uuid()
    draft_record = {
        "draft_id": draft_id,
        "lang": lang,
        "suggestions": suggestions,
        "draft": draft_body,
        "source_conversation_id": conv.id,
    }
    meta = dict(conv.metadata_ or {})
    meta["deposit_draft"] = draft_record
    _set_conv_metadata(conv, meta)
    try:
        await db.flush()
    except StaleDataError as exc:
        raise ValueError("对话已被删除或清空，无法保存沉淀结果。请重新打开对话后再分析。") from exc

    tasks_preview = []
    emp = draft_body.get("employee") if isinstance(draft_body.get("employee"), dict) else {}
    for t in emp.get("tasks") or []:
        if isinstance(t, dict):
            prompt = (t.get("task_config") or {}).get("prompt", "")
            tasks_preview.append({
                "name": t.get("name", ""),
                "schedule_type": t.get("schedule_type", "cron"),
                "cron_expression": t.get("cron_expression"),
                "schedule_label": t.get("schedule_label"),
                "prompt_preview": (prompt[:200] + "…") if len(prompt) > 200 else prompt,
            })

    skill = draft_body.get("skill") if isinstance(draft_body.get("skill"), dict) else {}
    kb = draft_body.get("knowledge") if isinstance(draft_body.get("knowledge"), dict) else {}
    agent = draft_body.get("agent") if isinstance(draft_body.get("agent"), dict) else {}

    return {
        "worth_deposit": True,
        "draft_id": draft_id,
        "suggestions": suggestions,
        "draft": {
            "skill_title": skill.get("display_name"),
            "knowledge_title": kb.get("kb_name"),
            "agent_name": agent.get("name"),
            "employee_name": emp.get("name"),
            "employee_title": emp.get("title"),
            "employee_description": emp.get("description"),
            "tasks": tasks_preview,
        },
    }


async def _create_agent_from_draft(
    db: AsyncSession,
    conv: Conversation,
    user_id: str,
    agent_spec: dict[str, Any],
    skill_ids: list[str],
) -> AgentModel:
    tools_config = [{"tool_name": t} for t in agent_spec.get("tools", []) if isinstance(t, str)]
    skills_config = [{"skill_id": sid, "always_load": True, "priority": i} for i, sid in enumerate(skill_ids)]
    agent = AgentModel(
        id=generate_uuid(),
        owner_id=user_id,
        name=str(agent_spec.get("name") or "对话智能体")[:255],
        role=str(agent_spec.get("role") or "Assistant")[:255],
        goal=str(agent_spec.get("goal") or conv.title or "协助用户完成对话中的任务")[:2000],
        backstory=str(agent_spec.get("backstory") or "")[:4000],
        llm_provider=settings.DEFAULT_LLM_PROVIDER,
        llm_model=settings.DEFAULT_LLM_MODEL,
        temperature=float(agent_spec.get("temperature", 0.7)),
        max_iterations=10,
        tools_config=tools_config,
        skills_config=skills_config,
        memory_config={},
        metadata_={"source_conversation_id": conv.id, "from_deposit": True},
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return agent


async def _create_employee_from_draft(
    db: AsyncSession,
    conv: Conversation,
    user_id: str,
    emp_spec: dict[str, Any],
    agent_id: str,
    skill_ids: list[str],
    *,
    knowledge_base_ids: list[str] | None = None,
    activate: bool = True,
) -> tuple[DigitalEmployee, int]:
    from app.db.models import User as UserModel

    owner = await db.get(UserModel, user_id)
    skills_config = [{"skill_id": sid, "always_load": True, "priority": i} for i, sid in enumerate(skill_ids)]
    emp = DigitalEmployee(
        id=generate_uuid(),
        owner_id=user_id,
        department_id=owner.primary_department_id if owner else None,
        name=str(emp_spec.get("name") or "对话数字员工")[:255],
        title=(emp_spec.get("title") or None),
        description=emp_spec.get("description"),
        status=EmployeeStatus.active if activate else EmployeeStatus.paused,
        agent_id=agent_id,
        skills_config=skills_config,
        knowledge_base_ids=knowledge_base_ids or list(conv.knowledge_base_ids or []),
        timezone=str(emp_spec.get("timezone") or "Asia/Shanghai"),
        metadata_={
            "source_conversation_id": conv.id,
            "from_deposit": True,
            "draft_until_confirm": not activate,
        },
    )
    db.add(emp)
    await db.flush()

    tasks_created = 0
    for raw_task in emp_spec.get("tasks") or []:
        if not isinstance(raw_task, dict):
            continue
        st = str(raw_task.get("schedule_type") or "cron")
        cron = raw_task.get("cron_expression")
        interval = raw_task.get("interval_seconds")
        raw_type = str(raw_task.get("task_type") or "agent")
        try:
            task_type = EmployeeTaskType(raw_type)
        except ValueError:
            task_type = EmployeeTaskType.agent
        try:
            validate_schedule(st, cron, interval)
        except ValueError as exc:
            logger.warning("deposit_task_schedule_invalid", name=raw_task.get("name"), error=str(exc))
            continue
        task = EmployeeScheduledTask(
            id=generate_uuid(),
            employee_id=emp.id,
            name=str(raw_task.get("name") or "定时任务")[:255],
            description=raw_task.get("description"),
            enabled=activate,
            schedule_type=ScheduleType.cron if st == "cron" else ScheduleType.interval,
            cron_expression=cron,
            interval_seconds=interval,
            timezone=str(emp_spec.get("timezone") or "Asia/Shanghai"),
            task_type=task_type,
            task_config=raw_task.get("task_config") if isinstance(raw_task.get("task_config"), dict) else {},
            metadata_={"source_conversation_id": conv.id},
        )
        if task.enabled:
            task.next_run_at = compute_next_run(
                st,
                cron_expression=task.cron_expression,
                interval_seconds=task.interval_seconds,
                timezone_name=task.timezone,
            )
        db.add(task)
        tasks_created += 1

    await db.flush()
    await db.refresh(emp)
    return emp, tasks_created


async def confirm_conversation_deposit(
    db: AsyncSession,
    conv: Conversation,
    user_id: str,
    *,
    draft_id: str,
    types: list[DepositType],
    activate_employee: bool = True,
    kb_id: Optional[str] = None,
    kb_name: Optional[str] = None,
    skill_title: Optional[str] = None,
) -> dict[str, Any]:
    meta = conv.metadata_ or {}
    draft_record = _get_deposit_draft(meta)
    if not draft_record:
        raise ValueError("Deposit draft not found or expired. Run suggest-deposit again.")

    stored_id = str(draft_record.get("draft_id") or "")
    if stored_id and stored_id != draft_id:
        logger.warning(
            "deposit_draft_id_mismatch",
            client_draft_id=draft_id,
            stored_draft_id=stored_id,
            conversation_id=conv.id,
        )
        draft_id = stored_id
    elif not stored_id:
        raise ValueError("Deposit draft not found or expired. Run suggest-deposit again.")

    draft_body = draft_record.get("draft") if isinstance(draft_record.get("draft"), dict) else {}
    selected = set(types)
    if "employee" in selected and "agent" not in selected:
        selected.add("agent")

    result: dict[str, Any] = {
        "skill_id": None,
        "knowledge_base_id": None,
        "agent_id": None,
        "employee_id": None,
        "tasks_created": 0,
    }
    skill_ids: list[str] = []
    kb_id_result: str | None = None

    if "skill" in selected:
        skill_spec = draft_body.get("skill") if isinstance(draft_body.get("skill"), dict) else {}
        title = skill_title or skill_spec.get("display_name") or conv.title or "对话技能"
        skill = await materialize_skill_from_spec(
            db, conv, user_id, skill_spec, title=title,
        )
        result["skill_id"] = skill.id
        skill_ids.append(skill.id)
        _append_skill_binding(conv, skill.id)

    if "knowledge" in selected:
        kb_spec = draft_body.get("knowledge") if isinstance(draft_body.get("knowledge"), dict) else {}
        kb, _doc = await materialize_knowledge_from_spec(
            db,
            conv,
            user_id,
            kb_spec,
            kb_id=kb_id,
            kb_name=kb_name or kb_spec.get("kb_name"),
        )
        result["knowledge_base_id"] = kb.id
        kb_id_result = kb.id
        _append_kb_id(conv, kb.id)
        if result["skill_id"]:
            skill = await db.get(Skill, result["skill_id"])
            if skill:
                linked = list(skill.knowledge_base_ids or [])
                if kb.id not in linked:
                    linked.append(kb.id)
                skill.knowledge_base_ids = linked
                await db.flush()

    all_skill_ids = _merge_skill_id_lists(skill_ids, _skill_ids_from_conv(conv))

    agent_id: str | None = conv.agent_id
    if "agent" in selected:
        agent_spec = _ensure_agent_spec(draft_body, conv)
        agent = await _create_agent_from_draft(db, conv, user_id, agent_spec, all_skill_ids)
        agent_id = agent.id
        result["agent_id"] = agent.id
        conv.agent_id = agent.id

    effective_kb_ids = list(conv.knowledge_base_ids or [])

    if "employee" in selected:
        if not agent_id:
            raise ValueError("Cannot create employee without an agent")
        emp_spec = draft_body.get("employee") if isinstance(draft_body.get("employee"), dict) else {}
        if not emp_spec:
            raise ValueError("Employee draft missing from deposit preview")
        emp, task_count = await _create_employee_from_draft(
            db,
            conv,
            user_id,
            emp_spec,
            agent_id,
            all_skill_ids,
            knowledge_base_ids=effective_kb_ids,
            activate=activate_employee,
        )
        result["employee_id"] = emp.id
        result["tasks_created"] = task_count

    meta = dict(conv.metadata_ or {})
    meta.pop("deposit_draft", None)
    meta["last_deposit"] = {
        "draft_id": draft_id,
        "types": list(selected),
        "result": {k: v for k, v in result.items() if v is not None},
    }
    _set_conv_metadata(conv, meta)
    try:
        await db.flush()
    except StaleDataError as exc:
        raise ValueError("对话已被删除或清空，无法保存沉淀结果。请重新打开对话后再确认。") from exc
    return result
