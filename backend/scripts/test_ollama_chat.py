#!/usr/bin/env python3
"""Quick chat smoke test against Ollama on server."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

BASE = "http://127.0.0.1:8000/api/v1"


async def main() -> int:
    async with httpx.AsyncClient(timeout=120.0) as client:
        login = await client.post(f"{BASE}/auth/login", json={"login": "admin", "password": "admin123"})
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        models = (await client.get(f"{BASE}/models/configs", headers=headers)).json()
        default = next((m for m in models if m.get("is_default")), None)
        ollama = next(
            (m for m in models if m.get("provider") == "ollama" and m.get("model_id") == "qwen3.6:35b"),
            None,
        )
        print("default model:", default and f"{default['provider']}/{default['model_id']}")
        cfg_id = (ollama or default or {}).get("id")
        if not cfg_id:
            print("No model config found")
            return 1

        conv = (
            await client.post(
                f"{BASE}/chat/conversations",
                headers=headers,
                json={"title": "ollama-test", "model_config_id": cfg_id},
            )
        ).json()
        cid = conv["id"]
        print("conversation:", cid[:8])

        resp = await client.post(
            f"{BASE}/chat/conversations/{cid}/messages",
            headers=headers,
            json={"message": "请只回复一个字：好"},
        )
        print("status:", resp.status_code)
        if resp.status_code >= 400:
            print("error:", resp.text[:800])
            return 1
        data = resp.json()
        content = data.get("content") or (data.get("message") or {}).get("content") or ""
        print("reply:", content[:300])
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
