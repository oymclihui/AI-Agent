"""Smoke tests for agent harness (tool policy, pending actions)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

BASE = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/v1"


async def main() -> int:
    print("=== Harness Smoke Test ===\n")
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        login = await client.post("/auth/login", json={"login": "admin", "password": "admin123"})
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        risks = (await client.get("/harness/tools/risk", headers=headers)).json()
        assert len(risks) >= 5, risks
        print(f"  [PASS] tools/risk count={len(risks)}")

        awaiting = (await client.get("/harness/actions/awaiting-confirmation", headers=headers)).json()
        print(f"  [PASS] awaiting-confirmation count={len(awaiting)}")

        tools = (await client.get("/tools/", headers=headers)).json()
        with_risk = [t for t in tools if t.get("risk_level")]
        assert len(with_risk) == len(tools), tools[0]
        print(f"  [PASS] tools list includes risk_level ({len(tools)} tools)")

    print("\n=== Harness OK ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
