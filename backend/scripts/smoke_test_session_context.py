"""Smoke tests for SessionContext P0: skills_config, PATCH context, RAG wiring, admin delete."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import bootstrap_backend

bootstrap_backend()

import httpx
from app.main import app

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    line = f"  [{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)


async def main() -> int:
    print("=== SessionContext P0 Smoke Test (ASGI in-process) ===\n")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1", timeout=180.0) as client:
        # 1. Routes
        paths = [getattr(r, "path", "") for r in app.routes if getattr(r, "path", None)]
        ctx_get = any("/chat/conversations/{conv_id}" in p and "context" not in p for p in paths)
        ctx_patch = any("context" in p and "conversations" in p for p in paths)
        record("route GET /chat/conversations/{id}", ctx_get, "registered" if ctx_get else "missing")
        record("route PATCH .../context", ctx_patch, "registered" if ctx_patch else "missing")

        # 2. Auth
        login = await client.post("/auth/login", json={"login": "admin", "password": "admin123"})
        record("auth login (admin)", login.status_code == 200, str(login.status_code))
        if login.status_code != 200:
            return 1
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        me = await client.get("/auth/me", headers=headers)
        is_admin = me.json().get("is_admin") is True if me.status_code == 200 else False
        record("auth/me is_admin", is_admin, str(me.json().get("is_admin")))

        # 3. Pick skill + KB + agent for context tests
        skill_id = None
        skills = await client.get("/skills/", headers=headers, params={"lang": "zh"})
        if skills.status_code == 200:
            active = [s for s in skills.json() if s.get("status") == "active"]
            skill_id = active[0]["id"] if active else None
        record("skills list", skills.status_code == 200 and bool(skill_id), f"skill={skill_id[:8] if skill_id else 'none'}")

        kb_id = None
        kbs = await client.get("/knowledge/", headers=headers)
        if kbs.status_code == 200 and kbs.json():
            kb_id = kbs.json()[0]["id"]
        record("knowledge list", kbs.status_code == 200, f"kb={kb_id[:8] if kb_id else 'none'}")

        agent_id = None
        agents = await client.get("/agents/", headers=headers, params={"lang": "zh"})
        if agents.status_code == 200 and agents.json():
            agent_id = agents.json()[0]["id"]
        record("agents list", agents.status_code == 200, f"agent={agent_id[:8] if agent_id else 'none'}")

        # 4. Create conversation with skills_config
        skills_config = [{"skill_id": skill_id, "always_load": True, "priority": 0}] if skill_id else []
        kb_ids = [kb_id] if kb_id else []
        create_body = {
            "title": "SessionContext冒烟",
            "agent_id": agent_id,
            "knowledge_base_ids": kb_ids,
            "skills_config": skills_config,
        }
        conv = await client.post("/chat/conversations", headers=headers, json=create_body)
        record("POST conversation w/ skills_config", conv.status_code == 201, conv.text[:80])
        if conv.status_code != 201:
            return 1
        conv_id = conv.json()["id"]
        data = conv.json()
        ok_create = (
            (not skill_id or any(s.get("skill_id") == skill_id for s in data.get("skills_config") or []))
            and data.get("knowledge_base_ids") == kb_ids
        )
        record("response includes skills_config", ok_create, f"skills={len(data.get('skills_config') or [])} kbs={len(data.get('knowledge_base_ids') or [])}")

        # 5. GET conversation
        got = await client.get(f"/chat/conversations/{conv_id}", headers=headers)
        record("GET conversation", got.status_code == 200, str(got.status_code))
        if got.status_code == 200:
            g = got.json()
            record(
                "GET returns skills_config",
                "skills_config" in g and isinstance(g["skills_config"], list),
                f"n={len(g.get('skills_config') or [])}",
            )

        # 6. PATCH context — clear skill, set KB only, then restore skill
        patch1 = await client.patch(
            f"/chat/conversations/{conv_id}/context",
            headers=headers,
            json={"skills_config": [], "knowledge_base_ids": kb_ids},
        )
        record("PATCH context clear skills", patch1.status_code == 200, str(patch1.status_code))
        if patch1.status_code == 200:
            record(
                "PATCH skills cleared",
                len(patch1.json().get("skills_config") or []) == 0,
                str(len(patch1.json().get("skills_config") or [])),
            )

        if skill_id:
            patch2 = await client.patch(
                f"/chat/conversations/{conv_id}/context",
                headers=headers,
                json={
                    "skills_config": [{"skill_id": skill_id, "always_load": True, "priority": 0}],
                    "agent_id": agent_id,
                },
            )
            ok_patch = patch2.status_code == 200 and any(
                s.get("skill_id") == skill_id for s in (patch2.json().get("skills_config") or [])
            )
            record("PATCH context restore skill+agent", ok_patch, patch2.text[:80])

        # 7. Chat message (skill-only context, KB for RAG) — 502 acceptable if LLM offline
        if skill_id or kb_id:
            msg = await client.post(
                f"/chat/conversations/{conv_id}/messages",
                headers=headers,
                json={"message": "用一句话说明当前会话绑定了哪些上下文。", "stream": False},
            )
            if msg.status_code == 200:
                rag = msg.json().get("rag_used")
                record("POST message (LLM ok)", True, f"rag_used={rag}")
            elif msg.status_code == 502:
                record("POST message (LLM offline)", True, "502 — LLM unreachable, endpoint OK")
            else:
                record("POST message", False, f"status={msg.status_code} {msg.text[:120]}")

        # 8. Admin delete permission — create disposable skill, delete as admin
        temp_slug = f"smoke-ctx-{conv_id[:8]}"
        created_skill_id = None
        create_skill = await client.post(
            "/skills/",
            headers=headers,
            json={
                "slug": temp_slug,
                "display_name": "SessionContext Smoke Temp",
                "description": "temp for smoke test",
                "instructions_md": "## Test\nSmoke only.",
                "status": "draft",
            },
        )
        if create_skill.status_code in (200, 201):
            created_skill_id = create_skill.json().get("id")
            del_resp = await client.delete(f"/skills/{created_skill_id}", headers=headers)
            record("admin delete skill", del_resp.status_code == 204, str(del_resp.status_code))
        else:
            record("admin delete skill", False, create_skill.text[:120])

        # 9. suggest-deposit + confirm skill (endpoint shape; LLM may skip confirm body)
        suggest = await client.post(
            f"/chat/conversations/{conv_id}/suggest-deposit",
            headers=headers,
            json={"lang": "zh"},
        )
        record("suggest-deposit", suggest.status_code == 200, f"status={suggest.status_code}")
        if suggest.status_code == 200:
            sdata = suggest.json()
            draft_id = sdata.get("draft_id")
            if draft_id and sdata.get("worth_deposit"):
                confirm = await client.post(
                    f"/chat/conversations/{conv_id}/deposit/confirm",
                    headers=headers,
                    json={"draft_id": draft_id, "types": ["skill"], "activate_employee": False},
                )
                if confirm.status_code == 200:
                    cdata = confirm.json()
                    record("deposit/confirm skill", bool(cdata.get("skill_id")), str(cdata)[:120])
                    # verify conv updated after deposit
                    after = await client.get(f"/chat/conversations/{conv_id}", headers=headers)
                    if after.status_code == 200:
                        n_skills = len(after.json().get("skills_config") or [])
                        record("deposit writes conv.skills_config", n_skills > 0, f"n={n_skills}")
                elif confirm.status_code == 502:
                    record("deposit/confirm skill", True, "502 LLM — endpoint reachable")
                else:
                    record("deposit/confirm skill", False, confirm.text[:120])
            else:
                record("deposit/confirm skill", True, "skipped — not worth_deposit (need more messages)")

        # 10. Cleanup conversation
        cleanup = await client.delete(f"/chat/conversations/{conv_id}", headers=headers)
        record("delete conversation", cleanup.status_code == 200, str(cleanup.status_code))

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n=== Summary: {passed} passed, {failed} failed / {len(RESULTS)} total ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
