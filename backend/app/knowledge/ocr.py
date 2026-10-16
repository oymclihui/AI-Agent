"""OCR for images and scanned PDFs. Text PDFs keep the normal extractor."""
from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


def _tesseract(image) -> str:
    import pytesseract

    try:
        return pytesseract.image_to_string(image, lang="chi_sim+eng") or ""
    except Exception:
        return pytesseract.image_to_string(image, lang="eng") or ""


def image_bytes_to_text(raw: bytes) -> str:
    from io import BytesIO
    from PIL import Image

    image = Image.open(BytesIO(raw))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    return _tesseract(image).strip()


def image_file_to_text(path: str) -> str:
    with open(path, "rb") as handle:
        return image_bytes_to_text(handle.read())


def pdf_scan_to_text(path: str, max_pages: int = 20) -> str:
    import fitz
    from PIL import Image

    parts: list[str] = []
    doc = fitz.open(path)
    try:
        for index, page in enumerate(doc):
            if index >= max_pages:
                break
            native = (page.get_text() or "").strip()
            if len(native) >= 40:
                parts.append(native)
                continue
            pix = page.get_pixmap(dpi=140)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            recognized = _tesseract(image).strip()
            if recognized:
                parts.append(recognized)
    finally:
        doc.close()
    return "\n\n".join(parts).strip()
