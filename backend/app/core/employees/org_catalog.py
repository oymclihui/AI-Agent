"""Display hints for employee org chart nodes (template + cadence labels)."""
from __future__ import annotations

from typing import Any, Optional

CADENCE_LABELS: dict[str, dict[str, str]] = {
    "daily": {"zh": "每日", "en": "Daily"},
    "weekly": {"zh": "每周", "en": "Weekly"},
    "monthly": {"zh": "每月", "en": "Monthly"},
}

TEMPLATE_DISPLAY: dict[str, dict[str, Any]] = {
    "nev-cfo-monthly-board": {
        "short_title": {"zh": "CFO", "en": "CFO"},
        "cadence_label": {"zh": "每月 · 3 日", "en": "Monthly · 3rd"},
    },
    "nev-vp-finance-weekly": {
        "short_title": {"zh": "财务 VP", "en": "VP Finance"},
        "cadence_label": {"zh": "每周 · 周一", "en": "Weekly · Mon"},
    },
    "nev-controller-manufacturing-daily": {
        "short_title": {"zh": "财务控制", "en": "Controller"},
        "cadence_label": {"zh": "每日 + 周五", "en": "Daily + Fri"},
    },
    "nev-treasury-weekly": {
        "short_title": {"zh": "司库", "en": "Treasury"},
        "cadence_label": {"zh": "每周 · 周一", "en": "Weekly · Mon"},
    },
    "nev-fpa-rolling-weekly": {
        "short_title": {"zh": "FP&A", "en": "FP&A"},
        "cadence_label": {"zh": "每周 · 周一", "en": "Weekly · Mon"},
    },
    "nev-tax-subsidy-monthly": {
        "short_title": {"zh": "税务政策", "en": "Tax"},
        "cadence_label": {"zh": "每月 · 5 日", "en": "Monthly · 5th"},
    },
    "nev-cost-accounting-weekly": {
        "short_title": {"zh": "成本会计", "en": "Cost"},
        "cadence_label": {"zh": "每周 · 周一", "en": "Weekly · Mon"},
    },
}


def display_hints(metadata: dict[str, Any] | None, title: str | None = None) -> dict[str, Optional[str]]:
    meta = metadata or {}
    template_id = str(meta.get("template_id") or "")
    catalog = TEMPLATE_DISPLAY.get(template_id, {})
    cadence = str(meta.get("org_cadence") or "")
    cadence_label = catalog.get("cadence_label") or CADENCE_LABELS.get(cadence, {})
    short_title = catalog.get("short_title") or {}
    fallback_short = (title or "").split("·")[0].strip()[:12] if title else None
    return {
        "cadence": cadence or None,
        "cadence_label_zh": cadence_label.get("zh") if cadence_label else None,
        "cadence_label_en": cadence_label.get("en") if cadence_label else None,
        "short_title_zh": short_title.get("zh") or fallback_short,
        "short_title_en": short_title.get("en") or fallback_short,
    }
