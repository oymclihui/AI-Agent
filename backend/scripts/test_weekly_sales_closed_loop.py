"""
Closed-loop test: Excel (BU × country × 12 weeks) → metrics → comparison report.

Architecture exercised:
  1. Chat + Excel attachment  — ad-hoc analysis (智能体 + 对话)
  2. Workflow (code → LLM)    — automated pipeline (工作流)
  3. Digital employee task    — scheduled-style report (数字员工)

Usage (backend running on :8000, Ollama reachable):
  cd backend
  .venv\\Scripts\\python.exe scripts\\test_weekly_sales_closed_loop.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
import pandas as pd
from sqlalchemy import select

from app.core.employees.runner import run_scheduled_task
from app.core.workflow.templates.loader import ensure_workflow_templates
from app.db.models import EmployeeScheduledTask, Workflow
from app.db.session import AsyncSessionLocal
from scripts.generate_weekly_sales_sample import build_dataframe, WEEK_COLS, OUT as XLSX_DEFAULT

BASE = "http://127.0.0.1:8000/api/v1"


from app.core.analytics.weekly_sales import compute_weekly_sales_metrics


def compute_metrics_snapshot(xlsx_path: Path) -> str:
    """Text snapshot for digital employee task prompt."""
    return compute_weekly_sales_metrics(xlsx_path)["metrics_summary"]


async def ensure_xlsx() -> Path:
    if not XLSX_DEFAULT.exists():
        from scripts.generate_weekly_sales_sample import main as gen

        gen()
    return XLSX_DEFAULT


async def login(client: httpx.AsyncClient) -> dict[str, str]:
    r = await client.post("/auth/login", json={"login": "admin", "password": "admin123"})
    r.raise_for_status()
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def step_chat_excel(client: httpx.AsyncClient, headers: dict, xlsx: Path) -> None:
    print("\n=== [1/3] 对话 + Excel 附件（智能体） ===")
    conv = await client.post("/chat/conversations", headers=headers, json={"title": "十二周销量分析测试"})
    conv.raise_for_status()
    conv_id = conv.json()["id"]

    prompt = (
        "请分析附件 Excel：字段含事业部、国家、第1–12周销量。"
        "输出中文 Markdown 报告，包含：执行摘要、整体趋势、周环比、事业部/国家对比、异常与建议。"
    )
    files = {"files": (xlsx.name, xlsx.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    data = {"message": prompt, "stream": "false"}
    msg = await client.post(
        f"/chat/conversations/{conv_id}/messages",
        headers=headers,
        data=data,
        files=files,
        timeout=600.0,
    )
    if msg.status_code >= 400:
        print("  chat failed:", msg.status_code, msg.text[:500])
        return
    body = msg.json()
    content = body.get("content") or body.get("message", {}).get("content") or ""
    print(f"  conversation: {conv_id}")
    print(f"  reply length: {len(content)} chars")
    print("  preview:", content[:400].replace("\n", " "), "...")


async def step_workflow(client: httpx.AsyncClient, headers: dict, xlsx: Path) -> None:
    print("\n=== [2/3] 工作流：Code(指标) → LLM(报告) ===")
    async with AsyncSessionLocal() as db:
        await ensure_workflow_templates(db)

    wfs = await client.get("/workflows/", headers=headers)
    wfs.raise_for_status()
    wf_id = None
    for wf in wfs.json():
        meta = wf.get("metadata") or {}
        if meta.get("template_id") == "weekly-sales-12w" or "十二周销量" in (wf.get("name") or ""):
            wf_id = wf["id"]
            break
    if not wf_id:
        print("  workflow weekly-sales-12w not found — restart backend to seed templates")
        return

    payload = {
        "input_data": {
            "file_path": str(xlsx.resolve()),
            "input": "生成十二周销量对比分析报告",
        }
    }
    ex = await client.post(f"/workflows/{wf_id}/execute", headers=headers, json=payload, timeout=600.0)
    if ex.status_code >= 400:
        print("  workflow failed:", ex.status_code, ex.text[:800])
        return
    out = ex.json().get("output") or {}
    report = out.get("final_output") or out.get("report_markdown") or ""
    errors = out.get("errors") or []
    print(f"  execution: {ex.json().get('execution_id')} status={ex.json().get('status')}")
    if errors:
        print("  errors:", errors)
    print(f"  report length: {len(str(report))} chars")
    print("  preview:", str(report)[:400].replace("\n", " "), "...")


async def step_employee(client: httpx.AsyncClient, headers: dict, xlsx: Path) -> None:
    print("\n=== [3/3] 数字员工：定时任务式报告 ===")
    snapshot = compute_metrics_snapshot(xlsx)

    imp = await client.post(
        "/employees/import-template",
        headers=headers,
        json={"template_id": "weekly-sales-12w-report", "employee_name": "销量分析测试助理"},
    )
    if imp.status_code >= 400:
        print("  import failed:", imp.status_code, imp.text[:500])
        return
    emp_id = imp.json()["employee"]["id"]
    tasks = await client.get(f"/employees/{emp_id}/tasks", headers=headers)
    tasks.raise_for_status()
    task_id = tasks.json()[0]["id"]

    async with AsyncSessionLocal() as db:
        task = await db.get(EmployeeScheduledTask, task_id)
        if not task:
            print("  task not found")
            return
        cfg = dict(task.task_config or {})
        prompt_tpl = str(cfg.get("prompt") or "")
        cfg["prompt"] = prompt_tpl.replace("{data_snapshot}", snapshot)
        cfg["context"] = {"data_snapshot": snapshot, "source_file": str(xlsx.name)}
        task.task_config = cfg
        await db.commit()
        emp = imp.json()["employee"]
        from app.db.models import DigitalEmployee

        employee = await db.get(DigitalEmployee, emp_id)
        run = await run_scheduled_task(db, task, employee, triggered_by="manual")
        await db.commit()
        await db.refresh(run)

    print(f"  employee: {emp_id} run: {run.id} status={run.status.value if hasattr(run.status, 'value') else run.status}")
    if run.status.value == "failed" if hasattr(run.status, "value") else run.status == "failed":
        print("  error:", run.error_message)
        return
    output = (run.output_data or {}).get("output") or ""
    print(f"  output length: {len(output)} chars")
    print("  preview:", output[:400].replace("\n", " "), "...")

    dl = await client.get(f"/employees/{emp_id}/runs/{run.id}/download", headers=headers)
    print(f"  markdown download: {dl.status_code} bytes={len(dl.content)}")

    save = await client.post(
        f"/employees/{emp_id}/runs/{run.id}/save-to-knowledge",
        headers=headers,
        json={"kb_name": "销量分析报告库"},
    )
    print(f"  save-to-kb: {save.status_code}", save.json() if save.status_code < 400 else save.text[:200])


async def main() -> None:
    xlsx = await ensure_xlsx()
    print("Sample Excel:", xlsx.resolve())
    print("Rows:", len(build_dataframe()), "Weeks:", len(WEEK_COLS))

    async with httpx.AsyncClient(base_url=BASE, timeout=600.0) as client:
        health = await client.get("http://127.0.0.1:8000/health")
        print("health:", health.status_code)
        headers = await login(client)

        await step_chat_excel(client, headers, xlsx)
        await step_workflow(client, headers, xlsx)
        await step_employee(client, headers, xlsx)

    print("\n=== 闭环完成 ===")
    print("  · 日常上传 Excel → 对话（智能体 + xlsx 技能）即时分析")
    print("  · 固定格式自动化 → 工作流 Code+LLM 或 数字员工每周定时")
    print("  · 报告沉淀 → 数字员工执行记录 → 存入知识库")


if __name__ == "__main__":
    asyncio.run(main())
