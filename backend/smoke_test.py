#!/usr/bin/env python3
"""End-to-end smoke test for AIAGNET backend (UTF-8 safe)."""
import sys
import io
import json
import time
import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000"
PASS, FAIL, SKIP = 0, 0, 0
failures: list[str] = []


def ok(name: str, detail: str = ""):
    global PASS
    PASS += 1
    print(f"\033[92m[PASS]\033[0m {name}  ->  {detail}")


def fail(name: str, detail: str = ""):
    global FAIL
    FAIL += 1
    failures.append(f"{name}: {detail}")
    print(f"\033[91m[FAIL]\033[0m {name}  ->  {detail}")


def skip(name: str, reason: str = ""):
    global SKIP
    SKIP += 1
    print(f"\033[93m[SKIP]\033[0m {name}  ->  {reason}")


def main():
    client = httpx.Client(base_url=BASE, timeout=120.0)

    # 1. Health
    try:
        r = client.get("/health")
        ok("health", r.json().get("status", ""))
    except Exception as e:
        fail("health", str(e))
        print("Backend not running — aborting.")
        return

    # 2. Models
    try:
        r = client.get("/api/v1/models/available")
        data = r.json()
        ok("models/available", f"{len(data)} total")
    except Exception as e:
        fail("models/available", str(e))

    try:
        r = client.get("/api/v1/models/configs")
        configs = r.json()
        default = next((c for c in configs if c.get("is_default")), {})
        ok("models/configs", f"{len(configs)} configs, default={default.get('provider')}/{default.get('model_id')}")
    except Exception as e:
        fail("models/configs", str(e))

    # 3. Tools
    try:
        r = client.get("/api/v1/tools/")
        tools = [t["name"] for t in r.json()]
        ok("tools/list", f"{len(tools)}: {tools}")
    except Exception as e:
        fail("tools/list", str(e))

    # 4. Agents
    try:
        r = client.get("/api/v1/agents/")
        agents = r.json()
        ok("agents/list", f"{len(agents)} agents")
    except Exception as e:
        fail("agents/list", str(e))

    try:
        r = client.post("/api/v1/agents/", json={
            "name": "冒烟测试助手", "role": "Test Agent",
            "goal": "Answer test questions", "backstory": "Smoke test",
            "llm_provider": "ollama", "llm_model": "qwen3.6:35b",
        })
        agent_id = r.json()["id"]
        ok("agents/create", f"id={agent_id[:8]}")
    except Exception as e:
        fail("agents/create", str(e))
        agent_id = None

    # 5. Agent run with calculator
    calc_agent = None
    try:
        agents = client.get("/api/v1/agents/").json()
        calc_agent = next((a for a in agents if "calculator" in str(a.get("tools_config", ""))), agent_id)
        if calc_agent:
            t0 = time.time()
            r = client.post(f"/api/v1/agents/{calc_agent['id']}/run", json={"task": "计算 12345 * 4 + 3，只输出数字结果"})
            out = r.json().get("output", "")
            ok("agents/run(tool)", f"output={out[:30]!r} in {time.time()-t0:.1f}s")
        else:
            skip("agents/run(tool)", "no calculator agent")
    except Exception as e:
        fail("agents/run(tool)", str(e))

    # 6. Chat quick
    try:
        t0 = time.time()
        r = client.post("/api/v1/chat/quick", json={"message": "天空是什么颜色？用两个字回答"})
        content = r.json().get("content", "")
        ok("chat/quick", f"{content[:20]!r} in {time.time()-t0:.1f}s")
    except Exception as e:
        fail("chat/quick", str(e))

    # 7. Chat memory
    try:
        r = client.post("/api/v1/chat/conversations", json={"title": "memory-test", "memory_type": "buffer"})
        conv_id = r.json()["id"]
        client.post(f"/api/v1/chat/conversations/{conv_id}/messages", json={"message": "我叫小明"})
        r2 = client.post(f"/api/v1/chat/conversations/{conv_id}/messages", json={"message": "我叫什么？"})
        content = r2.json().get("content", "")
        ok("chat/memory", f"name recalled: {content[:40]!r}")
    except Exception as e:
        fail("chat/memory", str(e))

    # 8. Knowledge + Milvus
    try:
        r = client.post("/api/v1/knowledge/", json={
            "name": "冒烟知识库", "description": "smoke",
            "embedding_model": "nomic-embed-text",
        })
        kb_id = r.json()["id"]
        ok("knowledge/create", f"id={kb_id[:8]}")
        text = "AIAGNET 是一个融合 CrewAI、LangGraph、LangChain 的统一 AI 智能体平台。"
        r = client.post(
            f"/api/v1/knowledge/{kb_id}/documents",
            files={"file": ("smoke.txt", text.encode("utf-8"), "text/plain")},
        )
        if r.status_code >= 400:
            fail("knowledge/upload+search", f"upload {r.status_code}: {r.text[:200]}")
        else:
            r2 = client.post(f"/api/v1/knowledge/{kb_id}/search", json={"query": "融合哪些框架", "top_k": 3})
            hits = r2.json() if isinstance(r2.json(), list) else r2.json().get("results", [])
            ok("knowledge/upload+search", f"{len(hits)} hits, top={hits[0]['content'][:30] if hits else 'none'}")
    except Exception as e:
        fail("knowledge/upload+search", str(e))

    # 9. Workflows
    try:
        wfs = client.get("/api/v1/workflows/").json()
        ok("workflows/list", f"{len(wfs)} workflows")
        llm_wf = next((w for w in wfs if any(
            n.get("type", "").lower() in ("llmnode", "llm") for n in (w.get("graph_definition") or {}).get("nodes", [])
        )), wfs[0] if wfs else None)
        if llm_wf:
            r = client.post(f"/api/v1/workflows/{llm_wf['id']}/execute", json={"input_data": {"input": "简述 AI 发展趋势"}})
            out = r.json().get("output", {})
            ok("workflow/execute(llm)", f"status={r.json().get('status')}, out_len={len(str(out))}")
        else:
            skip("workflow/execute(llm)", "no workflow")
    except Exception as e:
        fail("workflow/execute(llm)", str(e))

    # 10. Orchestrator
    try:
        agents = client.get("/api/v1/agents/").json()
        if len(agents) >= 2:
            ids = [a["id"] for a in agents[:2]]
            r = client.post("/api/v1/orchestrator/run", json={
                "goal": "用一句话介绍 AIAGNET 平台",
                "process": "sequential",
                "agent_ids": ids,
                "tasks": [{"description": "用一句话介绍 AIAGNET 平台", "agent_id": ids[0]}],
            })
            ok("orchestrator/run", f"out_len={len(r.json().get('output',''))} in {r.json().get('elapsed_s')}s")
        else:
            skip("orchestrator/run", "need 2+ agents")
    except Exception as e:
        fail("orchestrator/run", str(e))

    print("\n" + "=" * 60)
    print(f"TOTAL: {PASS} passed, {FAIL} failed, {SKIP} skipped")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - {f}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
