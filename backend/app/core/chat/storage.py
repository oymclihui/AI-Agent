"""Persist chat attachments under LOCAL_UPLOADS_DIR/chat/{conversation_id}/."""
from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.db.base import generate_uuid


def chat_uploads_root(conversation_id: str) -> Path:
    root = Path(settings.LOCAL_UPLOADS_DIR) / "chat" / conversation_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_attachment_bytes(
    conversation_id: str,
    *,
    filename: str,
    data: bytes,
    message_id: str | None = None,
) -> str:
    folder = chat_uploads_root(conversation_id)
    if message_id:
        folder = folder / message_id
        folder.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name.replace("..", "_").replace("/", "_").replace("\\", "_")
    dest = folder / f"{generate_uuid()[:8]}_{safe_name}"
    dest.write_bytes(data)
    return str(dest.relative_to(Path(settings.LOCAL_UPLOADS_DIR))).replace("\\", "/")


def delete_conversation_uploads(conversation_id: str) -> None:
    import shutil

    chat_dir = Path(settings.LOCAL_UPLOADS_DIR) / "chat" / conversation_id
    if chat_dir.is_dir():
        shutil.rmtree(chat_dir, ignore_errors=True)
