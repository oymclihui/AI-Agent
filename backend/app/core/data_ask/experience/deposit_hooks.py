"""Deposit integration: suggest data source employee from chat."""
from __future__ import annotations

from typing import Any


def enrich_deposit_with_data_ask(
    draft: dict[str, Any],
    *,
    data_source_id: str,
    data_source_name: str,
) -> dict[str, Any]:
    if draft.get("deposit_type") != "employee" and not draft.get("employee"):
        draft["suggestions"] = list(draft.get("suggestions") or [])
        draft["suggestions"].append(
            {
                "type": "employee",
                "title": f"从问数数据源「{data_source_name}」创建数字员工",
                "reason": "对话涉及数据分析，可沉淀为定时报告数字员工",
                "metadata": {"data_source_id": data_source_id, "data_ask": True},
            }
        )
    meta = draft.setdefault("metadata", {})
    meta["data_source_id"] = data_source_id
    meta["data_ask"] = True
    return draft
