"""Local filesystem storage for uploaded knowledge-base documents."""
from pathlib import Path

from app.config import settings


def _uploads_root() -> Path:
    root = Path(settings.LOCAL_UPLOADS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_document_file(kb_id: str, doc_id: str, filename: str, data: bytes) -> str:
    safe_name = filename.replace("/", "_").replace("\\", "_") or "document.txt"
    kb_dir = _uploads_root() / kb_id
    kb_dir.mkdir(parents=True, exist_ok=True)
    target = kb_dir / f"{doc_id}_{safe_name}"
    target.write_bytes(data)
    return f"{kb_id}/{doc_id}_{safe_name}"


def read_document_file(storage_path: str) -> bytes | None:
    if not storage_path:
        return None
    full = _uploads_root() / storage_path
    if full.is_file():
        return full.read_bytes()
    return None


def delete_document_file(storage_path: str) -> None:
    if not storage_path:
        return
    full = _uploads_root() / storage_path
    if full.is_file():
        full.unlink(missing_ok=True)
