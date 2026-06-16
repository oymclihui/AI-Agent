#!/usr/bin/env python3
"""Phase 0 — validate multi-agent discussion via orchestrator + manual transcript."""
from __future__ import annotations

import io
import os
import sys
import textwrap

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
API = f"{BASE}/api/v1"
ADMIN_LOGIN = os.environ.get("SMOKE_ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.environ.get("SMOKE_ADMIN_PASSWORD", "admin456")

STANDARD_PROMPTS = {
    "contract-review": (
        "请审查这份采购合同要点：付款节点前置 70%、违约金无上限、"
        "知识产权默认归供应商。请从法务、财务、产品三方面给出修改建议。"
    ),
    "data-analysis": (
        "近 12 个月销量为 120,135,142,158,176,195,210,188,205,230,248,268（万元）。"
        "请分析趋势、指出异常波动月份，并给出 3 条可执行的改进建议。"
    ),
}


def login(client: httpx.Client) -> dict[str, str]:
    r = client.post(f"{API}/auth/login", json={"login": ADMIN_LOGIN, "password": ADMIN_PASSWORD})
    r.raise_for_status()
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def pick_agents(client: httpx.Client, headers: dict, n: int = 3) -> list[str]:
    r = client.get(f"{API}/agents", headers=headers)
    r.raise_for_status()
    agents = r.json()
    if len(agents) < n:
        raise RuntimeError(f"Need at least {n} agents, found {len(agents)}")
    return [a["id"] for a in agents[:n]]


def build_transcript(goal: str, task_outputs: dict[str, str], agent_names: list[str]) -> str:
    lines = [f"# 讨论主题\n{goal}\n", "## 智能体发言（sequential crew）\n"]
    for i, (key, output) in enumerate(task_outputs.items()):
        name = agent_names[i] if i < len(agent_names) else key
        lines.append(f"### {name}\n{textwrap.indent(output.strip(), '')}\n")
    return "\n".join(lines)


def run_case(client: httpx.Client, headers: dict, case_id: str, goal: str) -> None:
    agent_ids = pick_agents(client, headers, 3)
    agents_r = client.get(f"{API}/agents", headers=headers)
    agents = {a["id"]: a["name"] for a in agents_r.json()}

    tasks = [
        {"description": f"{goal}\n\n请从你的专业角度给出 3-5 条要点。", "agent_id": agent_ids[0]},
        {"description": f"{goal}\n\n请补充或质疑上一位观点，给出你的专业意见。", "agent_id": agent_ids[1]},
        {"description": f"{goal}\n\n综合前两位发言，给出最终建议摘要。", "agent_id": agent_ids[2]},
    ]

    print(f"\n{'='*60}\nCase: {case_id}\nGoal: {goal[:80]}...\nAgents: {[agents.get(i, i) for i in agent_ids]}")

    r = client.post(
        f"{API}/orchestrator/run",
        headers=headers,
        json={
            "goal": goal,
            "process": "sequential",
            "agent_ids": agent_ids,
            "tasks": tasks,
        },
        timeout=300.0,
    )
    r.raise_for_status()
    data = r.json()
    transcript = build_transcript(
        goal,
        data.get("task_outputs") or {},
        [agents.get(aid, aid) for aid in agent_ids],
    )
    print(transcript)
    print(f"\nFinal output ({data.get('elapsed_s')}s):\n{data.get('output', '')[:2000]}")


def main() -> None:
    client = httpx.Client(timeout=300.0)
    headers = login(client)
    health = client.get(f"{BASE}/health")
    health.raise_for_status()
    print(f"Backend OK: {health.json().get('status')}")

    for case_id, prompt in STANDARD_PROMPTS.items():
        run_case(client, headers, case_id, prompt)

    print("\nPhase 0 validation complete.")


if __name__ == "__main__":
    main()
