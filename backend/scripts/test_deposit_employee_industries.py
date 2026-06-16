#!/usr/bin/env python3
"""Multi-industry E2E: chat dialogue -> suggest-deposit -> digital employee.

Usage:
  cd backend
  set SMOKE_BASE_URL=http://127.0.0.1:8001
  python scripts/test_deposit_employee_industries.py           # live chat (default)
  python scripts/test_deposit_employee_industries.py --seed    # seed transcript, skip chat LLM
  python scripts/test_deposit_employee_industries.py --industry retail_store
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from typing import Any

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BASE = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
API = f"{BASE}/api/v1"

INDUSTRIES: list[dict[str, Any]] = [
    {
        "id": "mfg_production",
        "name": "制造业·生产运营",
        "title": "总装车间 OEE 数字员工",
        "user_messages": [
            (
                "我们是一家新能源汽车总装厂，有 3 条产线、两班倒。"
                "我想创建一个「车间生产分析助理」数字员工：每个工作日早上 7:00 自动汇总昨日 OEE、"
                "计划达成率、停机 TOP3 原因，并给出班次交接要点。岗位要能看懂 MES 口径的产能与良率。"
            ),
            (
                "补充：cron 用工作日 7:00；任务 prompt 里要写清产线编号、班次、"
                "OEE=可用率×性能×质量，并提醒异常停机要关联设备工程师跟进。"
            ),
        ],
        "assistant_replies": [
            (
                "已理解：为总装车间设计「生产分析助理」，聚焦 OEE 与停机根因。"
                "建议绑定 web_search 与 calculator，定时任务 cron 为工作日 7:00，"
                "输出含产线/班次/计划达成/停机 TOP3 的结构化日报。"
            ),
            (
                "好的，将在 task_config.prompt 中明确 OEE 公式、产线编号、班次交接，"
                "并建议异常停机创建跟进项。可沉淀为 skill（OEE 日报 SOP）+ agent + employee。"
            ),
        ],
    },
    {
        "id": "mfg_quality",
        "name": "制造业·质量管理",
        "title": "IQC 来料异常周报",
        "user_messages": [
            (
                "我们是电子制造 OEM，来料检验 IQC 每周要出异常周报给采购和 SQE。"
                "请设计数字员工「IQC 周报助手」：每周一 9:00 汇总上周来料批次、不合格率、"
                "TOP 供应商与重复缺陷，并输出 8D 跟踪建议。"
            ),
        ],
        "assistant_replies": [
            (
                "建议创建 IQC 周报数字员工：agent 角色为质量工程师，"
                "employee 任务 cron 0 9 * * 1，prompt 含批次合格率、供应商排名、重复缺陷与 8D 建议。"
            ),
        ],
    },
    {
        "id": "retail_store",
        "name": "零售业·线下门店",
        "title": "门店日销售复盘",
        "user_messages": [
            (
                "我们是连锁商超，200+ 门店。想做一个「店长日结助手」数字员工："
                "每天 22:00 自动生成当日销售额、客流、坪效、连带率、TOP10 SKU、"
                "库存预警 SKU，并对比上周同日。"
            ),
            (
                "还要包含会员复购与当日促销活动 ROI 一句话点评；"
                "若坪效低于区域均值要标红提醒。"
            ),
        ],
        "assistant_replies": [
            (
                "门店日结助手方案：employee 每日 22:00 cron，prompt 覆盖销售/客流/坪效/连带率/"
                "TOP SKU/库存预警/促销 ROI/会员复购，并与区域均值对比。"
            ),
            (
                "将在输出模板中加入坪效低于区域均值的标红规则与促销 ROI 点评段落。"
            ),
        ],
    },
    {
        "id": "retail_franchise",
        "name": "零售业·加盟巡店",
        "title": "区域督导巡店周报",
        "user_messages": [
            (
                "我们是奶茶加盟品牌，区域督导每周巡店 8-12 家。"
                "需要「巡店督导助手」：每周五 18:00 汇总本周巡店评分、食安/陈列/服务扣分项、"
                "加盟商整改清单与下周重点门店。"
            ),
        ],
        "assistant_replies": [
            (
                "巡店督导助手：每周五 18:00 cron，prompt 含巡店评分、扣分维度、整改清单、"
                "下周重点门店；可沉淀巡店 SOP 技能与知识库（检查表）。"
            ),
        ],
    },
    {
        "id": "logistics",
        "name": "物流供应链",
        "title": "仓配 KPI 周报",
        "user_messages": [
            (
                "我们是 3PL 物流，全国 12 个 RDC。请设计「仓配 KPI 助手」数字员工："
                "每周一 8:30 汇总各仓准时发货率、破损率、库存准确率、"
                "在途超时单量，并给出承运商 OTIF 排名与改善建议。"
            ),
        ],
        "assistant_replies": [
            (
                "仓配 KPI 助手：周一 8:30 cron，覆盖 RDC 维度 KPI、承运商 OTIF、"
                "在途超时与改善建议；agent 需理解 WMS/TMS 口径。"
            ),
        ],
    },
    {
        "id": "fnb",
        "name": "餐饮服务",
        "title": "门店食安巡检",
        "user_messages": [
            (
                "我们是中式快餐连锁 150 店。需要「食安巡检员」数字员工："
                "每天 10:00 和 16:00 各执行一次，提醒门店完成消杀台账、"
                "原料保质期抽检、后厨温度记录，并汇总未提交门店清单。"
            ),
        ],
        "assistant_replies": [
            (
                "食安巡检员：两次日 cron（10:00/16:00），prompt 含消杀/保质期/温度台账，"
                "输出未提交门店清单；建议绑定 checklist 类 skill。"
            ),
        ],
    },
    {
        "id": "bank_branch",
        "name": "银行业·网点运营",
        "title": "网点日业绩复盘",
        "user_messages": [
            (
                "我们是城商行，120 家网点。需要「网点运营日结助手」数字员工："
                "每个工作日 18:00 汇总当日存款/贷款/理财销售、AUM 变动、"
                "柜面等候时长 TOP3 网点、双录合规抽检未通过笔数，并对比昨日与上月同日。"
            ),
            (
                "输出要按支行→网点层级；理财到期客户需单独列出触达清单；"
                "若某网点不良率环比上升要标红。"
            ),
        ],
        "assistant_replies": [
            (
                "网点运营日结助手：工作日 18:00 cron，prompt 覆盖存贷理财/AUM/等候时长/"
                "双录合规/支行网点层级对比；含理财到期触达清单。"
            ),
            (
                "将加入不良率环比上升标红规则，并按支行-网点结构输出。"
            ),
        ],
    },
    {
        "id": "bank_risk",
        "name": "银行业·贷后风控",
        "title": "贷后预警周报",
        "user_messages": [
            (
                "我们是股份制银行零售信贷部。请设计「贷后预警助手」："
                "每周一 8:30 汇总上周新增逾期、M1/M2 迁徙、"
                "异常还款行为 TOP 客户、反洗钱可疑交易初筛命中量，"
                "并给出客户经理跟进优先级建议。"
            ),
        ],
        "assistant_replies": [
            (
                "贷后预警助手：周一 8:30 cron，prompt 含逾期/M1M2/异常还款/AML 命中/"
                "客户经理优先级；agent 角色为贷后风控专员。"
            ),
        ],
    },
    {
        "id": "healthcare_followup",
        "name": "医疗·出院随访",
        "title": "慢病出院随访助手",
        "user_messages": [
            (
                "我们是三甲综合医院随访中心，重点慢病：心内、内分泌、肿瘤术后。"
                "需要「出院随访助手」数字员工：每个工作日 9:00 生成当日随访清单，"
                "包含出院 7 天/30 天节点患者、未接通需二次拨打名单、"
                "按科室汇总随访完成率，并提醒护士记录随访结果。"
            ),
        ],
        "assistant_replies": [
            (
                "出院随访助手：工作日 9:00 cron，prompt 含 7/30 天节点、科室维度、"
                "未接通重试名单、完成率统计；可沉淀随访 SOP 技能。"
            ),
        ],
    },
    {
        "id": "healthcare_qc",
        "name": "医疗·病案质控",
        "title": "病案 DRG 质控周报",
        "user_messages": [
            (
                "我们是区域医疗集团，12 家院区。请设计「病案质控周报助手」："
                "每周五 17:00 汇总各院区病案首页完整性、ICD 编码缺陷、"
                "DRG 入组异常病例 TOP10、平均住院日偏离，并给出整改科室清单。"
            ),
        ],
        "assistant_replies": [
            (
                "病案质控周报助手：周五 17:00 cron，覆盖院区维度首页/ICD/DRG/住院日指标，"
                "输出整改科室清单。"
            ),
        ],
    },
    {
        "id": "education_k12",
        "name": "教育·K12 学情",
        "title": "校区学情周报",
        "user_messages": [
            (
                "我们是 K12 教培连锁，40 校区、数学/英语为主。"
                "需要「学情周报助手」：每周日 20:00 汇总各校区到课率、"
                "作业提交率、阶段测平均分、续费预警学员（14 天内到期）、"
                "退课原因 TOP3，并标注需班主任跟进的班级。"
            ),
        ],
        "assistant_replies": [
            (
                "学情周报助手：周日 20:00 cron，prompt 含校区/科目/到课/作业/测评分/"
                "续费预警/退课原因/班主任跟进清单。"
            ),
        ],
    },
    {
        "id": "education_enrollment",
        "name": "教育·招生运营",
        "title": "试听转化日报",
        "user_messages": [
            (
                "我们是职业培训学校，线上+线下招生，需要创建一名「招生跟进」数字员工（不是只做技能文档）。"
                "每个工作日 18:00 自动执行：汇总当日新增线索、试听到场率、"
                "7 日内未跟进线索、各渠道 ROI（抖音/美团/地推），"
                "并输出顾问次日优先跟进名单。请给出 agent + employee + cron 定时任务配置。"
            ),
        ],
        "assistant_replies": [
            (
                "已设计招生跟进数字员工：employee 名称「招生跟进助手」，"
                "cron 0 18 * * 1-5 工作日 18:00，task_config.prompt 含线索/试听/渠道 ROI/顾问优先级；"
                "同时沉淀招生 SOP 技能。建议 types 包含 employee + skill + agent。"
            ),
        ],
    },
]

PASS = FAIL = 0
failures: list[str] = []


def ok(name: str, detail: str = "") -> None:
    global PASS
    PASS += 1
    print(f"[PASS] {name}  ->  {detail}")


def fail(name: str, detail: str = "") -> None:
    global FAIL
    FAIL += 1
    failures.append(f"{name}: {detail}")
    print(f"[FAIL] {name}  ->  {detail}")


async def _register(client: httpx.AsyncClient) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    login = f"deposit_{suffix}"
    password = "DepositTest1!"
    r = await client.post(
        "/auth/register",
        json={
            "employee_no": login,
            "password": password,
            "email": f"{login}@test.local",
            "display_name": f"Deposit Test {suffix}",
        },
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"register failed: {r.status_code} {r.text[:200]}")
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _seed_transcript(conv_id: str, user_id: str, scenario: dict[str, Any]) -> None:
    from app.db.base import generate_uuid
    from app.db.models import Message, MessageRole
    from app.db.session import AsyncSessionLocal

    user_msgs = scenario["user_messages"]
    asst_msgs = scenario.get("assistant_replies") or []
    async with AsyncSessionLocal() as db:
        for i, text in enumerate(user_msgs):
            db.add(
                Message(
                    id=generate_uuid(),
                    conversation_id=conv_id,
                    role=MessageRole.user,
                    content=text,
                    metadata_={"seeded": True, "industry": scenario["id"]},
                )
            )
            if i < len(asst_msgs):
                db.add(
                    Message(
                        id=generate_uuid(),
                        conversation_id=conv_id,
                        role=MessageRole.assistant,
                        content=asst_msgs[i],
                        metadata_={"seeded": True},
                    )
                )
        await db.commit()


async def _live_chat(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    conv_id: str,
    scenario: dict[str, Any],
    *,
    timeout: float,
) -> None:
    for msg in scenario["user_messages"]:
        r = await client.post(
            f"/chat/conversations/{conv_id}/messages",
            headers=headers,
            json={"message": msg, "stream": False},
            timeout=timeout,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"chat failed: {r.status_code} {r.text[:300]}")


async def _run_scenario(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    scenario: dict[str, Any],
    *,
    seed: bool,
    chat_timeout: float,
    keep: bool,
) -> None:
    name = scenario["name"]
    sid = scenario["id"]
    created: dict[str, str | None] = {"employee_id": None, "agent_id": None}

    try:
        conv = await client.post(
            "/chat/conversations",
            headers=headers,
            json={"title": scenario["title"]},
        )
        if conv.status_code not in (200, 201):
            fail(name, f"create conv {conv.status_code}: {conv.text[:200]}")
            return
        conv_id = conv.json()["id"]

        if seed:
            me = await client.get("/auth/me", headers=headers)
            user_id = me.json()["id"]
            await _seed_transcript(conv_id, user_id, scenario)
            ok(f"{name} · seed transcript", f"{len(scenario['user_messages'])} user turns")
        else:
            await _live_chat(client, headers, conv_id, scenario, timeout=chat_timeout)
            ok(f"{name} · live chat", f"{len(scenario['user_messages'])} user turns")

        suggest = await client.post(
            f"/chat/conversations/{conv_id}/suggest-deposit",
            headers=headers,
            json={"lang": "zh"},
            timeout=chat_timeout,
        )
        if suggest.status_code >= 400:
            fail(name, f"suggest-deposit {suggest.status_code}: {suggest.text[:300]}")
            return
        sdata = suggest.json()
        if not sdata.get("worth_deposit"):
            fail(name, "worth_deposit=false")
            return
        draft_id = sdata.get("draft_id")
        if not draft_id:
            fail(name, "no draft_id")
            return

        types = [s.get("type") for s in sdata.get("suggestions") or []]
        ok(f"{name} · suggest", f"types={types} draft={draft_id[:8]}")

        draft = sdata.get("draft") or {}
        emp_name = draft.get("employee_name") or scenario["title"]
        has_employee = any(t == "employee" for t in types) or bool(draft.get("employee_name"))
        if not has_employee:
            fail(name, f"no employee suggestion in {types}, draft={draft.get('employee_name')}")
            return

        confirm = await client.post(
            f"/chat/conversations/{conv_id}/deposit/confirm",
            headers=headers,
            json={
                "draft_id": draft_id,
                "types": ["skill", "agent", "employee"],
                "activate_employee": True,
            },
            timeout=300.0,
        )
        if confirm.status_code >= 400:
            fail(name, f"confirm {confirm.status_code}: {confirm.text[:400]}")
            return
        cdata = confirm.json()
        emp_id = cdata.get("employee_id")
        agent_id = cdata.get("agent_id")
        tasks = cdata.get("tasks_created", 0)
        if not emp_id or not agent_id:
            fail(name, f"missing ids: {cdata}")
            return
        created["employee_id"] = emp_id
        created["agent_id"] = agent_id

        er = await client.get(f"/employees/{emp_id}", headers=headers)
        if er.status_code != 200:
            fail(name, f"get employee {er.status_code}")
            return
        emp = er.json()
        task_count_field = emp.get("task_count", 0)
        ok(
            f"{name} · employee created",
            f"name={emp.get('name')} task_count={task_count_field} (confirm reported {tasks}) title={emp.get('title')}",
        )

        tr = await client.get(f"/employees/{emp_id}/tasks", headers=headers)
        if tr.status_code == 200 and tr.json():
            first = tr.json()[0]
            cron = first.get("cron_expression") or first.get("schedule_label")
            ok(f"{name} · schedule", str(cron)[:80])
        else:
            fail(name, "no scheduled tasks on employee")

    finally:
        if not keep:
            emp_id = created.get("employee_id")
            agent_id = created.get("agent_id")
            if emp_id:
                try:
                    await client.delete(f"/employees/{emp_id}", headers=headers)
                except Exception:
                    pass
            if agent_id:
                try:
                    await client.delete(f"/agents/{agent_id}", headers=headers)
                except Exception:
                    pass


async def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-industry deposit -> employee E2E")
    parser.add_argument("--seed", action="store_true", help="Seed transcript in DB (skip chat LLM)")
    parser.add_argument("--keep", action="store_true", help="Keep created employees/agents")
    parser.add_argument("--industry", action="append", dest="industries", help="Run subset by id")
    parser.add_argument("--chat-timeout", type=float, default=300.0)
    args = parser.parse_args()

    scenarios = INDUSTRIES
    if args.industries:
        wanted = set(args.industries)
        scenarios = [s for s in INDUSTRIES if s["id"] in wanted]
        if not scenarios:
            print(f"Unknown industry ids: {wanted}")
            return 1

    print(f"Deposit employee industries @ {BASE}")
    print(f"Mode: {'seed transcript' if args.seed else 'live chat'} | scenarios={len(scenarios)}\n")

    async with httpx.AsyncClient(base_url=API, timeout=30.0) as client:
        health = await client.get(f"{BASE}/health")
        if health.status_code != 200:
            print(f"Backend unhealthy: {health.status_code}")
            return 1
        ok("health", health.json().get("status", "ok"))

        headers = await _register(client)
        ok("register", "test user")

        for scenario in scenarios:
            print(f"\n--- {scenario['name']} ({scenario['id']}) ---")
            await _run_scenario(
                client,
                headers,
                scenario,
                seed=args.seed,
                chat_timeout=args.chat_timeout,
                keep=args.keep,
            )

    print(f"\n{'=' * 50}")
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
