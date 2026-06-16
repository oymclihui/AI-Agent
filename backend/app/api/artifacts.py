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


@router.get("/{filename}")
async def download_artifact(
    filename: str,
    format: str | None = Query(None, alias="format", description="md | docx | xlsx | pptx"),
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
        media = FORMAT_MEDIA.get(native_ext, "application/octet-stream")
        return FileResponse(
            path,
            media_type=media,
            filename=out_name if out_name.endswith(path.suffix) else path.name.split("_", 1)[-1],
        )

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
