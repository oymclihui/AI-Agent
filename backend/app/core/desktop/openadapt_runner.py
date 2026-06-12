"""
OpenAdapt integration adapter for the desktop sidecar.

Tries (in order):
1. openadapt-capture / openadapt-agent Python packages
2. `openadapt` CLI subprocess
3. Mock mode (POC without OpenAdapt installed)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class OpenAdaptRunner:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        from app.config import settings

        self.data_dir = Path(data_dir or settings.DESKTOP_OPENADAPT_DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.demos_dir = self.data_dir / "demos"
        self.demos_dir.mkdir(parents=True, exist_ok=True)
        self.capture_dir = self.data_dir / "active_capture"
        self._capture_active = False
        self._mode = self._detect_mode()
        logger.info("openadapt_runner_init", mode=self._mode, data_dir=str(self.data_dir))

    @property
    def mode(self) -> str:
        return self._mode

    def _detect_mode(self) -> str:
        if shutil.which("openadapt"):
            return "cli"
        try:
            import openadapt_capture  # noqa: F401
            return "python"
        except ImportError:
            pass
        try:
            import openadapt  # noqa: F401
            return "python"
        except ImportError:
            pass
        return "mock"

    def _demo_path(self, demo_name: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in demo_name.strip())
        return self.demos_dir / f"{safe}.json"

    def _run_cli(self, args: list[str], timeout: int = 300) -> tuple[bool, str]:
        cmd = ["openadapt", *args]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.data_dir),
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            return proc.returncode == 0, out.strip()
        except FileNotFoundError:
            return False, "openadapt CLI not found"
        except subprocess.TimeoutExpired:
            return False, "openadapt CLI timed out"
        except Exception as exc:
            return False, str(exc)

    def start_capture(self, task: dict | None = None) -> dict[str, Any]:
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "started_at": time.time(),
            "task": task or {},
            "steps": [],
        }
        (self.capture_dir / "session.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if self._mode == "cli":
            ok, out = self._run_cli(["capture", "start", "--output", str(self.capture_dir)])
            if ok:
                self._capture_active = True
                return {"message": "OpenAdapt CLI capture started.", "mode": "cli", "detail": out[:500]}

        if self._mode == "python":
            try:
                # openadapt-capture API (package layout may vary by version)
                from openadapt_capture import CaptureSession  # type: ignore

                session = CaptureSession(output_dir=str(self.capture_dir))
                session.start()
                self._capture_active = True
                self._python_session = session
                return {"message": "OpenAdapt capture session started.", "mode": "python"}
            except Exception as exc:
                logger.warning("openadapt_python_capture_failed", error=str(exc))

        self._capture_active = True
        return {
            "message": "Mock capture started — perform GUI steps on this PC.",
            "mode": "mock",
        }

    def stop_capture(self, demo_name: str, task: dict | None = None) -> dict[str, Any]:
        input_data = (task or {}).get("input_data") or {}
        app_name = input_data.get("app_name") or ""
        description = input_data.get("description") or ""
        step_count = 5

        if self._mode == "cli":
            ok, out = self._run_cli(
                ["capture", "stop", "--name", demo_name, "--output", str(self.demos_dir)]
            )
            if ok:
                self._capture_active = False
                return {
                    "message": f"OpenAdapt CLI capture saved: {demo_name}",
                    "mode": "cli",
                    "demo_name": demo_name,
                    "detail": out[:500],
                }

        if self._mode == "python":
            try:
                session = getattr(self, "_python_session", None)
                if session is not None:
                    session.stop()
                    recording = session.export() if hasattr(session, "export") else {}
                    step_count = len(recording.get("steps", [])) if isinstance(recording, dict) else 5
                self._capture_active = False
            except Exception as exc:
                logger.warning("openadapt_python_stop_failed", error=str(exc))

        # Persist demo metadata locally (all modes)
        demo_file = self._demo_path(demo_name)
        session_file = self.capture_dir / "session.json"
        steps: list[str] = []
        if session_file.exists():
            try:
                sess = json.loads(session_file.read_text(encoding="utf-8"))
                steps = list(sess.get("steps") or [])
            except json.JSONDecodeError:
                pass
        if not steps and self._mode == "mock":
            steps = [
                "打开目标应用",
                "执行演示操作",
                "完成并保存结果",
            ]
            step_count = len(steps)

        payload = {
            "name": demo_name,
            "app_name": app_name,
            "description": description,
            "step_count": step_count,
            "steps": steps,
            "mode": self._mode,
            "saved_at": time.time(),
        }
        demo_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._capture_active = False
        return {
            "message": f"Capture saved: {demo_name}",
            "mode": self._mode,
            "demo_name": demo_name,
            "step_count": step_count,
            "steps": steps,
        }

    def replay(self, demo_name: str, instructions: str = "") -> dict[str, Any]:
        demo_file = self._demo_path(demo_name)
        if not demo_file.exists():
            # still attempt replay — demo may exist only in platform DB
            logger.warning("openadapt_demo_file_missing", demo=demo_name)

        if self._mode == "cli":
            args = ["replay", "--demo", demo_name]
            if instructions:
                args.extend(["--instructions", instructions])
            ok, out = self._run_cli(args, timeout=600)
            if ok:
                return {
                    "message": f"OpenAdapt CLI replay completed for '{demo_name}'.",
                    "mode": "cli",
                    "demo_name": demo_name,
                    "instructions": instructions,
                    "detail": out[:1000],
                }
            return {
                "message": f"OpenAdapt CLI replay failed for '{demo_name}'.",
                "mode": "cli",
                "error": out[:500],
            }

        if self._mode == "python":
            try:
                from openadapt_agent import ReplayAgent  # type: ignore

                agent = ReplayAgent(demo_name=demo_name, data_dir=str(self.demos_dir))
                result = agent.run(instructions=instructions)
                return {
                    "message": f"OpenAdapt agent replay completed for '{demo_name}'.",
                    "mode": "python",
                    "demo_name": demo_name,
                    "result": str(result)[:1000],
                }
            except Exception as exc:
                logger.warning("openadapt_python_replay_failed", error=str(exc))

        # Mock: simulate replay latency
        time.sleep(2)
        steps: list[str] = []
        if demo_file.exists():
            try:
                data = json.loads(demo_file.read_text(encoding="utf-8"))
                steps = list(data.get("steps") or [])
            except json.JSONDecodeError:
                pass
        return {
            "message": f"Mock replay completed for '{demo_name}' ({len(steps) or 3} steps).",
            "mode": "mock",
            "demo_name": demo_name,
            "instructions": instructions,
            "steps_replayed": len(steps) or 3,
        }


def create_runner() -> OpenAdaptRunner:
    data_dir = os.environ.get("AIAGNET_OPENADAPT_DATA_DIR")
    return OpenAdaptRunner(data_dir=data_dir)
