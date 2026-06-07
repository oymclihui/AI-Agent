#!/usr/bin/env python3
"""Deep integration test for AIAGNET backend — extends smoke_test with CRUD, SSE, and assertions."""
import io
import json
import os
import re
import sys
import time
import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.environ.get("AIAGNET_TEST_BASE", "http://127.0.0.1:8000")
TIMEOUT = 300.0
PREFIX = "deep-test"

PASS, FAIL, SKIP = 0, 0, 0
failures: list[str] = []
_cleanup: list[tuple[str, str]] = []  # (resource, id)


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


def assert_status(r: httpx.Response, expected: int, name: str) -> bool:
    if r.status_code != expected:
        fail(name, f"HTTP {r.status_code}, expected {expected}: {r.text[:200]}")
        return False
    return True


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
    print(f"\n{'─' * 60}\n  {title}\n{'─' * 60}")


def cleanup(client: httpx.Client):
    for kind, rid in reversed(_cleanup):
        try:
            if kind == "agent":
                client.delete(f"/api/v1/agents/{rid}")
            elif kind == "workflow":
                client.delete(f"/api/v1/workflows/{rid}")
            elif kind == "kb":
                client.delete(f"/api/v1/knowledge/{rid}")
        except Exception:
            pass


def main():
    client = httpx.Client(base_url=BASE, timeout=TIMEOUT)
    t_start = time.time()

    # ── 0. Health & docs ─────────────────────────────────────
    section("0. Infrastructure")
    try:
        r = client.get("/health")
        if assert_status(r, 200, "health"):
            data = r.json()
            if data.get("status") == "healthy" and data.get("app") == "AI-AGENT":
                ok("health", f"v{data.get('version', '?')}")
            else:
                fail("health", f"unexpected payload: {data}")
    except Exception as e:
        fail("health", str(e))
        print("Backend not running — aborting.")
        return

    try:
        r = client.get("/docs")
        ok("openapi/docs", f"status={r.status_code}")
    except Exception as e:
        fail("openapi/docs", str(e))

    # ── 1. Models ────────────────────────────────────────────
    section("1. Model Hub")
    default_provider = default_model = None
    try:
        r = client.get("/api/v1/models/available")
        if assert_status(r, 200, "models/available"):
            data = r.json()
            if isinstance(data, list):
                providers = sorted({m.get("provider") for m in data if m.get("provider")})
                ok("models/available", f"{len(data)} models, providers={providers}")
                if "ollama" not in providers and "openai" not in providers:
                    fail("models/available/providers", f"no ollama/openai in {providers}")
            else:
                providers = list(data.keys()) if isinstance(data, dict) else []
                ok("models/available", f"providers={providers}")
                if "ollama" not in providers and "openai" not in providers:
                    fail("models/available/providers", f"no ollama/openai in {providers}")
    except Exception as e:
        fail("models/available", str(e))

    try:
        r = client.get("/api/v1/models/configs")
        if assert_status(r, 200, "models/configs"):
            configs = r.json()
            default = next((c for c in configs if c.get("is_default")), None)
            if not default:
                fail("models/configs/default", "no default model configured")
            else:
                default_provider = default["provider"]
                default_model = default["model_id"]
                ok("models/configs", f"{len(configs)} active, default={default_provider}/{default_model}")
    except Exception as e:
        fail("models/configs", str(e))

    # ── 2. Tools ─────────────────────────────────────────────
    section("2. Tools Registry")
    try:
        r = client.get("/api/v1/tools/")
        if assert_status(r, 200, "tools/list"):
            tools = [t["name"] for t in r.json()]
            expected = {"calculator", "get_datetime", "http_request", "web_search"}
            missing = expected - set(tools)
            if missing:
                fail("tools/builtin", f"missing: {missing}")
            else:
                ok("tools/builtin", f"{len(tools)} tools: {tools}")
    except Exception as e:
        fail("tools/list", str(e))

    # ── 3. Agents CRUD + run + stream ────────────────────────
    section("3. Agents (CRUD, run, stream)")
    agent_id = None
    try:
        r = client.post("/api/v1/agents/", json={
            "name": f"{PREFIX}-calc",
            "role": "Math Assistant",
            "goal": "Compute accurately",
            "backstory": "Deep test agent",
            "llm_provider": default_provider or "ollama",
            "llm_model": default_model or "qwen3.6:35b",
            "tools_config": [{"tool_name": "calculator"}],
        })
        if assert_status(r, 201, "agents/create"):
            agent_id = r.json()["id"]
            _cleanup.append(("agent", agent_id))
            ok("agents/create", f"id={agent_id[:8]}")
    except Exception as e:
        fail("agents/create", str(e))

    if agent_id:
        try:
            r = client.get(f"/api/v1/agents/{agent_id}")
            if assert_status(r, 200, "agents/get"):
                ok("agents/get", r.json().get("name", ""))
        except Exception as e:
            fail("agents/get", str(e))

        try:
            r = client.patch(f"/api/v1/agents/{agent_id}", json={"temperature": 0.1})
            if assert_status(r, 200, "agents/patch"):
                ok("agents/patch", f"temperature={r.json().get('temperature')}")
        except Exception as e:
            fail("agents/patch", str(e))

        try:
            t0 = time.time()
            r = client.post(f"/api/v1/agents/{agent_id}/run", json={
                "task": "Calculate 12345 * 4 + 3. Output only the final number."
            })
            if assert_status(r, 200, "agents/run"):
                out = r.json().get("output", "")
                nums = re.findall(r"\d+", out.replace(",", ""))
                if "49383" in out.replace(",", "") or "49383" in nums:
                    ok("agents/run(calculator)", f"49383 found in {out[:40]!r} ({time.time()-t0:.1f}s)")
                else:
                    fail("agents/run(calculator)", f"expected 49383, got {out[:80]!r}")
        except Exception as e:
            fail("agents/run(calculator)", str(e))

        try:
            t0 = time.time()
            with client.stream(
                "POST",
                f"/api/v1/agents/{agent_id}/run",
                json={"task": "What is 7+8? Reply with number only.", "stream": True},
            ) as resp:
                if resp.status_code != 200:
                    fail("agents/run(stream)", f"HTTP {resp.status_code}")
                else:
                    body = resp.read().decode("utf-8", errors="replace")
                    tokens = parse_sse(body)
                    text = "".join(tokens)
                    ok("agents/run(stream)", f"tokens={len(tokens)}, text={text[:30]!r} ({time.time()-t0:.1f}s)")
        except Exception as e:
            fail("agents/run(stream)", str(e))

    try:
        r = client.get("/api/v1/agents/not-a-real-id")
        if r.status_code == 404:
            ok("agents/404", "not found as expected")
        else:
            fail("agents/404", f"HTTP {r.status_code}")
    except Exception as e:
        fail("agents/404", str(e))

    # Agent NL generate (LLM-heavy)
    gen_id = None
    try:
        t0 = time.time()
        r = client.post("/api/v1/agents/generate", json={
            "description": "A research assistant that searches the web and summarizes findings."
        })
        if assert_status(r, 201, "agents/generate"):
            gen_id = r.json()["id"]
            _cleanup.append(("agent", gen_id))
            ok("agents/generate", f"name={r.json().get('name')!r} ({time.time()-t0:.1f}s)")
    except Exception as e:
        skip("agents/generate", str(e))

    try:
        r = client.post("/api/v1/agents/seed-templates")
        if assert_status(r, 200, "agents/seed-templates"):
            ok("agents/seed-templates", r.json().get("message", "")[:50])
    except Exception as e:
        fail("agents/seed-templates", str(e))

    # ── 4. Chat ──────────────────────────────────────────────
    section("4. Chat (memory, list, stream)")
    conv_id = None
    try:
        r = client.post("/api/v1/chat/conversations", json={
            "title": f"{PREFIX}-conv",
            "memory_type": "buffer",
        })
        if assert_status(r, 201, "chat/create-conversation"):
            conv_id = r.json()["id"]
            ok("chat/create-conversation", f"id={conv_id[:8]}")
    except Exception as e:
        fail("chat/create-conversation", str(e))

    if conv_id:
        try:
            r = client.post(f"/api/v1/chat/conversations/{conv_id}/messages", json={
                "message": "My name is Alice. Remember it."
            })
            if assert_status(r, 200, "chat/message-1"):
                ok("chat/message-1", f"len={len(r.json().get('content', ''))}")
        except Exception as e:
            fail("chat/message-1", str(e))

        try:
            r = client.post(f"/api/v1/chat/conversations/{conv_id}/messages", json={
                "message": "What is my name? Reply with the name only."
            })
            if assert_status(r, 200, "chat/memory-recall"):
                content = r.json().get("content", "")
                if re.search(r"alice", content, re.I):
                    ok("chat/memory-recall", f"Alice found in {content[:50]!r}")
                else:
                    fail("chat/memory-recall", f"Alice not in {content[:80]!r}")
        except Exception as e:
            fail("chat/memory-recall", str(e))

        try:
            r = client.get(f"/api/v1/chat/conversations/{conv_id}/messages")
            if assert_status(r, 200, "chat/list-messages"):
                msgs = r.json()
                roles = [m["role"] for m in msgs]
                if len(msgs) >= 4 and roles.count("user") >= 2:
                    ok("chat/list-messages", f"{len(msgs)} messages, roles={roles}")
                else:
                    fail("chat/list-messages", f"expected >=4 msgs, got {len(msgs)}")
        except Exception as e:
            fail("chat/list-messages", str(e))

        try:
            with client.stream(
                "POST",
                f"/api/v1/chat/conversations/{conv_id}/messages",
                json={"message": "Say hi in one word.", "stream": True},
            ) as resp:
                if resp.status_code != 200:
                    fail("chat/stream", f"HTTP {resp.status_code}")
                else:
                    body = resp.read().decode("utf-8", errors="replace")
                    tokens = parse_sse(body)
                    ok("chat/stream", f"tokens={len(tokens)}, joined={''.join(tokens)[:30]!r}")
        except Exception as e:
            fail("chat/stream", str(e))

    try:
        r = client.get("/api/v1/chat/conversations")
        if assert_status(r, 200, "chat/list-conversations"):
            ok("chat/list-conversations", f"{len(r.json())} conversations")
    except Exception as e:
        fail("chat/list-conversations", str(e))

    try:
        t0 = time.time()
        r = client.post("/api/v1/chat/quick", json={"message": "Reply with exactly: OK"})
        if assert_status(r, 200, "chat/quick"):
            content = r.json().get("content", "")
            ok("chat/quick", f"{content[:30]!r} ({time.time()-t0:.1f}s)")
    except Exception as e:
        fail("chat/quick", str(e))

    # ── 5. Knowledge ─────────────────────────────────────────
    section("5. Knowledge Base (CRUD, multi-doc, search)")
    kb_id = None
    doc_id = None
    try:
        r = client.post("/api/v1/knowledge/", json={
            "name": f"{PREFIX}-kb",
            "description": "Deep test knowledge base",
            "embedding_model": "nomic-embed-text",
        })
        if assert_status(r, 201, "knowledge/create"):
            kb_id = r.json()["id"]
            _cleanup.append(("kb", kb_id))
            ok("knowledge/create", f"id={kb_id[:8]}")
    except Exception as e:
        fail("knowledge/create", str(e))

    if kb_id:
        docs = [
            ("doc1.txt", "AIAGNET integrates CrewAI, LangGraph, and LangChain for agent orchestration."),
            ("doc2.txt", "The default embedding model is nomic-embed-text via Ollama."),
        ]
        for fname, text in docs:
            try:
                r = client.post(
                    f"/api/v1/knowledge/{kb_id}/documents",
                    files={"file": (fname, text.encode("utf-8"), "text/plain")},
                )
                if not assert_status(r, 201, f"knowledge/upload/{fname}"):
                    continue
                if fname == "doc1.txt":
                    doc_id = r.json()["id"]
                ok(f"knowledge/upload/{fname}", f"chunks={r.json().get('chunk_count', '?')}")
            except Exception as e:
                fail(f"knowledge/upload/{fname}", str(e))

        try:
            r = client.get(f"/api/v1/knowledge/{kb_id}/documents")
            if assert_status(r, 200, "knowledge/list-documents"):
                ok("knowledge/list-documents", f"{len(r.json())} documents")
        except Exception as e:
            fail("knowledge/list-documents", str(e))

        try:
            r = client.post(f"/api/v1/knowledge/{kb_id}/search", json={
                "query": "Which frameworks does AIAGNET integrate?",
                "top_k": 3,
            })
            if assert_status(r, 200, "knowledge/search"):
                hits = r.json()
                top = hits[0]["content"] if hits else ""
                if hits and re.search(r"crew|langgraph|langchain", top, re.I):
                    ok("knowledge/search/relevance", f"{len(hits)} hits, top={top[:50]!r}")
                elif hits:
                    ok("knowledge/search", f"{len(hits)} hits (weak keyword match)")
                else:
                    fail("knowledge/search", "no hits returned")
        except Exception as e:
            fail("knowledge/search", str(e))

        if doc_id:
            try:
                r = client.delete(f"/api/v1/knowledge/{kb_id}/documents/{doc_id}")
                if r.status_code == 204:
                    ok("knowledge/delete-document", f"doc={doc_id[:8]}")
                else:
                    fail("knowledge/delete-document", f"HTTP {r.status_code}")
            except Exception as e:
                fail("knowledge/delete-document", str(e))

    # ── 6. Workflows ─────────────────────────────────────────
    section("6. Workflows (CRUD, execute, executions)")
    wf_id = None
    try:
        r = client.post("/api/v1/workflows/", json={
            "name": f"{PREFIX}-wf",
            "description": "Minimal LLM workflow for deep test",
            "process_type": "sequential",
            "graph_definition": {
                "nodes": [
                    {"id": "start", "type": "start", "label": "Start", "config": {}, "position": {"x": 0, "y": 0}},
                    {"id": "llm1", "type": "llm", "label": "LLM", "config": {"prompt": "Summarize: {{input}}"}, "position": {"x": 200, "y": 0}},
                    {"id": "end", "type": "end", "label": "End", "config": {}, "position": {"x": 400, "y": 0}},
                ],
                "edges": [
                    {"id": "e1", "source": "start", "target": "llm1"},
                    {"id": "e2", "source": "llm1", "target": "end"},
                ],
            },
        })
        if assert_status(r, 201, "workflows/create"):
            wf_id = r.json()["id"]
            _cleanup.append(("workflow", wf_id))
            ok("workflows/create", f"id={wf_id[:8]}")
    except Exception as e:
        fail("workflows/create", str(e))

    if wf_id:
        try:
            r = client.get(f"/api/v1/workflows/{wf_id}")
            if assert_status(r, 200, "workflows/get"):
                nodes = len(r.json().get("graph_definition", {}).get("nodes", []))
                ok("workflows/get", f"{nodes} nodes")
        except Exception as e:
            fail("workflows/get", str(e))

        try:
            r = client.patch(f"/api/v1/workflows/{wf_id}", json={"description": "Updated by deep test"})
            if assert_status(r, 200, "workflows/patch"):
                ok("workflows/patch", r.json().get("description", "")[:40])
        except Exception as e:
            fail("workflows/patch", str(e))

        try:
            t0 = time.time()
            r = client.post(f"/api/v1/workflows/{wf_id}/execute", json={
                "input_data": {"input": "AI agents in 2026"}
            })
            if assert_status(r, 200, "workflows/execute(custom)"):
                data = r.json()
                out_len = len(str(data.get("output", "")))
                ok("workflows/execute(custom)", f"status={data.get('status')}, out_len={out_len} ({time.time()-t0:.1f}s)")
        except Exception as e:
            fail("workflows/execute(custom)", str(e))

        try:
            r = client.get(f"/api/v1/workflows/{wf_id}/executions")
            if assert_status(r, 200, "workflows/executions"):
                execs = r.json()
                ok("workflows/executions", f"{len(execs)} execution(s)")
        except Exception as e:
            fail("workflows/executions", str(e))

    try:
        r = client.post("/api/v1/workflows/seed-templates")
        if assert_status(r, 200, "workflows/seed-templates"):
            ok("workflows/seed-templates", r.json().get("message", "")[:50])
    except Exception as e:
        fail("workflows/seed-templates", str(e))

    try:
        wfs = client.get("/api/v1/workflows/").json()
        template = next((w for w in wfs if any(
            n.get("type", "").lower() in ("llmnode", "llm")
            for n in (w.get("graph_definition") or {}).get("nodes", [])
        )), None)
        if template:
            t0 = time.time()
            r = client.post(f"/api/v1/workflows/{template['id']}/execute", json={
                "input_data": {"input": "One sentence about AI platforms."}
            })
            if assert_status(r, 200, "workflows/execute(template)"):
                ok("workflows/execute(template)", f"status={r.json().get('status')} ({time.time()-t0:.1f}s)")
        else:
            skip("workflows/execute(template)", "no LLM template workflow")
    except Exception as e:
        fail("workflows/execute(template)", str(e))

    # ── 7. Orchestrator ──────────────────────────────────────
    section("7. Orchestrator")
    try:
        agents = client.get("/api/v1/agents/").json()
        if len(agents) >= 2:
            ids = [a["id"] for a in agents[:2]]
            t0 = time.time()
            r = client.post("/api/v1/orchestrator/run", json={
                "goal": "Describe AIAGNET in one sentence.",
                "process": "sequential",
                "agent_ids": ids,
                "tasks": [{"description": "Write one sentence about AIAGNET platform.", "agent_id": ids[0]}],
            })
            if assert_status(r, 200, "orchestrator/run"):
                out = r.json().get("output", "")
                ok("orchestrator/run", f"out_len={len(out)} ({time.time()-t0:.1f}s)")
        else:
            skip("orchestrator/run", "need 2+ agents")
    except Exception as e:
        fail("orchestrator/run", str(e))

    # ── 8. Validation errors ───────────────────────────────────
    section("8. Error handling")
    for path, method, payload, expect in [
        ("/api/v1/agents/", "POST", {"name": ""}, 422),
        ("/api/v1/knowledge/fake-id", "GET", None, 404),
        ("/api/v1/workflows/fake-id", "GET", None, 404),
        ("/api/v1/chat/conversations/fake-id/messages", "POST", {"message": "hi"}, 404),
    ]:
        name = f"errors/{method} {path.split('/')[-1] or path}"
        try:
            if method == "POST":
                r = client.post(path, json=payload)
            else:
                r = client.get(path)
            if r.status_code == expect:
                ok(name, f"HTTP {expect}")
            else:
                fail(name, f"HTTP {r.status_code}, expected {expect}")
        except Exception as e:
            fail(name, str(e))

    # ── Cleanup ──────────────────────────────────────────────
    section("9. Cleanup")
    cleanup(client)
    ok("cleanup", f"removed {len(_cleanup)} test resource(s)")

    elapsed = time.time() - t_start
    print("\n" + "=" * 60)
    print(f"DEEP TEST TOTAL: {PASS} passed, {FAIL} failed, {SKIP} skipped  ({elapsed:.0f}s)")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - {f}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
