"""Shared deploy target resolution — no hardcoded server IPs."""
from __future__ import annotations

import os
import sys


def require_env(name: str, *, hint: str = "") -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        msg = f"ERROR: environment variable {name} is required."
        if hint:
            msg += f" {hint}"
        print(msg, file=sys.stderr)
        raise SystemExit(1)
    return value


def deploy_host() -> str:
    return require_env(
        "DEPLOY_HOST",
        hint="Example: set DEPLOY_HOST=10.0.0.5 before running deploy scripts.",
    )


def public_host() -> str:
    return os.environ.get("PUBLIC_HOST", deploy_host()).strip()


def deploy_db_host() -> str:
    return os.environ.get("DEPLOY_DB_HOST", deploy_host()).strip()


def deploy_ollama_url() -> str:
    explicit = os.environ.get("DEPLOY_OLLAMA_URL", "").strip()
    if explicit:
        return explicit
    host = deploy_db_host()
    port = os.environ.get("DEPLOY_OLLAMA_PORT", "11434").strip() or "11434"
    return f"http://{host}:{port}"


def deploy_milvus_uri() -> str:
    explicit = os.environ.get("DEPLOY_MILVUS_URI", "").strip()
    if explicit:
        return explicit
    host = deploy_db_host()
    port = os.environ.get("DEPLOY_MILVUS_PORT", "19530").strip() or "19530"
    return f"http://{host}:{port}"
