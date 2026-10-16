"""业务语义层加载器（Agent Evolution 阶段一）。

问数时把业务语义层（术语词典 ds_semantic_term / 指标口径 ds_semantic_metric）
合并进 semantic dict，并用 Schema 画像丰富列注释与枚举示例。

数据真实性红线：术语/指标全部来自用户真实配置或反馈沉淀，画像列信息全部来自
真实探测与 LLM 基于真实样本的推断（inferred_comment 标注来源），不合成填充。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DsSemanticMetric, DsSemanticTerm

logger = logging.getLogger("ds_semantic_loader")


async def load_ds_semantic(
    db: AsyncSession,
    data_source_id: str,
    semantic: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[tuple[str, str], dict[str, Any]]]:
    """加载业务语义层合并进 semantic，并返回画像列 lookup。

    合并规则：数据源手工配置的 semantic_model 优先（同名词条/指标跳过），
    语义层条目作为补充追加。返回 (merged_semantic, profile_column_lookup)。
    """
    merged: dict[str, Any] = dict(semantic) if isinstance(semantic, dict) else {}

    terms_res = await db.execute(
        select(DsSemanticTerm).where(DsSemanticTerm.data_source_id == str(data_source_id))
    )
    terms = list(terms_res.scalars().all())
    if terms:
        existing: list[Any] = list(merged.get("terms") or [])
        have = {
            str(t.get("term") or t.get("name") or "")
            for t in existing
            if isinstance(t, dict)
        }
        for t in terms:
            if t.term in have:
                continue
            existing.append(
                {
                    "term": t.term,
                    "name": t.term,
                    "definition": t.definition or "",
                    "description": t.definition or "",
                    "column_ref": t.column_ref or "",
                    "synonyms": t.synonyms or [],
                }
            )
        merged["terms"] = existing

    metrics_res = await db.execute(
        select(DsSemanticMetric).where(DsSemanticMetric.data_source_id == str(data_source_id))
    )
    metrics = list(metrics_res.scalars().all())
    if metrics:
        existing_m: list[Any] = list(merged.get("metrics") or [])
        have_m = {str(m.get("name") or "") for m in existing_m if isinstance(m, dict)}
        for m in metrics:
            if m.name in have_m:
                continue
            existing_m.append(
                {
                    "name": m.name,
                    "expr": m.expr,
                    "description": m.description or "",
                    "dimensions": m.dimensions or [],
                    "default_filters": m.default_filters or [],
                }
            )
        merged["metrics"] = existing_m

    try:
        from app.db.models import DsBusinessRule

        rules_res = await db.execute(
            select(DsBusinessRule).where(
                DsBusinessRule.data_source_id == str(data_source_id),
                DsBusinessRule.status == "active",
            )
        )
        rules = [r for r in rules_res.scalars().all() if r.rule_type == "filter"]
        if rules:
            notes = list(merged.get("notes") or [])
            have = {str(n) for n in notes}
            for r in rules:
                text = f"业务规则（默认过滤）：{r.rule_text}"
                if text not in have:
                    notes.append(text)
            merged["notes"] = notes
    except Exception as exc:
        logger.warning("load_business_rules_failed ds=%s err=%s", data_source_id, str(exc)[:150])

    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        from app.core.data_ask.profile import get_latest_profile, profile_column_lookup

        profile_row = await get_latest_profile(db, str(data_source_id))
        lookup = profile_column_lookup(profile_row)
    except Exception as exc:
        logger.warning("load_profile_lookup_failed ds=%s err=%s", data_source_id, str(exc)[:150])

    return (merged or None), lookup


def enrich_table_meta_with_profile(
    table_meta: list[dict[str, Any]],
    lookup: dict[tuple[str, str], dict[str, Any]],
) -> None:
    """用画像丰富 table_meta：列注释为空才填 inferred_comment，枚举值写入 examples。

    仅就地修改内存中的 prompt 上下文，不回写数据源注册表（保持原始元数据纯净）。
    """
    if not lookup:
        return
    for table in table_meta or []:
        tname = str(table.get("table_name") or "")
        if not tname:
            continue
        for col in table.get("columns") or []:
            if not isinstance(col, dict):
                continue
            info = lookup.get((tname, str(col.get("name") or "").lower()))
            if not info:
                continue
            if not str(col.get("comment") or "").strip() and info.get("inferred_comment"):
                col["comment"] = str(info["inferred_comment"])
            enums = info.get("enum_values") or []
            if enums and not col.get("examples"):
                col["examples"] = [
                    e.get("value") for e in enums[:10] if e.get("value") is not None
                ]
