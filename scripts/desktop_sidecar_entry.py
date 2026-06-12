#!/usr/bin/env python3
"""PyInstaller entry for AI-AGENT Desktop Sidecar."""
from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _load_sidecar_env(app_dir: Path) -> None:
    for name in ("sidecar.env", "sidecar.env.local"):
        env_file = app_dir / name
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ[key] = value
        break


def _bootstrap() -> Path:
    app_dir = _app_dir()
    os.chdir(app_dir)
    _load_sidecar_env(app_dir)

    data_dir = os.environ.get("AIAGNET_OPENADAPT_DATA_DIR") or str(app_dir / "openadapt_data")
    os.environ.setdefault("AIAGNET_OPENADAPT_DATA_DIR", data_dir)
    Path(data_dir).mkdir(parents=True, exist_ok=True)

    if getattr(sys, "frozen", False):
        bundle = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        backend = bundle / "backend"
        scripts = bundle / "scripts"
        if scripts.is_dir() and str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
    else:
        backend = app_dir / "backend"
    if backend.is_dir() and str(backend) not in sys.path:
        sys.path.insert(0, str(backend))

    return app_dir


def main() -> int:
    app_dir = _bootstrap()

    from desktop_sidecar import main as sidecar_main  # noqa: WPS433

    base = os.environ.get("AIAGNET_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    frontend = os.environ.get("AIAGNET_FRONTEND_URL", "http://127.0.0.1:3000").rstrip("/")
    open_browser = os.environ.get("AIAGNET_OPEN_BROWSER", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )

    if open_browser and "--no-browser" not in sys.argv:
        url = f"{frontend}/desktop-automation"
        print(f"[sidecar] opening {url}")
        try:
            webbrowser.open(url)
        except Exception as exc:
            print(f"[sidecar] browser open failed: {exc}")

    print(f"[sidecar] config dir: {app_dir}")
    print(f"[sidecar] edit {app_dir / 'sidecar.env'} to change server URL / login")
    return sidecar_main()


if __name__ == "__main__":
    raise SystemExit(main())
