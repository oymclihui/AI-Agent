#!/usr/bin/env python3
"""
AI-AGENT desktop sidecar — polls the platform for GUI automation tasks.

Usage (from repo root, with backend running):
  set AIAGNET_BASE_URL=http://127.0.0.1:8000
  set AIAGNET_LOGIN=admin
  set AIAGNET_PASSWORD=admin123
  backend\.venv\Scripts\python.exe scripts\desktop_sidecar.py

OpenAdapt (optional):
  pip install openadapt-capture openadapt-agent
  set AIAGNET_OPENADAPT_DATA_DIR=E:\AIAGNET\desktop_openadapt_data
"""
from __future__ import annotations

import os
import platform
import socket
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.core.desktop.openadapt_runner import create_runner  # noqa: E402

POLL_INTERVAL = float(os.environ.get("AIAGNET_SIDECAR_POLL_SEC", "3"))
DEVICE_ID = os.environ.get("AIAGNET_DEVICE_ID") or str(uuid.uuid4())
RUNNER = create_runner()


def _base_url() -> str:
    return os.environ.get("AIAGNET_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _login(client: httpx.Client) -> str:
    login = os.environ.get("AIAGNET_LOGIN", "admin")
    password = os.environ.get("AIAGNET_PASSWORD", "admin123")
    token = os.environ.get("AIAGNET_TOKEN", "").strip()
    if token:
        return token
    resp = client.post(
        f"{_base_url()}/api/v1/auth/login",
        json={"login": login, "password": password},
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("access_token") or data.get("token") or ""


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register(client: httpx.Client, token: str) -> None:
    hostname = socket.gethostname()
    resp = client.post(
        f"{_base_url()}/api/v1/desktop-automation/sidecar/register",
        headers=_headers(token),
        json={
            "device_id": DEVICE_ID,
            "device_name": os.environ.get("AIAGNET_DEVICE_NAME", hostname),
            "hostname": hostname,
            "platform": platform.system(),
        },
    )
    resp.raise_for_status()
    body = resp.json()
    print(f"[sidecar] registered device_id={body.get('device_id')} name={body.get('device_name')}")


def execute_task(task: dict) -> tuple[str, dict, str | None, dict]:
    """Returns status, output_data, error_message, extra complete payload."""
    action = task.get("action")
    try:
        if action == "capture_start":
            out = RUNNER.start_capture(task)
            return "completed", out, None, {}
        if action == "capture_stop":
            input_data = task.get("input_data") or {}
            demo_name = input_data.get("demo_name") or "未命名演示"
            out = RUNNER.stop_capture(demo_name, task)
            extra = {
                "demo_name": demo_name,
                "app_name": input_data.get("app_name"),
                "description": input_data.get("description"),
                "step_count": out.get("step_count") or len(out.get("steps") or []),
            }
            return "completed", out, None, extra
        if action == "replay":
            input_data = task.get("input_data") or {}
            demo_name = input_data.get("demo_name") or task.get("demo_name") or "demo"
            instructions = task.get("instructions") or ""
            out = RUNNER.replay(demo_name, instructions)
            if out.get("error"):
                return "failed", out, str(out.get("error")), {}
            return "completed", out, None, {}
        return "failed", {}, f"Unknown action: {action}", {}
    except Exception as exc:
        return "failed", {}, str(exc), {}


def complete_task(client: httpx.Client, token: str, task_id: str, payload: dict) -> None:
    resp = client.post(
        f"{_base_url()}/api/v1/desktop-automation/sidecar/tasks/{task_id}/complete",
        headers=_headers(token),
        json=payload,
    )
    resp.raise_for_status()


def poll_once(client: httpx.Client, token: str) -> None:
    resp = client.get(
        f"{_base_url()}/api/v1/desktop-automation/sidecar/poll",
        headers=_headers(token),
        params={"device_id": DEVICE_ID},
    )
    resp.raise_for_status()
    tasks = resp.json().get("tasks") or []
    for task in tasks:
        task_id = task["id"]
        print(f"[sidecar] running task {task_id} action={task.get('action')}")
        status, output_data, error_message, extra = execute_task(task)
        payload = {
            "status": status,
            "output_data": output_data,
            "error_message": error_message,
            **extra,
        }
        complete_task(client, token, task_id, payload)
        print(f"[sidecar] task {task_id} -> {status} mode={output_data.get('mode', '?')}")


def main() -> int:
    print("[sidecar] AI-AGENT desktop sidecar")
    print(f"[sidecar] base_url={_base_url()} device_id={DEVICE_ID}")
    print(f"[sidecar] openadapt_mode={RUNNER.mode} data_dir={RUNNER.data_dir}")
    with httpx.Client(timeout=120.0) as client:
        try:
            token = _login(client)
        except Exception as exc:
            print(f"[sidecar] login failed: {exc}", file=sys.stderr)
            return 1
        if not token:
            print("[sidecar] no access token", file=sys.stderr)
            return 1
        try:
            register(client, token)
        except Exception as exc:
            print(f"[sidecar] register failed: {exc}", file=sys.stderr)
            return 1

        while True:
            try:
                poll_once(client, token)
            except KeyboardInterrupt:
                print("\n[sidecar] stopped")
                return 0
            except Exception as exc:
                print(f"[sidecar] poll error: {exc}")
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
