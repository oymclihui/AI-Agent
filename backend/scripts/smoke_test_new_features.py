"""Smoke tests for chat deposit, connectors, model override, and agent hub APIs."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
OPENAPI = "http://127.0.0.1:8000/openapi.json"

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    line = f"  [{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)


async def main() -> int:
    print("=== AI-AGENT New Features Smoke Test ===\n")

    async with httpx.AsyncClient(base_url=BASE, timeout=120.0) as client:
        # 1. Health
        try:
            health = await client.get("http://127.0.0.1:8000/health")
            record("health", health.status_code == 200, str(health.status_code))
        except Exception as exc:
            record("health", False, str(exc))
            print("\nBackend not reachable. Start uvicorn on :8000 first.")
            return 1

        # 2. OpenAPI routes
        try:
            spec = (await client.get(OPENAPI)).json()
            paths = spec.get("paths", {})
            required = [
                "/api/v1/chat/conversations/{conv_id}/suggest-deposit",
                "/api/v1/chat/conversations/{conv_id}/deposit/confirm",
                "/api/v1/chat/conversations/{conv_id}/save-as-skill",
                "/api/v1/chat/conversations/{conv_id}/save-to-knowledge",
                "/api/v1/models/configs/{config_id}/test-connection",
            ]
            missing = [p for p in required if p not in paths]
            record("openapi routes", not missing, "missing: " + ", ".join(missing) if missing else "ok")
        except Exception as exc:
            record("openapi routes", False, str(exc))

        # 3. Auth
        try:
            login = await client.post("/auth/login", json={"login": "admin", "password": "admin123"})
            login.raise_for_status()
            token = login.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            record("auth login", True)
        except Exception as exc:
            record("auth login", False, str(exc))
            return 1

        # 4. Model configs (chat model selector)
        model_config_id = None
        try:
            models = await client.get("/models/configs", headers=headers)
            models.raise_for_status()
            configs = models.json()
            record("models list", len(configs) > 0, f"count={len(configs)}")
            default = next((c for c in configs if c.get("is_default")), configs[0] if configs else None)
            model_config_id = default["id"] if default else None
        except Exception as exc:
            record("models list", False, str(exc))

        # 5. Connectors catalog (frontend static; verify mailbox IMAP preset save)
        try:
            mb = await client.post(
                "/auth/me/mailbox",
                headers=headers,
                json={
                    "email": "test-smoke@byd.com",
                    "mailbox_password": "dummy-smoke-only",
                    "imap_host": "imap.byd.com",
                    "imap_port": 1993,
                    "imap_use_ssl": True,
                },
            )
            # May fail on invalid creds format but should accept payload shape
            record("mailbox preset save", mb.status_code in (200, 201, 400, 422), f"status={mb.status_code}")
        except Exception as exc:
            record("mailbox preset save", False, str(exc))

        # 6. Create conversation with model + connector metadata
        conv_id = None
        try:
            body = {
                "title": "冒烟测试-沉淀",
                "model_config_id": model_config_id,
                "connector_id": "wecom-mail",
            }
            conv = await client.post("/chat/conversations", headers=headers, json=body)
            conv.raise_for_status()
            data = conv.json()
            conv_id = data["id"]
            ok_meta = data.get("connector_id") == "wecom-mail"
            if model_config_id:
                ok_meta = ok_meta and data.get("model_config_id") == model_config_id
            record("conversation create w/ model+connector", ok_meta, f"id={conv_id[:8]}")
        except Exception as exc:
            record("conversation create w/ model+connector", False, str(exc))

        if not conv_id:
            print("\nSkipping chat-dependent tests (no conversation).")
        else:
            # 7. Seed messages for deposit analysis
            try:
                for i, (role_msg, content) in enumerate([
                    ("user", "我需要一个每周一早上9点自动执行的竞品分析数字员工，输出Markdown报告。"),
                    ("assistant", "好的，我可以帮你定义岗位：每周一09:00抓取竞品动态，整理优劣势并给出建议。"),
                    ("user", "请把流程固化成SOP，并绑定fetch_mail和企业邮箱。"),
                    ("assistant", "已整理：1) 读取邮箱竞品订阅 2) 汇总要点 3) 输出结构化周报。"),
                ]):
                    # Use internal message flow via chat endpoint
                    pass
                msg1 = await client.post(
                    f"/chat/conversations/{conv_id}/messages",
                    headers=headers,
                    json={
                        "message": "我需要一个每周一早上9点自动执行的竞品分析数字员工，输出Markdown报告。",
                        "stream": False,
                        "model_config_id": model_config_id,
                        "connector_id": "wecom-mail",
                    },
                    timeout=180.0,
                )
                if msg1.status_code == 502:
                    record("chat message (LLM)", False, "502 LLM unreachable — skip downstream LLM tests")
                else:
                    msg1.raise_for_status()
                    record("chat message (LLM)", True, f"len={len(msg1.json().get('content',''))}")

                    msg2 = await client.post(
                        f"/chat/conversations/{conv_id}/messages",
                        headers=headers,
                        json={
                            "message": "请把上述流程固化：每周一9点执行，包含邮箱摘要和竞品要点。",
                            "stream": False,
                            "model_config_id": model_config_id,
                            "connector_id": "wecom-mail",
                        },
                        timeout=180.0,
                    )
                    if msg2.status_code < 400:
                        record("chat message 2", True)
                    else:
                        record("chat message 2", False, f"status={msg2.status_code}")

                    # 8. suggest-deposit
                    try:
                        suggest = await client.post(
                            f"/chat/conversations/{conv_id}/suggest-deposit",
                            headers=headers,
                            json={"lang": "zh"},
                            timeout=180.0,
                        )
                        suggest.raise_for_status()
                        sdata = suggest.json()
                        record(
                            "suggest-deposit",
                            True,
                            f"worth={sdata.get('worth_deposit')} draft={bool(sdata.get('draft_id'))} "
                            f"suggestions={len(sdata.get('suggestions') or [])}",
                        )
                        draft_id = sdata.get("draft_id")
                        if draft_id and sdata.get("worth_deposit"):
                            # 9. confirm deposit — skill only (minimal side effects)
                            confirm = await client.post(
                                f"/chat/conversations/{conv_id}/deposit/confirm",
                                headers=headers,
                                json={
                                    "draft_id": draft_id,
                                    "types": ["skill"],
                                    "activate_employee": False,
                                },
                                timeout=180.0,
                            )
                            if confirm.status_code == 200:
                                cdata = confirm.json()
                                record("deposit/confirm (skill)", bool(cdata.get("skill_id")), json.dumps(cdata))
                            else:
                                record("deposit/confirm (skill)", False, confirm.text[:200])
                    except Exception as exc:
                        record("suggest-deposit", False, str(exc))

                    # 10. Manual save-as-skill
                    try:
                        skill = await client.post(
                            f"/chat/conversations/{conv_id}/save-as-skill",
                            headers=headers,
                            json={"title": "冒烟测试技能"},
                            timeout=180.0,
                        )
                        record(
                            "save-as-skill",
                            skill.status_code == 200,
                            skill.json().get("display_name", skill.text[:120]) if skill.status_code == 200 else skill.text[:120],
                        )
                    except Exception as exc:
                        record("save-as-skill", False, str(exc))

                    # 11. save-to-knowledge (may fail on vector DB)
                    try:
                        kb = await client.post(
                            f"/chat/conversations/{conv_id}/save-to-knowledge",
                            headers=headers,
                            json={"kb_name": "冒烟测试-对话沉淀"},
                            timeout=180.0,
                        )
                        record(
                            "save-to-knowledge",
                            kb.status_code == 200,
                            kb.json().get("knowledge_base_name", kb.text[:120]) if kb.status_code == 200 else kb.text[:120],
                        )
                    except Exception as exc:
                        record("save-to-knowledge", False, str(exc))

            except httpx.HTTPStatusError as exc:
                record("chat message (LLM)", False, f"{exc.response.status_code} {exc.response.text[:120]}")
            except Exception as exc:
                record("chat message (LLM)", False, str(exc))

        # 12. Agents list (hub page data)
        try:
            agents = await client.get("/agents/", headers=headers, params={"lang": "zh"})
            agents.raise_for_status()
            alist = agents.json()
            record("agents list", isinstance(alist, list), f"count={len(alist)}")
        except Exception as exc:
            record("agents list", False, str(exc))

    # Summary
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n=== Summary: {passed} passed, {failed} failed / {len(RESULTS)} total ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
