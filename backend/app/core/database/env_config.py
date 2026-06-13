"""Read/write database connection settings in backend/.env."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote_plus, urlparse

from app.config import settings, _BACKEND_DIR

ENV_PATH = _BACKEND_DIR / ".env"

DB_ENV_KEYS = (
    "DB_DRIVER",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
    "DB_SSL",
    "DB_SCHEMA",
)

# Keys removed when switching to component-based config
LEGACY_URL_KEY = "DATABASE_URL"


def _mask_password(password: str) -> str:
    if not password:
        return ""
    if len(password) <= 2:
        return "****"
    return f"{'*' * min(8, len(password) - 2)}{password[-2:]}"


def parse_database_url(url: str) -> dict[str, str | int]:
    """Extract host/port/user/password/database from a PostgreSQL async URL."""
    normalized = url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )
    parsed = urlparse(normalized)
    return {
        "host": parsed.hostname or "",
        "port": parsed.port or 5432,
        "user": unquote_plus(parsed.username or ""),
        "password": unquote_plus(parsed.password or ""),
        "database": (parsed.path or "/").lstrip("/"),
    }


def current_db_config() -> dict:
    """Snapshot of active DB settings (password masked)."""
    driver = settings.resolved_db_driver
    if settings.DB_HOST:
        host = settings.DB_HOST
        port = settings.DB_PORT
        user = settings.DB_USER
        password = settings.DB_PASSWORD
        database = settings.DB_NAME
    else:
        parts = parse_database_url(settings.DATABASE_URL)
        host = str(parts["host"])
        port = int(parts["port"])
        user = str(parts["user"])
        password = str(parts["password"])
        database = str(parts["database"])

    return {
        "driver": driver,
        "host": host,
        "port": port,
        "user": user,
        "password_set": bool(password),
        "password_preview": _mask_password(password),
        "database": database,
        "ssl": settings.DB_SSL,
        "db_schema": settings.DB_SCHEMA or "public",
        "database_url_preview": settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else "",
    }


def _upsert_env_lines(text: str, updates: dict[str, str]) -> str:
    lines = text.splitlines()
    seen: set[str] = set()
    out: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        elif key == LEGACY_URL_KEY and "DB_HOST" in updates:
            out.append(f"# {line}  # replaced by DB_* settings via Settings → Database")
            seen.add(LEGACY_URL_KEY)
        else:
            out.append(line)

    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    return "\n".join(out).rstrip() + "\n"


def save_db_config(
    *,
    driver: str,
    host: str,
    port: int,
    user: str,
    password: str | None,
    database: str,
    ssl: str,
    schema: str,
) -> None:
    """Persist DB_* keys to backend/.env (does not reload running process)."""
    updates: dict[str, str] = {
        "DB_DRIVER": driver.strip().lower(),
        "DB_HOST": host.strip(),
        "DB_PORT": str(int(port)),
        "DB_USER": user.strip(),
        "DB_NAME": database.strip(),
        "DB_SSL": ssl.strip().lower() or "prefer",
        "DB_SCHEMA": schema.strip() or "public",
    }
    if password is not None and password != "":
        updates["DB_PASSWORD"] = password

    if ENV_PATH.is_file():
        text = ENV_PATH.read_text(encoding="utf-8")
    else:
        example = _BACKEND_DIR / ".env.example"
        text = example.read_text(encoding="utf-8") if example.is_file() else ""

    if "DB_HOST=" not in text and LEGACY_URL_KEY not in text:
        text = text.rstrip() + "\n\n# ── Database (managed via Settings → Database) ──\n"

    ENV_PATH.write_text(_upsert_env_lines(text, updates), encoding="utf-8")


def validate_schema_name(schema: str) -> str:
    name = (schema or "public").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(
            "Schema name must start with a letter or underscore and contain only letters, digits, and underscores."
        )
    return name
