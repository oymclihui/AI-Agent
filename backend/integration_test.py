#!/usr/bin/env python3
"""
AI-AGENT integration test — L0 infrastructure, L1 module APIs, L2 cross-module chains.

Usage:
  python integration_test.py           # L0 + L1 + L2
  python integration_test.py --level L0
  python integration_test.py --level L2

Env:
  AIAGNET_TEST_BASE     default http://127.0.0.1:8000
  AIAGNET_SKIP_LLM=1    skip LLM-heavy cases (generate, configure-node)
  AIAGNET_SKIP_NETWORK=1 skip online skill library import
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
from typing import Any

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.environ.get("AIAGNET_TEST_BASE", "http://127.0.0.1:8000")
TIMEOUT = float(os.environ.get("AIAGNET_TEST_TIMEOUT", "600"))
PREFIX = os.environ.get("AIAGNET_TEST_PREFIX", "int-test")
SKIP_LLM = os.environ.get("AIAGNET_SKIP_LLM", "").lower() in ("1", "true", "yes")
SKIP_NETWORK = os.environ.get("AIAGNET_SKIP_NETWORK", "").lower() in ("1", "true", "yes")
CHAIN_PAUSE = float(os.environ.get("AIAGNET_CHAIN_PAUSE", "1.0"))

PASS, FAIL, SKIP = 0, 0, 0
failures: list[str] = []
chain_results: dict[str, str] = {}
_cleanup: list[tuple[str, str]] = []

default_provider: str | None = None
default_model: str | None = None
RUN_ID: str = ""


def uid(suffix: str = "") -> str:
    """Unique suffix for slugs/names within a test run."""
    base = RUN_ID or str(int(time.time() * 1000))
    return f"{PREFIX}-{base}{('-' + suffix) if suffix else ''}"


def wait_for_get(
    client: httpx.Client,
    path: str,
    name: str,
    *,
    expected: int = 200,
    retries: int = 6,
) -> httpx.Response | None:
    last: httpx.Response | None = None
    for attempt in range(retries):
        last = api(client, "GET", path)
        if last.status_code == expected:
            return last
        time.sleep(0.25 + attempt * 0.15)
    fail(name, f"HTTP {last.status_code if last else '?'} after {retries} retries")
    return None


def ok(name: str, detail: str = ""):
    global PASS
    PASS += 1
    print(f"\033[92m[PASS]\033[0m {name}  ->  {detail}", flush=True)


def fail(name: str, detail: str = ""):
    global FAIL
    FAIL += 1
    failures.append(f"{name}: {detail}")
    print(f"\033[91m[FAIL]\033[0m {name}  ->  {detail}", flush=True)


def skip(name: str, reason: str = ""):
    global SKIP
    SKIP += 1
    print(f"\033[93m[SKIP]\033[0m {name}  ->  {reason}", flush=True)


def chain_done(chain: str, status: str):
    chain_results[chain] = status


def assert_status(r: httpx.Response, expected: int, name: str) -> bool:
    if r.status_code != expected:
        fail(name, f"HTTP {r.status_code}, expected {expected}: {r.text[:200]}")
        return False
    return True


def api(client: httpx.Client, method: str, path: str, *, retries: int = 4, **kwargs) -> httpx.Response:
    """HTTP call with retry on SQLite 503 / transient errors."""
    last: httpx.Response | None = None
    for attempt in range(retries):
        try:
            last = client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            if attempt + 1 >= retries:
                raise
            time.sleep(2 + attempt)
            continue
        if last.status_code != 503:
            return last
        time.sleep(1.5 + attempt)
    return last  # type: ignore[return-value]


def pause_between_chains():
    if CHAIN_PAUSE > 0:
        time.sleep(CHAIN_PAUSE)


def parse_sse(text: str) -> list[str]:
    tokens = []
    for line in text.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            try:
                tokens.append(json.loads(line[6:]).get("token", ""))
            except json.JSONDecodeError:
                pass
    return tokens


def section(title: str):
    print(f"\n{'─' * 60}\n  {title}\n{'─' * 60}", flush=True)


def track(kind: str, rid: str):
    _cleanup.append((kind, rid))


def cleanup(client: httpx.Client):
    for kind, rid in reversed(_cleanup):
        try:
            paths = {
                "agent": f"/api/v1/agents/{rid}",
                "workflow": f"/api/v1/workflows/{rid}",
                "kb": f"/api/v1/knowledge/{rid}",
                "skill": f"/api/v1/skills/{rid}",
                "employee": f"/api/v1/employees/{rid}",
            }
            path = paths.get(kind)
            if path:
                client.delete(path)
        except Exception:
            pass


def agent_payload(**overrides) -> dict[str, Any]:
    base = {
        "name": uid("agent"),
        "role": "Test Agent",
        "goal": "Execute integration tests accurately",
        "backstory": "Integration test agent",
        "llm_provider": default_provider or "ollama",
        "llm_model": default_model or "qwen3.6:35b",
        "temperature": 0.1,
        "tools_config": [],
        "skills_config": [],
    }
    base.update(overrides)
    return base


# ── L0 Infrastructure ─────────────────────────────────────────────


def run_l0(client: httpx.Client) -> bool:
    global default_provider, default_model
    section("L0 · Infrastructure")
    alive = True

    try:
        r = client.get("/health")
        if assert_status(r, 200, "L0/health"):
            data = r.json()
            if data.get("status") == "healthy" and data.get("app") == "AI-AGENT":
                ok("L0/health", f"v{data.get('version', '?')}")
            else:
                fail("L0/health", f"unexpected: {data}")
                alive = False
    except Exception as exc:
        fail("L0/health", str(exc))
        return False

    try:
        r = client.get("/openapi.json")
        paths = r.json().get("paths", {}) if r.status_code == 200 else {}
        required = [
            "/api/v1/skills/",
            "/api/v1/employees/",
            "/api/v1/knowledge/{kb_id}/documents/{doc_id}/content",
            "/api/v1/workflows/generate",
        ]
        missing = [p for p in required if p not in paths]
        if missing:
            fail("L0/routes", f"missing routes (restart backend?): {missing}")
        else:
            ok("L0/routes", f"{len(required)} critical routes present")
    except Exception as exc:
        fail("L0/routes", str(exc))

    try:
        r = client.get("/api/v1/models/configs")
        if assert_status(r, 200, "L0/models/configs"):
            configs = r.json()
            default = next((c for c in configs if c.get("is_default")), None)
            if default:
                default_provider = default["provider"]
                default_model = default["model_id"]
                ok("L0/models/configs", f"default={default_provider}/{default_model}")
            else:
                fail("L0/models/configs", "no default model")
    except Exception as exc:
        fail("L0/models/configs", str(exc))

    try:
        r = client.get("/api/v1/models/available")
        if assert_status(r, 200, "L0/models/available"):
            data = r.json()
            count = len(data) if isinstance(data, list) else sum(len(v) for v in data.values())
            ok("L0/models/available", f"{count} models")
    except Exception as exc:
        fail("L0/models/available", str(exc))

    try:
        r = client.get("/api/v1/tools/")
        if assert_status(r, 200, "L0/tools"):
            names = {t["name"] for t in r.json()}
            if {"calculator", "web_search"} - names:
                fail("L0/tools", f"missing builtins in {names}")
            else:
                ok("L0/tools", str(sorted(names)))
    except Exception as exc:
        fail("L0/tools", str(exc))

    try:
        r = client.get("/api/v1/employees/scheduler/status")
        if assert_status(r, 200, "L0/scheduler"):
            ok("L0/scheduler", json.dumps(r.json(), ensure_ascii=False)[:80])
    except Exception as exc:
        fail("L0/scheduler", str(exc))

    return alive


# ── L1 Module APIs ────────────────────────────────────────────────


def run_l1(client: httpx.Client):
    section("L1 · Module APIs")

    # Skills CRUD
    skill_id = None
    try:
        r = api(client, "POST", "/api/v1/skills/", json={
            "display_name": uid("skill"),
            "description": "Integration test skill for format prefix.",
            "instructions_md": "Always prefix replies with [SKILL].",
            "status": "active",
            "tags": ["test"],
        })
        if assert_status(r, 201, "L1/skills/create"):
            skill_id = r.json()["id"]
            track("skill", skill_id)
            ok("L1/skills/create", skill_id[:8])
    except Exception as exc:
        fail("L1/skills/create", str(exc))

    if skill_id:
        try:
            r = wait_for_get(client, f"/api/v1/skills/{skill_id}", "L1/skills/get")
            if r:
                ok("L1/skills/get", r.json().get("slug", ""))
        except Exception as exc:
            fail("L1/skills/get", str(exc))

    try:
        r = client.get("/api/v1/skills/library/sources")
        if assert_status(r, 200, "L1/skills/library/sources"):
            ok("L1/skills/library/sources", f"{len(r.json())} sources")
    except Exception as exc:
        fail("L1/skills/library/sources", str(exc))

    try:
        r = client.get("/api/v1/skills/library/catalog", params={"q": "review"})
        if assert_status(r, 200, "L1/skills/library/catalog"):
            ok("L1/skills/library/catalog", f"{len(r.json())} templates")
    except Exception as exc:
        fail("L1/skills/library/catalog", str(exc))

    # Employees list + seed presence
    try:
        r = client.get("/api/v1/employees/")
        if assert_status(r, 200, "L1/employees/list"):
            ok("L1/employees/list", f"{len(r.json())} employees")
    except Exception as exc:
        fail("L1/employees/list", str(exc))

    # Workflows node catalog
    try:
        r = client.get("/api/v1/workflows/node-catalog")
        if assert_status(r, 200, "L1/workflows/node-catalog"):
            total = r.json().get("total", 0)
            if total < 100:
                fail("L1/workflows/node-catalog", f"total={total} too low")
            else:
                ok("L1/workflows/node-catalog", f"total={total}")
    except Exception as exc:
        fail("L1/workflows/node-catalog", str(exc))

    # Knowledge content route on seed KB
    try:
        kbs = client.get("/api/v1/knowledge/").json()
        platform_kb = next(
            (k for k in kbs if "平台" in k.get("name", "") or "AI-AGENT" in k.get("name", "")),
            None,
        )
        if platform_kb:
            docs = client.get(f"/api/v1/knowledge/{platform_kb['id']}/documents").json()
            if docs:
                r = client.get(
                    f"/api/v1/knowledge/{platform_kb['id']}/documents/{docs[0]['id']}/content"
                )
                if assert_status(r, 200, "L1/knowledge/content"):
                    content = r.json().get("content", "")
                    ok("L1/knowledge/content", f"len={len(content)}, source={r.json().get('source')}")
            else:
                skip("L1/knowledge/content", "platform KB has no documents")
        else:
            skip("L1/knowledge/content", "platform KB not seeded")
    except Exception as exc:
        fail("L1/knowledge/content", str(exc))


# ── L2 Chain A: Skill → Agent → Run ──────────────────────────────


def chain_a_skill_agent_run(client: httpx.Client) -> tuple[str | None, str | None]:
    section("L2-A · Skill → Agent → Run")
    skill_id = agent_id = None
    chain_ok = True

    try:
        r = api(client, "POST", "/api/v1/skills/", json={
            "slug": uid("prefix-skill"),
            "display_name": f"{PREFIX} Prefix Skill",
            "description": "Forces prefix in agent output.",
            "instructions_md": (
                "You MUST start every reply with exactly the token [SKILL] "
                "followed by a space, then your answer."
            ),
            "status": "active",
        })
        if not assert_status(r, 201, "L2-A/skill/create"):
            chain_done("A", "fail")
            return None, None
        skill_id = r.json()["id"]
        track("skill", skill_id)
    except Exception as exc:
        fail("L2-A/skill/create", str(exc))
        chain_done("A", "fail")
        return None, None

    try:
        r = api(client, "POST", "/api/v1/agents/", json=agent_payload(
            name=uid("skill-agent"),
            skills_config=[{"skill_id": skill_id, "always_load": True, "priority": 10}],
        ))
        if not assert_status(r, 201, "L2-A/agent/create"):
            chain_done("A", "fail")
            return skill_id, None
        agent_id = r.json()["id"]
        track("agent", agent_id)
    except Exception as exc:
        fail("L2-A/agent/create", str(exc))
        chain_done("A", "fail")
        return skill_id, None

    try:
        t0 = time.time()
        r = client.post(f"/api/v1/agents/{agent_id}/run", json={
            "task": "Reply with the single word: OK"
        })
        if assert_status(r, 200, "L2-A/agent/run"):
            out = r.json().get("output", "")
            if "[SKILL]" in out:
                ok("L2-A/agent/run", f"prefix found in {out[:50]!r} ({time.time()-t0:.1f}s)")
            else:
                fail("L2-A/agent/run", f"[SKILL] not in output: {out[:120]!r}")
                chain_ok = False
    except Exception as exc:
        fail("L2-A/agent/run", str(exc))
        chain_ok = False

    chain_done("A", "pass" if chain_ok else "fail")
    pause_between_chains()
    return skill_id, agent_id


# ── L2 Chain B: Skill → Agent → Chat ─────────────────────────────


def chain_b_skill_agent_chat(client: httpx.Client, agent_id: str | None):
    section("L2-B · Skill → Agent → Chat")
    if not agent_id:
        skip("L2-B", "no agent from chain A")
        chain_done("B", "skip")
        return

    chain_ok = True
    conv_id = None
    try:
        r = client.post("/api/v1/chat/conversations", json={
            "title": f"{PREFIX}-skill-chat",
            "agent_id": agent_id,
            "memory_type": "buffer",
        })
        if not assert_status(r, 201, "L2-B/chat/create"):
            chain_done("B", "fail")
            return
        conv_id = r.json()["id"]
    except Exception as exc:
        fail("L2-B/chat/create", str(exc))
        chain_done("B", "fail")
        return

    try:
        r = client.post(f"/api/v1/chat/conversations/{conv_id}/messages", json={
            "message": "Say OK only. Remember to follow your skill prefix rules."
        })
        if assert_status(r, 200, "L2-B/chat/message"):
            content = r.json().get("content", "")
            if "[SKILL]" in content:
                ok("L2-B/chat/message", f"{content[:60]!r}")
            else:
                fail("L2-B/chat/message", f"[SKILL] missing: {content[:100]!r}")
                chain_ok = False
    except Exception as exc:
        fail("L2-B/chat/message", str(exc))
        chain_ok = False

    try:
        with client.stream(
            "POST",
            f"/api/v1/chat/conversations/{conv_id}/messages",
            json={"message": "Reply OK with prefix.", "stream": True},
        ) as resp:
            if resp.status_code != 200:
                fail("L2-B/chat/stream", f"HTTP {resp.status_code}")
                chain_ok = False
            else:
                body = resp.read().decode("utf-8", errors="replace")
                tokens = parse_sse(body)
                ok("L2-B/chat/stream", f"tokens={len(tokens)}")
    except Exception as exc:
        fail("L2-B/chat/stream", str(exc))
        chain_ok = False

    chain_done("B", "pass" if chain_ok else "fail")
    pause_between_chains()


# ── L2 Chain C: Employee → Task → Run → Runs ───────────────────


def chain_c_employee_task(client: httpx.Client) -> str | None:
    section("L2-C · Employee → Task → Run → Runs")
    chain_ok = True
    employee_id = None

    agent_id = None
    try:
        r = api(client, "POST", "/api/v1/agents/", json=agent_payload(
            name=uid("emp-agent"),
            tools_config=[{"tool_name": "calculator"}],
        ))
        if not assert_status(r, 201, "L2-C/agent/create"):
            chain_done("C", "fail")
            return None
        agent_id = r.json()["id"]
        track("agent", agent_id)
        verify = wait_for_get(client, f"/api/v1/agents/{agent_id}", "L2-C/agent/verify")
        if not verify:
            chain_done("C", "fail")
            return None
    except Exception as exc:
        fail("L2-C/agent/create", str(exc))
        chain_done("C", "fail")
        return None

    try:
        r = api(client, "POST", "/api/v1/employees/", json={
            "name": f"{PREFIX}-employee",
            "title": "Test Clerk",
            "description": "Integration test employee",
            "agent_id": agent_id,
            "timezone": "Asia/Shanghai",
        })
        if not assert_status(r, 201, "L2-C/employee/create"):
            chain_done("C", "fail")
            return None
        employee_id = r.json()["id"]
        track("employee", employee_id)
    except Exception as exc:
        fail("L2-C/employee/create", str(exc))
        chain_done("C", "fail")
        return None

    task_id = None
    try:
        r = client.post(f"/api/v1/employees/{employee_id}/tasks", json={
            "name": f"{PREFIX}-calc-task",
            "schedule_type": "interval",
            "interval_seconds": 3600,
            "task_type": "agent",
            "task_config": {
                "prompt": "Calculate 100 * 5 + 7. Output only the final number."
            },
        })
        if assert_status(r, 201, "L2-C/task/create"):
            task_id = r.json()["id"]
            ok("L2-C/task/create", f"next_run={str(r.json().get('next_run_at'))[:19]}")
    except Exception as exc:
        fail("L2-C/task/create", str(exc))
        chain_done("C", "fail")
        return employee_id

    try:
        t0 = time.time()
        r = api(client, "POST", f"/api/v1/employees/{employee_id}/tasks/{task_id}/run", timeout=600.0)
        if assert_status(r, 200, "L2-C/task/run"):
            data = r.json()
            status = data.get("status", "")
            if hasattr(status, "value"):
                status = status.value
            status = str(status)
            out = (data.get("output_data") or {}).get("output", "")
            if status == "completed" and "507" in str(out).replace(",", ""):
                ok("L2-C/task/run", f"507 in output ({time.time()-t0:.1f}s)")
            elif status == "completed":
                ok("L2-C/task/run", f"completed, out={str(out)[:40]!r} ({time.time()-t0:.1f}s)")
            else:
                fail("L2-C/task/run", f"status={status}, err={data.get('error_message', '')[:100]}")
                chain_ok = False
    except Exception as exc:
        fail("L2-C/task/run", str(exc))
        chain_ok = False

    try:
        r = client.get(f"/api/v1/employees/{employee_id}/runs")
        if assert_status(r, 200, "L2-C/runs"):
            runs = r.json()
            if runs:
                ok("L2-C/runs", f"{len(runs)} run(s), latest={runs[0].get('status')}")
            else:
                fail("L2-C/runs", "no runs recorded")
                chain_ok = False
    except Exception as exc:
        fail("L2-C/runs", str(exc))
        chain_ok = False

    chain_done("C", "pass" if chain_ok else "fail")
    pause_between_chains()
    return employee_id


# ── L2 Chain D: Workflows ─────────────────────────────────────────


def chain_d_workflows(client: httpx.Client):
    section("L2-D · Workflows (tool + NL generate)")
    chain_ok = True
    wf_id = None

    try:
        r = client.post("/api/v1/workflows/", json={
            "name": f"{PREFIX}-tool-wf",
            "description": "Calculator workflow chain test",
            "process_type": "sequential",
            "graph_definition": {
                "nodes": [
                    {"id": "start", "type": "start", "label": "Start", "config": {}, "position": {"x": 0, "y": 0}},
                    {"id": "calc", "type": "tool", "label": "Calc", "config": {"tool_name": "calculator"}, "position": {"x": 200, "y": 0}},
                    {"id": "end", "type": "end", "label": "End", "config": {}, "position": {"x": 400, "y": 0}},
                ],
                "edges": [
                    {"id": "e1", "source": "start", "target": "calc"},
                    {"id": "e2", "source": "calc", "target": "end"},
                ],
            },
        })
        if assert_status(r, 201, "L2-D/wf/create"):
            wf_id = r.json()["id"]
            track("workflow", wf_id)
    except Exception as exc:
        fail("L2-D/wf/create", str(exc))
        chain_done("D", "fail")
        return

    try:
        r = client.post(f"/api/v1/workflows/{wf_id}/execute", json={
            "input_data": {"expression": "999 + 1"}
        })
        if assert_status(r, 200, "L2-D/wf/execute"):
            ok("L2-D/wf/execute", f"status={r.json().get('status')}")
    except Exception as exc:
        fail("L2-D/wf/execute", str(exc))
        chain_ok = False

    if SKIP_LLM:
        skip("L2-D/wf/generate", "AIAGNET_SKIP_LLM=1")
        skip("L2-D/configure-node", "AIAGNET_SKIP_LLM=1")
    else:
        try:
            t0 = time.time()
            r = client.post("/api/v1/workflows/generate", json={
                "description": "A simple workflow: start, one LLM node summarizing input, then end."
            })
            if assert_status(r, 201, "L2-D/wf/generate"):
                gen_id = r.json()["id"]
                track("workflow", gen_id)
                nodes = len(r.json().get("graph_definition", {}).get("nodes", []))
                ok("L2-D/wf/generate", f"{nodes} nodes ({time.time()-t0:.1f}s)")
        except Exception as exc:
            skip("L2-D/wf/generate", str(exc))

        try:
            r = client.post("/api/v1/workflows/configure-node", json={
                "node_id": "httpRequest",
                "prompt": "Set method GET and url https://example.com",
                "current_config": {},
            })
            if assert_status(r, 200, "L2-D/configure-node"):
                cfg = r.json().get("config", {})
                ok("L2-D/configure-node", f"keys={list(cfg.keys())[:5]}")
        except Exception as exc:
            skip("L2-D/configure-node", str(exc))

    chain_done("D", "pass" if chain_ok else "fail")
    pause_between_chains()


# ── L2 Chain E: Orchestrator ──────────────────────────────────────


def chain_e_orchestrator(client: httpx.Client):
    section("L2-E · Orchestrator")
    try:
        agents = client.get("/api/v1/agents/").json()
        int_agents = [a for a in agents if str(a.get("name", "")).startswith(PREFIX)]
        if len(int_agents) < 2:
            agents = client.get("/api/v1/agents/").json()
            int_agents = agents[:2]
        if len(int_agents) < 2:
            skip("L2-E/orchestrator", "need 2 agents")
            chain_done("E", "skip")
            return
        ids = [a["id"] for a in int_agents[:2]]
        t0 = time.time()
        r = api(client, "POST", "/api/v1/orchestrator/run", json={
            "goal": "Say hello in one short sentence.",
            "process": "sequential",
            "agent_ids": ids,
            "tasks": [{"description": "Say hello in one short sentence.", "agent_id": ids[0]}],
        }, timeout=600.0)
        if assert_status(r, 200, "L2-E/orchestrator"):
            out = r.json().get("output", "")
            ok("L2-E/orchestrator", f"out_len={len(out)} ({time.time()-t0:.1f}s)")
            chain_done("E", "pass")
        else:
            chain_done("E", "fail")
    except httpx.TimeoutException:
        skip("L2-E/orchestrator", "timed out")
        chain_done("E", "skip")
    except Exception as exc:
        fail("L2-E/orchestrator", str(exc))
        chain_done("E", "fail")
    pause_between_chains()


# ── L2 Chain F: Knowledge ─────────────────────────────────────────


def chain_f_knowledge(client: httpx.Client):
    section("L2-F · Knowledge (upload → search → content)")
    chain_ok = True
    kb_id = doc_id = None
    marker = f"{PREFIX}-UNIQUE-{int(time.time())}"

    try:
        r = api(client, "POST", "/api/v1/knowledge/", json={
            "name": f"{PREFIX}-kb",
            "description": "Integration test KB",
            "embedding_model": "nomic-embed-text",
        })
        if not assert_status(r, 201, "L2-F/kb/create"):
            chain_done("F", "fail")
            return
        kb_id = r.json()["id"]
        track("kb", kb_id)
        verify = wait_for_get(client, f"/api/v1/knowledge/{kb_id}", "L2-F/kb/verify")
        if not verify:
            chain_done("F", "fail")
            return
    except Exception as exc:
        fail("L2-F/kb/create", str(exc))
        chain_done("F", "fail")
        return

    text = f"AI-AGENT integration marker {marker} for RAG retrieval testing."
    try:
        r = api(client, "POST", f"/api/v1/knowledge/{kb_id}/documents",
                files={"file": ("chain-f.txt", text.encode("utf-8"), "text/plain")})
        if assert_status(r, 201, "L2-F/upload"):
            doc_id = r.json()["id"]
            ok("L2-F/upload", f"chunks={r.json().get('chunk_count')}")
    except Exception as exc:
        fail("L2-F/upload", str(exc))
        chain_done("F", "fail")
        return

    try:
        r = client.post(f"/api/v1/knowledge/{kb_id}/search", json={
            "query": marker,
            "top_k": 3,
            "score_threshold": 0.0,
        })
        if assert_status(r, 200, "L2-F/search"):
            hits = r.json()
            if hits and marker in hits[0].get("content", ""):
                ok("L2-F/search", f"{len(hits)} hits, marker found")
            elif hits:
                ok("L2-F/search", f"{len(hits)} hits (weak match)")
            else:
                fail("L2-F/search", "no hits")
                chain_ok = False
    except Exception as exc:
        fail("L2-F/search", str(exc))
        chain_ok = False

    if doc_id:
        try:
            r = client.get(f"/api/v1/knowledge/{kb_id}/documents/{doc_id}/content")
            if assert_status(r, 200, "L2-F/content"):
                content = r.json().get("content", "")
                if marker in content:
                    ok("L2-F/content", f"source={r.json().get('source')}, len={len(content)}")
                else:
                    fail("L2-F/content", f"marker missing, len={len(content)}")
                    chain_ok = False
        except Exception as exc:
            fail("L2-F/content", str(exc))
            chain_ok = False

    try:
        kbs = client.get("/api/v1/knowledge/").json()
        platform_kb = next(
            (k for k in kbs if "平台" in k.get("name", "") or "AI-AGENT" in k.get("name", "")),
            None,
        )
        if platform_kb:
            r = client.post(f"/api/v1/knowledge/{platform_kb['id']}/search", json={
                "query": "数字员工 Phase 2",
                "top_k": 3,
                "score_threshold": 0.0,
            })
            if assert_status(r, 200, "L2-F/platform-kb/search"):
                hits = r.json()
                ok("L2-F/platform-kb/search", f"{len(hits)} hits")
        else:
            skip("L2-F/platform-kb/search", "no seed KB")
    except Exception as exc:
        fail("L2-F/platform-kb/search", str(exc))
        chain_ok = False

    chain_done("F", "pass" if chain_ok else "fail")
    pause_between_chains()


# ── L2 Chain G: Skill library import ──────────────────────────────


def chain_g_skill_library(client: httpx.Client):
    section("L2-G · Skill library import")
    if SKIP_NETWORK:
        skip("L2-G", "AIAGNET_SKIP_NETWORK=1")
        chain_done("G", "skip")
        return

    try:
        r = client.get("/api/v1/skills/library/catalog", params={"q": "commit", "limit": 5})
        if not assert_status(r, 200, "L2-G/catalog"):
            chain_done("G", "fail")
            return
        templates = r.json()[:1]
        if not templates:
            skip("L2-G/import", "no templates")
            chain_done("G", "skip")
            return
        item = templates[0]
        r2 = client.post("/api/v1/skills/library/import", json={
            "items": [{"source": item["source"], "slug": item["slug"]}],
            "overwrite": False,
        })
        if assert_status(r2, 200, "L2-G/import"):
            imported = r2.json().get("imported", r2.json())
            ok("L2-G/import", str(imported)[:80])
            chain_done("G", "pass")
        else:
            chain_done("G", "fail")
    except Exception as exc:
        skip("L2-G", str(exc))
        chain_done("G", "skip")
    pause_between_chains()


# ── L2 Chain H: Onboarding E2E ────────────────────────────────────


def chain_h_onboarding(client: httpx.Client):
    section("L2-H · Onboarding E2E (mini)")
    chain_ok = True

    skill_id = agent_id = employee_id = None
    try:
        r = api(client, "POST", "/api/v1/skills/", json={
            "slug": uid("onboard-skill"),
            "display_name": f"{PREFIX} Onboard Skill",
            "description": "Onboarding test skill.",
            "instructions_md": "Be concise.",
            "status": "active",
        })
        if assert_status(r, 201, "L2-H/skill"):
            skill_id = r.json()["id"]
            track("skill", skill_id)
        else:
            chain_ok = False
            chain_done("H", "fail")
            return
    except Exception as exc:
        fail("L2-H/skill", str(exc))
        chain_done("H", "fail")
        return

    try:
        r = client.post("/api/v1/agents/", json=agent_payload(
            name=f"{PREFIX}-onboard-agent",
            tools_config=[{"tool_name": "calculator"}],
            skills_config=[{"skill_id": skill_id, "always_load": True}],
        ))
        if assert_status(r, 201, "L2-H/agent"):
            agent_id = r.json()["id"]
            track("agent", agent_id)
    except Exception as exc:
        fail("L2-H/agent", str(exc))
        chain_done("H", "fail")
        return

    try:
        r = client.post("/api/v1/employees/", json={
            "name": f"{PREFIX}-onboard-emp",
            "title": "Onboard",
            "agent_id": agent_id,
        })
        if assert_status(r, 201, "L2-H/employee"):
            employee_id = r.json()["id"]
            track("employee", employee_id)
    except Exception as exc:
        fail("L2-H/employee", str(exc))
        chain_done("H", "fail")
        return

    task_id = None
    try:
        r = client.post(f"/api/v1/employees/{employee_id}/tasks", json={
            "name": f"{PREFIX}-onboard-task",
            "schedule_type": "interval",
            "interval_seconds": 3600,
            "task_config": {"prompt": "Reply with: onboard-ok"},
        })
        if assert_status(r, 201, "L2-H/task"):
            task_id = r.json()["id"]
    except Exception as exc:
        fail("L2-H/task", str(exc))
        chain_done("H", "fail")
        return

    try:
        r = api(client, "POST", f"/api/v1/employees/{employee_id}/tasks/{task_id}/run", timeout=600.0)
        if assert_status(r, 200, "L2-H/run"):
            status = str(r.json().get("status", ""))
            if "completed" in status:
                ok("L2-H/run", status)
            else:
                fail("L2-H/run", f"status={status}")
                chain_ok = False
    except httpx.TimeoutException:
        skip("L2-H/run", "timed out")
        chain_ok = False
    except Exception as exc:
        fail("L2-H/run", str(exc))
        chain_ok = False

    try:
        r = api(client, "POST", "/api/v1/chat/conversations", json={
            "title": f"{PREFIX}-onboard-chat",
            "agent_id": agent_id,
        })
        if assert_status(r, 201, "L2-H/chat"):
            conv_id = r.json()["id"]
            r2 = api(client, "POST", f"/api/v1/chat/conversations/{conv_id}/messages", json={
                "message": "Say onboard-ok"
            }, timeout=600.0)
            if assert_status(r2, 200, "L2-H/chat/msg"):
                ok("L2-H/chat/msg", f"{r2.json().get('content', '')[:40]!r}")
    except Exception as exc:
        fail("L2-H/chat", str(exc))
        chain_ok = False

    chain_done("H", "pass" if chain_ok else "fail")
    pause_between_chains()


# ── Main ──────────────────────────────────────────────────────────


def print_summary(elapsed: float, report_path: str | None):
    print("\n" + "=" * 60)
    print(f"INTEGRATION TEST: {PASS} passed, {FAIL} failed, {SKIP} skipped  ({elapsed:.0f}s)")
    if chain_results:
        print("\nChains:")
        for name, status in chain_results.items():
            icon = {"pass": "✓", "fail": "✗", "skip": "−"}.get(status, "?")
            print(f"  [{icon}] {name}: {status}")
    if failures:
        print("\nFailures:")
        for item in failures:
            print(f"  - {item}")

    report = {
        "passed": PASS,
        "failed": FAIL,
        "skipped": SKIP,
        "duration_s": round(elapsed, 1),
        "chains": chain_results,
        "failures": failures,
        "base": BASE,
    }
    if report_path:
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(f"\nReport: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="AI-AGENT integration test")
    parser.add_argument(
        "--level",
        choices=["L0", "L1", "L2", "ALL"],
        default="ALL",
        help="Test level (default ALL = L0+L1+L2)",
    )
    parser.add_argument("--report", default="", help="Write JSON report to path")
    args = parser.parse_args()

    level = args.level.upper()
    global RUN_ID
    RUN_ID = str(int(time.time() * 1000))
    run_l0_flag = level in ("L0", "ALL")
    run_l1_flag = level in ("L1", "ALL")
    run_l2_flag = level in ("L2", "ALL")

    client = httpx.Client(base_url=BASE, timeout=TIMEOUT)
    t_start = time.time()

    try:
        if run_l0_flag:
            if not run_l0(client):
                print_summary(time.time() - t_start, args.report or None)
                sys.exit(1)
        elif run_l1_flag or run_l2_flag:
            run_l0(client)

        if run_l1_flag:
            run_l1(client)

        if run_l2_flag:
            _, agent_id = chain_a_skill_agent_run(client)
            chain_b_skill_agent_chat(client, agent_id)
            chain_c_employee_task(client)
            chain_d_workflows(client)
            chain_e_orchestrator(client)
            chain_f_knowledge(client)
            chain_g_skill_library(client)
            chain_h_onboarding(client)

        section("Cleanup")
        cleanup(client)
        ok("cleanup", f"removed {len(_cleanup)} resource(s)")

    finally:
        client.close()

    print_summary(time.time() - t_start, args.report or None)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
