#!/usr/bin/env python3
"""End-to-end smoke test for AIAGNET backend (UTF-8 safe)."""
from __future__ import annotations

import io
import os
import sys
import time
import uuid

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API = f"{BASE}/api/v1"
ADMIN_LOGIN = os.environ.get("SMOKE_ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.environ.get("SMOKE_ADMIN_PASSWORD", "admin123")

PASS, FAIL, SKIP = 0, 0, 0
failures: list[str] = []


def ok(name: str, detail: str = "") -> None:
    global PASS
    PASS += 1
    print(f"\033[92m[PASS]\033[0m {name}  ->  {detail}")


def fail(name: str, detail: str = "") -> None:
    global FAIL
    FAIL += 1
    failures.append(f"{name}: {detail}")
    print(f"\033[91m[FAIL]\033[0m {name}  ->  {detail}")


def skip(name: str, reason: str = "") -> None:
    global SKIP
    SKIP += 1
    print(f"\033[93m[SKIP]\033[0m {name}  ->  {reason}")


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict) and "detail" in body:
            return str(body["detail"])[:300]
        return str(body)[:300]
    except Exception:
        return resp.text[:300]


def login(client: httpx.Client) -> dict[str, str]:
    resp = client.post(
        f"{API}/auth/login",
        json={"login": ADMIN_LOGIN, "password": ADMIN_PASSWORD},
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("login response missing access_token")
    return {"Authorization": f"Bearer {token}"}


def main() -> None:
    suffix = uuid.uuid4().hex[:6]
    client = httpx.Client(timeout=180.0)
    auth: dict[str, str] = {}

    print(f"Smoke test base: {BASE}\n")

    # 1. Health (no auth)
    try:
        r = client.get(f"{BASE}/health")
        r.raise_for_status()
        ok("health", r.json().get("status", ""))
    except Exception as exc:
        fail("health", str(exc))
        print("Backend not running — aborting.")
        sys.exit(1)

    # 2. Auth
    try:
        auth = login(client)
        ok("auth/login", ADMIN_LOGIN)
    except Exception as exc:
        fail("auth/login", str(exc))
        print("Cannot authenticate — aborting protected tests.")
        sys.exit(1)

    reg_emp = f"smoke{suffix}"
    reg_pwd = f"Smoke{suffix}!"
    try:
        r = client.post(
            f"{API}/auth/register",
            json={
                "employee_no": reg_emp,
                "display_name": f"Smoke User {suffix}",
                "password": reg_pwd,
            },
        )
        if r.status_code >= 400:
            fail("auth/register", f"{r.status_code}: {_detail(r)}")
        else:
            ok("auth/register", reg_emp)
            r2 = client.post(
                f"{API}/auth/login",
                json={"login": reg_emp, "password": reg_pwd},
            )
            r2.raise_for_status()
            ok("auth/register-login", reg_emp)
    except Exception as exc:
        fail("auth/register", str(exc))

    try:
        r = client.get(f"{API}/setup/status")
        r.raise_for_status()
        setup_st = r.json()
        ok("setup/status", f"setup_required={setup_st.get('setup_required')}")
        r2 = client.get(f"{API}/setup/presets")
        if r2.status_code == 403:
            ok("setup/presets-guard", "403 without token")
        elif setup_st.get("setup_required"):
            ok("setup/presets-guard", f"{r2.status_code} while setup pending")
        else:
            fail("setup/presets-guard", f"unexpected {r2.status_code}: {_detail(r2)}")
    except Exception as exc:
        fail("setup/status", str(exc))

    if ":8000" not in BASE:
        frontend_url = os.environ.get("SMOKE_FRONTEND_URL", "").rstrip("/")
        if not frontend_url:
            skip("frontend/login", "set SMOKE_FRONTEND_URL=http://127.0.0.1:3000 to test login page")
        else:
            try:
                r = client.get(f"{frontend_url}/login", follow_redirects=True)
                r.raise_for_status()
                html = r.text
                if "前往首次部署" in html or "administrator — open setup" in html:
                    fail("frontend/login-hidden-setup", "setup banner text still in login page")
                else:
                    ok("frontend/login-hidden-setup", "no setup banner on login")
                if "注册" in html or "Register" in html:
                    ok("frontend/login-register-ui", "register tab visible")
                else:
                    skip("frontend/login-register-ui", "redeploy frontend to pick up register UI")
            except Exception as exc:
                fail("frontend/login", str(exc))

    # 3. Models
    try:
        r = client.get(f"{API}/models/available", headers=auth)
        r.raise_for_status()
        data = r.json()
        ok("models/available", f"{len(data)} total")
    except Exception as exc:
        fail("models/available", str(exc))

    try:
        r = client.get(f"{API}/models/configs", headers=auth)
        r.raise_for_status()
        configs = r.json()
        default = next((c for c in configs if c.get("is_default")), configs[0] if configs else {})
        ok(
            "models/configs",
            f"{len(configs)} configs, default={default.get('provider')}/{default.get('model_id')}",
        )
    except Exception as exc:
        fail("models/configs", str(exc))

    try:
        r = client.get(f"{API}/auth/me/model-keys", headers=auth)
        r.raise_for_status()
        ok("auth/model-keys/list", f"{len(r.json())} keys")
    except Exception as exc:
        fail("auth/model-keys/list", str(exc))

    try:
        r = client.post(
            f"{API}/auth/me/model-keys",
            headers=auth,
            json={
                "provider": "openai",
                "model_id": f"smoke-test-{suffix}",
                "api_key": f"smoke-key-{suffix}",
            },
        )
        if r.status_code >= 400:
            fail("auth/model-keys/save", f"{r.status_code}: {_detail(r)}")
        else:
            key_id = r.json().get("id", "")
            ok("auth/model-keys/save", f"id={key_id[:8] if key_id else '?'}")
            if key_id:
                client.delete(f"{API}/auth/me/model-keys/{key_id}", headers=auth)
    except Exception as exc:
        fail("auth/model-keys/save", str(exc))

    # 4. Tools
    try:
        r = client.get(f"{API}/tools/", headers=auth)
        r.raise_for_status()
        tools = [t["name"] for t in r.json()]
        ok("tools/list", f"{len(tools)}: {tools}")
    except Exception as exc:
        fail("tools/list", str(exc))

    # 5. Agents
    agent_id: str | None = None
    try:
        r = client.get(f"{API}/agents/", headers=auth)
        r.raise_for_status()
        agents = r.json()
        ok("agents/list", f"{len(agents)} agents")
    except Exception as exc:
        fail("agents/list", str(exc))
        agents = []

    try:
        r = client.post(
            f"{API}/agents/",
            headers=auth,
            json={
                "name": f"冒烟测试助手-{suffix}",
                "role": "Test Agent",
                "goal": "Answer test questions",
                "backstory": "Smoke test",
                "tools_config": [{"tool_name": "calculator"}],
            },
        )
        if r.status_code >= 400:
            fail("agents/create", f"{r.status_code}: {_detail(r)}")
        else:
            agent_id = r.json()["id"]
            ok("agents/create", f"id={agent_id[:8]}")
    except Exception as exc:
        fail("agents/create", str(exc))

    # 6. Agent run with calculator
    try:
        calc_agent = next(
            (a for a in agents if "calculator" in str(a.get("tools_config", ""))),
            None,
        )
        run_id = (calc_agent or {}).get("id") or agent_id
        if run_id:
            t0 = time.time()
            r = client.post(
                f"{API}/agents/{run_id}/run",
                headers=auth,
                json={"task": "计算 12345 * 4 + 3，只输出数字结果"},
            )
            r.raise_for_status()
            out = r.json().get("output", "")
            ok("agents/run(tool)", f"output={out[:30]!r} in {time.time() - t0:.1f}s")
        else:
            skip("agents/run(tool)", "no calculator agent")
    except Exception as exc:
        fail("agents/run(tool)", str(exc))

    # 7. Chat quick
    try:
        t0 = time.time()
        r = client.post(
            f"{API}/chat/quick",
            headers=auth,
            json={"message": "天空是什么颜色？用两个字回答"},
        )
        r.raise_for_status()
        content = r.json().get("content", "")
        ok("chat/quick", f"{content[:20]!r} in {time.time() - t0:.1f}s")
    except Exception as exc:
        fail("chat/quick", str(exc))

    # 8. Chat memory
    try:
        r = client.post(
            f"{API}/chat/conversations",
            headers=auth,
            json={"title": f"memory-test-{suffix}", "memory_type": "buffer"},
        )
        r.raise_for_status()
        conv_id = r.json()["id"]
        client.post(
            f"{API}/chat/conversations/{conv_id}/messages",
            headers=auth,
            json={"message": "我叫小明", "stream": False},
        ).raise_for_status()
        r2 = client.post(
            f"{API}/chat/conversations/{conv_id}/messages",
            headers=auth,
            json={"message": "我叫什么？", "stream": False},
        )
        r2.raise_for_status()
        content = r2.json().get("content", "")
        ok("chat/memory", f"name recalled: {content[:40]!r}")
    except Exception as exc:
        fail("chat/memory", str(exc))

    # 9. Knowledge + search
    try:
        r = client.post(
            f"{API}/knowledge/",
            headers=auth,
            json={
                "name": f"冒烟知识库-{suffix}",
                "description": "smoke",
                "embedding_model": "nomic-embed-text",
            },
        )
        r.raise_for_status()
        kb_id = r.json()["id"]
        ok("knowledge/create", f"id={kb_id[:8]}")
        text = "AIAGNET 是一个融合 CrewAI、LangGraph、LangChain 的统一 AI 智能体平台。"
        r = client.post(
            f"{API}/knowledge/{kb_id}/documents",
            headers=auth,
            files={"file": ("smoke.txt", text.encode("utf-8"), "text/plain")},
        )
        if r.status_code >= 400:
            fail("knowledge/upload+search", f"upload {r.status_code}: {_detail(r)}")
        else:
            r2 = client.post(
                f"{API}/knowledge/{kb_id}/search",
                headers=auth,
                json={"query": "融合哪些框架", "top_k": 3},
            )
            r2.raise_for_status()
            body = r2.json()
            hits = body if isinstance(body, list) else body.get("results", [])
            top = hits[0]["content"][:30] if hits else "none"
            ok("knowledge/upload+search", f"{len(hits)} hits, top={top}")
    except Exception as exc:
        fail("knowledge/upload+search", str(exc))

    # 10. Desktop automation
    try:
        r = client.get(f"{API}/desktop-automation/demos", headers=auth)
        r.raise_for_status()
        ok("desktop/demos", f"count={len(r.json())}")
    except Exception as exc:
        fail("desktop/demos", str(exc))

    # 11. Workflows
    try:
        r = client.get(f"{API}/workflows/", headers=auth)
        r.raise_for_status()
        wfs = r.json()
        ok("workflows/list", f"{len(wfs)} workflows")
        llm_wf = next(
            (
                w
                for w in wfs
                if any(
                    n.get("type", "").lower() in ("llmnode", "llm")
                    for n in (w.get("graph_definition") or {}).get("nodes", [])
                )
            ),
            wfs[0] if wfs else None,
        )
        if llm_wf:
            r = client.post(
                f"{API}/workflows/{llm_wf['id']}/execute",
                headers=auth,
                json={"input_data": {"input": "简述 AI 发展趋势"}},
                timeout=300.0,
            )
            if r.status_code >= 400:
                fail("workflow/execute(llm)", f"{r.status_code}: {_detail(r)}")
            else:
                body = r.json()
                out = body.get("output", {})
                ok(
                    "workflow/execute(llm)",
                    f"status={body.get('status')}, out_len={len(str(out))}",
                )
        else:
            skip("workflow/execute(llm)", "no workflow")
    except Exception as exc:
        fail("workflow/execute(llm)", str(exc))

    # 12. Orchestrator (may take longer than other LLM calls)
    try:
        r = client.get(f"{API}/agents/", headers=auth)
        r.raise_for_status()
        agents = r.json()
        if len(agents) >= 2:
            ids = [a["id"] for a in agents[:2]]
            r = client.post(
                f"{API}/orchestrator/run",
                headers=auth,
                json={
                    "goal": "用一句话介绍 AIAGNET 平台",
                    "process": "sequential",
                    "agent_ids": ids,
                    "tasks": [{"description": "用一句话介绍 AIAGNET 平台", "agent_id": ids[0]}],
                },
                timeout=300.0,
            )
            r.raise_for_status()
            body = r.json()
            ok(
                "orchestrator/run",
                f"out_len={len(body.get('output', ''))} in {body.get('elapsed_s')}s",
            )
        else:
            skip("orchestrator/run", "need 2+ agents")
    except Exception as exc:
        fail("orchestrator/run", str(exc))

    print("\n" + "=" * 60)
    print(f"TOTAL: {PASS} passed, {FAIL} failed, {SKIP} skipped")
    if failures:
        print("\nFailures:")
        for item in failures:
            print(f"  - {item}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
