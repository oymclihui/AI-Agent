"""语义层维度派生：列名规则自动识别 + 语义模型手工覆盖。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataSourceTable, DataSourceTableRole, MetricDimension

# 列名 → (显示名, 类型, 层级, 父级)
_DIMENSION_RULES: dict[str, tuple[str, str, int, str | None]] = {
    "RQ": ("日期", "date", 0, None),
    "FL1MC": ("一级品类", "string", 0, None),
    "FL2MC": ("二级品类", "string", 1, "一级品类"),
    "FL3MC": ("三级品类", "string", 2, "二级品类"),
    "FL4MC": ("四级品类", "string", 3, "三级品类"),
    "SPMC": ("商品", "string", 4, "四级品类"),
    "GHDWMC": ("供货单位", "string", 0, None),
    "FDMC": ("分店", "string", 0, None),
    "FDBH": ("分店", "string", 0, None),
    "FDBHMC": ("分店", "string", 0, None),
    "SPTM": ("商品条码", "string", 4, "商品"),
}

_NUMERIC_TYPES = ("int", "decimal", "numeric", "float", "double", "real", "bigint", "smallint", "number")


def _column_list(column_meta: Any) -> list[dict[str, str]]:
    """兼容 {name: type}、{"columns": [...]}、[...] 三种列元数据形态。"""
    out: list[dict[str, str]] = []
    if isinstance(column_meta, list):
        for item in column_meta:
            if isinstance(item, dict) and item.get("name"):
                out.append({"name": str(item["name"]), "type": str(item.get("type") or item.get("data_type") or "")})
            elif isinstance(item, str):
                out.append({"name": item, "type": ""})
        return out
    if isinstance(column_meta, dict):
        cols = column_meta.get("columns")
        if isinstance(cols, list):
            return _column_list(cols)
        for name, typ in column_meta.items():
            out.append({"name": str(name), "type": str(typ) if not isinstance(typ, dict) else str(typ.get("type") or "")})
    return out


def _is_numeric(dtype: str) -> bool:
    d = (dtype or "").lower()
    return any(token in d for token in _NUMERIC_TYPES)


def derive_dimensions(
    column_meta: Any,
    manual: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """按规则识别维度，再用语义模型的手工定义覆盖同名项。"""
    derived: list[dict[str, Any]] = []
    for col in _column_list(column_meta):
        name = col["name"]
        if _is_numeric(col["type"]):
            continue
        rule = _DIMENSION_RULES.get(name.upper())
        if not rule:
            continue
        label, dtype, level, parent = rule
        derived.append({
            "name": label,
            "column": name,
            "data_type": dtype,
            "hierarchy_level": level,
            "parent": parent,
            "source": "auto",
        })

    if manual:
        by_column = {d["column"].upper(): i for i, d in enumerate(derived)}
        for item in manual:
            if not isinstance(item, dict):
                continue
            column = str(item.get("column") or item.get("column_name") or "").strip()
            if not column:
                continue
            entry = {
                "name": str(item.get("name") or column),
                "column": column,
                "data_type": str(item.get("data_type") or "string"),
                "hierarchy_level": int(item.get("hierarchy_level") or 0),
                "parent": item.get("parent"),
                "source": "manual",
            }
            idx = by_column.get(column.upper())
            if idx is None:
                derived.append(entry)
                by_column[column.upper()] = len(derived) - 1
            else:
                derived[idx] = entry
    return derived


def dimension_hierarchy(dimensions: list[dict[str, Any]], name: str) -> list[str]:
    """返回从根到目标维度的下钻路径。"""
    by_name = {str(d.get("name")): d for d in dimensions if isinstance(d, dict)}
    chain: list[str] = []
    current = name
    guard = 0
    while current and current in by_name and guard < 10:
        chain.append(current)
        current = by_name[current].get("parent")
        guard += 1
    return list(reversed(chain))


async def refresh_dimensions(db: AsyncSession, source: Any) -> list[dict[str, Any]]:
    """重算某数据源的维度并物化到 metric_dimensions。"""
    rows = (await db.execute(
        select(DataSourceTable)
        .where(
            DataSourceTable.data_source_id == source.id,
            DataSourceTable.role == DataSourceTableRole.data,
        )
        .order_by(DataSourceTable.created_at.asc())
        .limit(1)
    )).scalars().all()
    column_meta = rows[0].column_meta if rows else {}
    manual = (getattr(source, "semantic_model", None) or {}).get("dimensions") or []
    dims = derive_dimensions(column_meta, manual)

    await db.execute(delete(MetricDimension).where(MetricDimension.data_source_id == source.id))
    for d in dims:
        db.add(MetricDimension(
            data_source_id=source.id,
            name=d["name"],
            column_name=d["column"],
            data_type=d["data_type"],
            hierarchy_level=d["hierarchy_level"],
            parent_id=None,
        ))
    await db.flush()
    return dims
