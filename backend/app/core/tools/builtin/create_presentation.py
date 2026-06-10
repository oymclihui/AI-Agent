import json

from langchain_core.tools import tool

from app.core.artifacts import artifact_download_url, new_artifact_path, sanitize_filename
from app.core.design.pptx_export import export_pptx_file


@tool
def create_presentation(
    slides_json: str,
    filename: str = "deck.pptx",
    deck_title: str = "Presentation",
) -> str:
    """
    Create an editable PowerPoint (.pptx) file from structured slide JSON.

    slides_json: JSON array, e.g.
      [{"title":"封面","subtitle":"副标题"},{"title":"要点","bullets":["A","B","C"]}]

    Returns JSON with storage_key and download_url for the generated file.
    Use this when the user asks for a downloadable PPT/PPTX deck.
    """
    try:
        full_path, storage_key = new_artifact_path(filename)
        export_pptx_file(
            output_path=full_path,
            slides_json=slides_json,
            deck_title=deck_title,
        )
        display_name = sanitize_filename(filename)
        payload = {
            "ok": True,
            "filename": display_name,
            "storage_key": storage_key,
            "download_url": artifact_download_url(storage_key, filename=display_name),
            "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "message": f"PPTX saved: {filename}",
        }
        return json.dumps(payload, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


CreatePresentationTool = create_presentation
