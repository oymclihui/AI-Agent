"""Generate editable PPTX from structured slide data."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.util import Pt


def _parse_slides(slides_json: str) -> list[dict[str, Any]]:
    data = json.loads(slides_json)
    if isinstance(data, dict) and "slides" in data:
        data = data["slides"]
    if not isinstance(data, list) or not data:
        raise ValueError("slides_json must be a non-empty JSON array of slide objects")
    return data


def build_presentation(
    *,
    slides: list[dict[str, Any]],
    deck_title: str = "Presentation",
) -> Presentation:
    prs = Presentation()
    prs.core_properties.title = deck_title[:200]

    for idx, slide_data in enumerate(slides):
        title = str(slide_data.get("title") or slide_data.get("heading") or f"Slide {idx + 1}")
        body = slide_data.get("body")
        bullets = slide_data.get("bullets") or slide_data.get("points")

        if bullets and not isinstance(bullets, list):
            bullets = [str(bullets)]
        if body and not bullets:
            bullets = [str(body)]

        if idx == 0 and not bullets and not body:
            layout = prs.slide_layouts[0]
            slide = prs.slides.add_slide(layout)
            slide.shapes.title.text = title
            if slide.placeholders[1].text_frame:
                slide.placeholders[1].text = str(slide_data.get("subtitle") or "")
            continue

        layout = prs.slide_layouts[1] if len(prs.slide_layouts) > 1 else prs.slide_layouts[0]
        slide = prs.slides.add_slide(layout)
        slide.shapes.title.text = title

        if bullets:
            tf = slide.placeholders[1].text_frame
            tf.clear()
            for i, item in enumerate(bullets):
                text = str(item).strip()
                if not text:
                    continue
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = text
                p.level = 0
                p.font.size = Pt(18)
        elif body:
            slide.placeholders[1].text = str(body)

    if not prs.slides:
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = deck_title

    return prs


def export_pptx_file(
    *,
    output_path: Path,
    slides_json: str,
    deck_title: str = "Presentation",
) -> Path:
    slides = _parse_slides(slides_json)
    prs = build_presentation(slides=slides, deck_title=deck_title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output_path))
    return output_path
