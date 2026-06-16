#!/usr/bin/env python3
"""Write pre-configured env files for org desktop delivery (Docker + native Windows)."""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from desktop_delivery import (  # noqa: E402
    admin_readme,
    build_backend_env_text,
    build_env_text,
    user_readme,
)


def write_docker_env(out: Path) -> str:
    token = secrets.token_hex(16)
    (out / ".env").write_text(build_env_text(setup_token=token), encoding="utf-8")
    (out / "SETUP_TOKEN.admin.txt").write_text(admin_readme(token), encoding="utf-8")
    (out / "单位部署说明.txt").write_text(user_readme(), encoding="utf-8")
    return token


def write_backend_env(root: Path) -> str:
    token = secrets.token_hex(16)
    backend = root / "backend"
    backend.mkdir(parents=True, exist_ok=True)
    (backend / ".env").write_text(build_backend_env_text(setup_token=token), encoding="utf-8")
    (root / "SETUP_TOKEN.admin.txt").write_text(admin_readme(token), encoding="utf-8")
    (root / "单位部署说明.txt").write_text(user_readme(), encoding="utf-8")
    frontend_env = root / "frontend" / ".env.local"
    frontend_env.parent.mkdir(parents=True, exist_ok=True)
    if not frontend_env.is_file():
        frontend_env.write_text(
            "BACKEND_URL=http://127.0.0.1:8000\n"
            "NEXT_PUBLIC_API_URL=http://localhost:8000\n"
            "NEXT_PUBLIC_WS_URL=ws://localhost:8000\n",
            encoding="utf-8",
        )
    for sub in ("uploads", "chroma_data"):
        (backend / sub).mkdir(parents=True, exist_ok=True)
    return token


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("Usage: write_desktop_env.py <docker_out_dir>", file=sys.stderr)
        print("       write_desktop_env.py --backend <package_root>", file=sys.stderr)
        print("       write_desktop_env.py --all <package_root>", file=sys.stderr)
        return 1

    if args[0] == "--backend":
        root = Path(args[1])
        write_backend_env(root)
        print(f"Wrote {root / 'backend' / '.env'}")
        return 0
    if args[0] == "--all":
        root = Path(args[1])
        write_backend_env(root)
        write_docker_env(root)
        print(f"Wrote backend + docker env under {root}")
        return 0

    out = Path(args[0])
    write_docker_env(out)
    print(f"Wrote {out / '.env'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
