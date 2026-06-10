from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.artifacts import artifacts_root, resolve_artifact

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])


@router.get("/{filename}")
async def download_artifact(filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    root = artifacts_root()
    matches = sorted(root.glob(f"*_{filename}"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        # Also allow direct storage key basename lookup
        direct = resolve_artifact(f"artifacts/{filename}")
        if direct:
            matches = [direct]

    if not matches:
        raise HTTPException(status_code=404, detail="Artifact not found")

    path: Path = matches[0]
    media = "application/octet-stream"
    if path.suffix.lower() == ".pptx":
        media = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

    return FileResponse(
        path,
        media_type=media,
        filename=filename if filename.endswith(path.suffix) else path.name.split("_", 1)[-1],
    )
