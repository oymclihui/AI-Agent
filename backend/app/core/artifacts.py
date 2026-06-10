"""Artifact file storage under LOCAL_UPLOADS_DIR/artifacts."""
from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

from app.config import settings

_ARTIFACT_DIR_NAME = "artifacts"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def artifacts_root() -> Path:
    root = Path(settings.LOCAL_UPLOADS_DIR) / _ARTIFACT_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def sanitize_filename(name: str, default: str = "artifact") -> str:
    base = _SAFE_NAME.sub("_", (name or "").strip()) or default
    if not base.lower().endswith(".pptx"):
        base = f"{base}.pptx"
    return base[:120]


def new_artifact_path(filename: str) -> tuple[Path, str]:
    """Return (absolute path, storage_key relative to uploads root)."""
    safe = sanitize_filename(filename)
    storage_key = f"{_ARTIFACT_DIR_NAME}/{uuid4().hex}_{safe}"
    full = Path(settings.LOCAL_UPLOADS_DIR) / storage_key
    full.parent.mkdir(parents=True, exist_ok=True)
    return full, storage_key


def resolve_artifact(storage_key: str) -> Path | None:
    key = storage_key.lstrip("/").replace("\\", "/")
    if ".." in key.split("/"):
        return None
    if not key.startswith(f"{_ARTIFACT_DIR_NAME}/"):
        return None
    full = Path(settings.LOCAL_UPLOADS_DIR) / key
    if full.is_file():
        return full
    return None


def artifact_download_url(storage_key: str, *, filename: str | None = None) -> str:
    name = filename or Path(storage_key).name
    if "_" in name and len(name.split("_", 1)[0]) == 32:
        name = name.split("_", 1)[-1]
    return f"/api/v1/artifacts/{name}"


def collect_artifacts_from_output(text: str | None) -> list[dict]:
    """Find artifact download URLs mentioned in agent final answer."""
    if not text:
        return []
    found: list[dict] = []
    seen: set[str] = set()
    for match in re.finditer(r"/api/v1/artifacts/([A-Za-z0-9._-]+)", text):
        filename = match.group(1)
        if filename in seen:
            continue
        seen.add(filename)
        mime = "application/octet-stream"
        if filename.lower().endswith(".pptx"):
            mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        found.append({
            "filename": filename,
            "download_url": f"/api/v1/artifacts/{filename}",
            "mime_type": mime,
        })
    return found


def merge_artifacts(*groups: list[dict] | None) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for group in groups:
        for item in group or []:
            url = str(item.get("download_url") or "")
            key = url or str(item.get("storage_key") or item.get("filename") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def collect_artifacts_from_steps(steps: list[dict] | None) -> list[dict]:
    """Parse tool results that embed artifact JSON."""
    found: list[dict] = []
    seen: set[str] = set()
    for step in steps or []:
        if step.get("type") != "tool_call":
            continue
        raw = str(step.get("result") or "")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        key = data.get("storage_key") or data.get("artifact_path")
        if not key or key in seen:
            continue
        seen.add(key)
        found.append({
            "filename": data.get("filename") or Path(str(key)).name,
            "storage_key": key,
            "download_url": data.get("download_url") or artifact_download_url(key),
            "mime_type": data.get("mime_type") or "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        })
    return found
