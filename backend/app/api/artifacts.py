from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from app.core.artifacts import artifacts_root, resolve_artifact
from app.core.doc_export import (
    FORMAT_MEDIA,
    convert_markdown,
    normalize_format,
    replace_extension,
)

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])

# Preview is a unique origin: scripts can run, but cannot read the app's storage.
_HTML_PREVIEW_CSP = (
    "sandbox allow-scripts allow-forms allow-popups allow-modals; "
    "default-src 'none'; "
    "script-src 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com "
    "https://unpkg.com https://cdn.tailwindcss.com; "
    "style-src 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com "
    "https://unpkg.com https://fonts.googleapis.com https://cdn.tailwindcss.com; "
    "font-src data: https://fonts.gstatic.com https://cdn.jsdelivr.net; "
    "img-src data: blob: https:; "
    "media-src data: blob: https:; "
    "connect-src 'none'; "
    "frame-src 'none'; "
    "frame-ancestors 'self'; "
    "base-uri 'none'; "
    "form-action 'none'"
)


def _html_file(path: Path, filename: str, *, download: bool) -> FileResponse:
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"}
    if not download:
        headers["Content-Security-Policy"] = _HTML_PREVIEW_CSP
    return FileResponse(
        path,
        media_type="text/html; charset=utf-8",
        filename=filename,
        content_disposition_type="attachment" if download else "inline",
        headers=headers,
    )


@router.get("/{filename}")
async def download_artifact(
    filename: str,
    format: str | None = Query(None, alias="format", description="md | docx | xlsx | pptx"),
    download: bool = Query(False, description="Force a file download for HTML previews"),
):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    root = artifacts_root()
    matches = sorted(root.glob(f"*_{filename}"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        direct = resolve_artifact(f"artifacts/{filename}")
        if direct:
            matches = [direct]

    if not matches:
        raise HTTPException(status_code=404, detail="Artifact not found")

    path: Path = matches[0]
    native_ext = path.suffix.lower().lstrip(".") or "bin"
    try:
        target = normalize_format(format, default=native_ext if native_ext in ("md", "docx", "xlsx", "pptx") else "md")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    out_name = filename if filename.endswith(f".{target}") else replace_extension(filename, target)

    if target == native_ext or format is None:
        served_name = out_name if out_name.endswith(path.suffix) else path.name.split("_", 1)[-1]
        if native_ext == "html":
            return _html_file(path, served_name, download=download)
        media = FORMAT_MEDIA.get(native_ext, "application/octet-stream")
        return FileResponse(path, media_type=media, filename=served_name)

    if native_ext not in ("md", "txt", ""):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot convert .{native_ext} to .{target}; download the original file instead",
        )

    text = path.read_text(encoding="utf-8")
    body = convert_markdown(text, target, title=Path(filename).stem)
    return Response(
        content=body,
        media_type=FORMAT_MEDIA[target],
        headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
    )
