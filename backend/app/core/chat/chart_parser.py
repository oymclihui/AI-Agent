"""
Extract chart configuration from LLM response content.
The agent outputs chart configs in fenced ```chart code blocks.

Format:
```chart
{"type": "bar", "title": "...", "labels": ["A","B","C"], "datasets": [{"label": "Series1", "data": [1,2,3]}]}
```
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional


def extract_chart_data(content: str) -> Optional[dict[str, Any]]:
    """Parse the FIRST valid ```chart JSON block from assistant content.

    Returns the first valid chart config, or None.
    """
    charts = extract_charts_data(content)
    return charts[0] if charts else None


def extract_charts_data(content: str) -> list[dict[str, Any]]:
    """Parse ALL valid ```chart JSON blocks from assistant content.

    Returns a list of valid chart configs (may be empty).
    Chart config shape:
        {
            "type": "bar" | "line" | "pie" | "area" | "scatter",
            "title": str,
            "labels": [str, ...],
            "datasets": [{"label": str, "data": [number, ...]}]
        }
    """
    if not content:
        return []

    pattern = r"```chart\s*\n?(\{.*?\})\s*```"
    matches = re.findall(pattern, content, re.DOTALL)

    charts = []
    for raw_json in matches:
        try:
            cfg = json.loads(raw_json)
            if _validate_chart_config(cfg):
                charts.append(cfg)
        except (json.JSONDecodeError, TypeError):
            continue

    return charts


def _validate_chart_config(cfg: dict) -> bool:
    """Check minimum required fields."""
    if not isinstance(cfg, dict):
        return False
    chart_type = cfg.get("type", "")
    if chart_type not in ("bar", "line", "pie", "area", "scatter"):
        return False
    if not cfg.get("labels"):
        return False
    datasets = cfg.get("datasets")
    if not datasets or not isinstance(datasets, list):
        return False
    for ds in datasets:
        if not isinstance(ds, dict):
            return False
        if "data" not in ds or not isinstance(ds["data"], list):
            return False
    return True


def strip_chart_blocks(content: str) -> str:
    """Remove ```chart JSON blocks from content (for cleaner text display)."""
    if not content:
        return content
    pattern = r"```chart\s*\n?\{.*?\}\s*```"
    return re.sub(pattern, "", content, flags=re.DOTALL).strip()
