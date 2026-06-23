#!/usr/bin/env python3
"""Deactivate all Ollama :cloud model configs (admin API or DB seed on restart)."""
from __future__ import annotations

import os
import sys

import httpx

BASE = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API = f"{BASE}/api/v1"
LOGIN = os.environ.get("SMOKE_ADMIN_LOGIN", "admin")
PASSWORD = os.environ.get("SMOKE_ADMIN_PASSWORD", "admin123")


def main() -> int:
    client = httpx.Client(timeout=60.0)
    r = client.post(f"{API}/auth/login", json={"login": LOGIN, "password": PASSWORD})
    if r.status_code != 200:
        print("login failed:", r.status_code, r.text[:200])
        return 1
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    configs = client.get(f"{API}/models/configs", headers=h).json()
    removed = 0
    for cfg in configs:
        model_id = str(cfg.get("model_id") or "")
        if ":cloud" not in model_id:
            continue
        cid = cfg["id"]
        dr = client.delete(f"{API}/models/configs/{cid}", headers=h)
        if dr.status_code in (204, 200):
            print(f"removed: {cfg.get('name')} ({model_id})")
            removed += 1
        else:
            print(f"failed: {cfg.get('name')} — {dr.status_code} {dr.text[:120]}")

    print(f"done — removed {removed} cloud model(s)")
    return 0 if removed >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
