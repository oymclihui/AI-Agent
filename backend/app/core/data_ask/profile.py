"""Schema 画像：字段业务含义推断、枚举/分布探测、主外键识别、数据质量报告。

数据真实性红线：所有统计值（行数/null 率/基数/枚举/min/max）全部来自对源库的
真实 SELECT 探测查询；字段含义由 LLM 基于真实样本值推断并标注 inferred=True；
数据不足或探测失败时如实记录缺口，绝不合成填充。
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_ask.connectors.factory import build_connector_from_source
from app.core.data_ask.schema.introspect import infer_join_graph, introspect_tables, is_key_column
from app.db.models import DataSource, DataSourceTable, DataSourceTableRole, DsSchemaProfile

logger = logging.getLogger("ds_profile")

ENUM_MAX_CARDINALITY = 50       # 基数 <= 50 的文本列才探测枚举值
ENUM_TOP_N = 20                 # 枚举值保留条数
PROFILE_MAX_TABLES = 20         # 单数据源画像表数上限
PROFILE_MAX_COLS_PER_TABLE = 80 # 单表统计列数上限
LLM_INFER_BATCH = 25            # LLM 每批推断列数
MAX_ENUM_PROBE_COLS = 30        # 单表枚举探测列数上限（控制 SQL 数量）

_SAFE_IDENT = re.compile(r"^[A-Za-z_一-鿿][A-Za-z0-9_一-鿿$]*$")
_NUMERIC_HINT = ("int", "decimal", "numeric", "float", "double", "number", "real", "money")
_DATE_HINT = ("date", "time", "timestamp")
_TEXT_HINT = ("char", "text", "string", "varchar", "clob")


def _quote(driver: str, ident: str) -> str:
    if driver in ("mysql", "doris", "starrocks", "hive"):
        return f"`{ident}`"
    return f'"{ident}"'


def _safe(driver: str, ident: str) -> str | None:
    """标识符白名单校验，不通过则跳过探测（防注入，名字来自库元数据仍防御）。"""
    ident = (ident or "").strip()
    if not ident or len(ident) > 128 or not _SAFE_IDENT.match(ident):
        return None
    return _quote(driver, ident)


def _type_kind(dtype: str) -> str:
    t = (dtype or "").lower()
    if any(h in t for h in _NUMERIC_HINT):
        return "numeric"
    if any(h in t for h in _DATE_HINT):
        return "datetime"
    if any(h in t for h in _TEXT_HINT):
        return "text"
    return "other"


def _qr(result: Any) -> tuple[list[str], list[list[Any]]]:
    """兼容 QueryResult 对象 / dict 两种返回。"""
    if isinstance(result, dict):
        cols = result.get("columns") or []
        rows = result.get("rows") or []
    else:
        cols = getattr(result, "columns", None) or []
        rows = getattr(result, "rows", None) or []
    norm_rows: list[list[Any]] = []
    for r in rows:
        if isinstance(r, dict):
            norm_rows.append([r.get(c) for c in cols])
        elif isinstance(r, (list, tuple)):
            norm_rows.append(list(r))
        else:
            norm_rows.append([r])
    return [str(c) for c in cols], norm_rows


async def _probe_table_stats(conn, driver: str, table_name: str, columns: list[dict[str, Any]]) -> dict[str, Any]:
    """一次聚合 SQL 取行数 + 各列 null 数/基数 + 数值与日期列 min/max。失败退化为仅行数。"""
    qt = _safe(driver, table_name)
    if qt is None:
        return {"row_count": None, "columns": {}}
    probed = [c for c in columns if _safe(driver, str(c.get("name") or ""))][:PROFILE_MAX_COLS_PER_TABLE]
    stats: dict[str, Any] = {"row_count": None, "columns": {}}
    selects = ["COUNT(*) AS __n"]
    for c in probed:
        qn = _safe(driver, str(c["name"]))
        key = str(c["name"])
        selects.append(f"COUNT(*) - COUNT({qn}) AS n__{key}")
        selects.append(f"COUNT(DISTINCT {qn}) AS d__{key}")
        kind = _type_kind(str(c.get("type") or ""))
        if kind in ("numeric", "datetime"):
            selects.append(f"MIN({qn}) AS lo__{key}")
            selects.append(f"MAX({qn}) AS hi__{key}")
    sql = f"SELECT {', '.join(selects)} FROM {qt}"
    try:
        raw = await conn.execute_select(sql, limit=1, timeout_s=120)
        cols, rows = _qr(raw)
        if rows:
            row = rows[0]
            by_name = {cols[i]: row[i] for i in range(min(len(cols), len(row)))}
            stats["row_count"] = by_name.get("__n")
            for c in probed:
                key = str(c["name"])
                entry: dict[str, Any] = {
                    "null_count": by_name.get(f"n__{key}"),
                    "distinct_count": by_name.get(f"d__{key}"),
                }
                if f"lo__{key}" in by_name:
                    entry["min"] = by_name.get(f"lo__{key}")
                    entry["max"] = by_name.get(f"hi__{key}")
                stats["columns"][key] = entry
    except Exception as exc:  # 聚合失败退化为仅行数
        logger.warning("profile_stats_fallback table=%s err=%s", table_name, str(exc)[:200])
        try:
            raw = await conn.execute_select(f"SELECT COUNT(*) AS __n FROM {qt}", limit=1, timeout_s=60)
            cols, rows = _qr(raw)
            if rows:
                stats["row_count"] = rows[0][0]
        except Exception as exc2:
            logger.warning("profile_rowcount_failed table=%s err=%s", table_name, str(exc2)[:200])
            stats["gap"] = f"统计探测失败: {str(exc2)[:120]}"
    return stats


async def _probe_enums(conn, driver: str, table_name: str, col_name: str) -> list[dict[str, Any]] | None:
    """低基数文本列枚举探测：真实 GROUP BY 取 TOP N 值及占比。"""
    qt, qn = _safe(driver, table_name), _safe(driver, col_name)
    if qt is None or qn is None:
        return None
    sql = (
        f"SELECT {qn} AS v, COUNT(*) AS c FROM {qt} "
        f"WHERE {qn} IS NOT NULL GROUP BY {qn} ORDER BY c DESC LIMIT {ENUM_TOP_N}"
    )
    try:
        raw = await conn.execute_select(sql, limit=ENUM_TOP_N, timeout_s=120)
        cols, rows = _qr(raw)
        out = []
        for r in rows:
            if len(r) >= 2:
                out.append({"value": None if r[0] is None else str(r[0])[:100], "count": r[1]})
        return out or None
    except Exception as exc:
        logger.warning("profile_enum_failed %s.%s err=%s", table_name, col_name, str(exc)[:150])
        return None


def _column_samples(sample_rows: list[dict[str, Any]], col_name: str, limit: int = 3) -> list[str]:
    vals: list[str] = []
    for row in sample_rows or []:
        if not isinstance(row, dict):
            continue
        v = row.get(col_name)
        if v is None:
            continue
        s = str(v)[:60]
        if s not in vals:
            vals.append(s)
        if len(vals) >= limit:
            break
    return vals


async def _infer_column_meanings(db: AsyncSession, pending: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    """LLM 批量推断无注释列的业务含义。输入含真实样本值；失败留缺口不编造。"""
    if not pending:
        return {}
    from app.models_hub.router import ModelRouter

    try:
        llm = await ModelRouter.get_llm(db=db, provider=None, model=None, user_id=None, response_style="precise")
    except Exception as exc:
        logger.warning("profile_llm_unavailable err=%s", str(exc)[:200])
        return {}
    system = (
        "你是数据仓库专家。根据表名、列名、数据类型和真实样本值，推断每列的业务含义。\n"
        "要求：简洁中文（不超过20字）；只描述业务含义，不要重复列名；无法判断时该列返回空字符串。\n"
        '返回 JSON 数组: [{"table":"...","column":"...","meaning":"..."}]，不要输出其他内容。'
    )
    result: dict[tuple[str, str], str] = {}
    for i in range(0, len(pending), LLM_INFER_BATCH):
        batch = pending[i : i + LLM_INFER_BATCH]
        user = json.dumps(batch, ensure_ascii=False, default=str)
        try:
            resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if not match:
                continue
            for item in json.loads(match.group(0)):
                if not isinstance(item, dict):
                    continue
                t, c = str(item.get("table") or ""), str(item.get("column") or "")
                m = str(item.get("meaning") or "").strip()[:60]
                if t and c and m:
                    result[(t, c)] = m
        except Exception as exc:
            logger.warning("profile_infer_batch_failed err=%s", str(exc)[:200])
    return result


async def build_schema_profile(
    db: AsyncSession,
    source: DataSource,
    *,
    trigger: str = "manual",
    profile_id: int | None = None,
) -> DsSchemaProfile:
    """构建完整画像并落库。返回画像行（status=ready/failed）。"""
    started = time.monotonic()

    async def _fail(row: DsSchemaProfile, msg: str) -> DsSchemaProfile:
        row.status = "failed"
        row.error = msg[:2000]
        row.duration_ms = int((time.monotonic() - started) * 1000)
        await db.flush()
        return row

    # 版本与占位行
    prev = await db.execute(
        select(DsSchemaProfile)
        .where(DsSchemaProfile.data_source_id == str(source.id))
        .order_by(DsSchemaProfile.version.desc())
        .limit(1)
    )
    last = prev.scalar_one_or_none()
    if profile_id is not None:
        row = await db.get(DsSchemaProfile, profile_id)
        if row is None:
            row = DsSchemaProfile(data_source_id=str(source.id), version=(last.version + 1) if last else 1)
            db.add(row)
    else:
        row = DsSchemaProfile(data_source_id=str(source.id), version=(last.version + 1) if last else 1)
        db.add(row)
    row.trigger = trigger
    row.status = "building"
    await db.flush()

    driver = str(getattr(source, "driver", "") or "")
    if driver in ("excel_folder", "excel_template"):
        return await _fail(row, "Excel 类数据源暂不支持 Schema 画像（阶段一仅覆盖数据库类数据源）")

    # 注册的 data 角色表
    reg = await db.execute(
        select(DataSourceTable).where(DataSourceTable.data_source_id == str(source.id))
    )
    reg_tables = [t for t in reg.scalars().all() if t.role == DataSourceTableRole.data]
    if not reg_tables:
        return await _fail(row, "数据源未注册任何数据表，请先在数据源设置中选择表")
    table_names = [t.table_name for t in reg_tables][:PROFILE_MAX_TABLES]

    # 1. 结构内省（列元数据 + 真实样本行）
    try:
        tables_meta = await introspect_tables(source, table_names)
    except Exception as exc:
        return await _fail(row, f"结构内省失败: {str(exc)[:300]}")

    # 2. 统计探测（行数/null/基数/min/max）+ 3. 枚举探测
    conn = build_connector_from_source(source)
    stats_map: dict[str, Any] = {}
    enum_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
    try:
        for meta in tables_meta:
            tname = str(meta.get("table_name") or "")
            cols = meta.get("columns") or []
            stats = await _probe_table_stats(conn, driver, tname, cols)
            stats_map[tname] = stats
            row_count = stats.get("row_count") or 0
            enum_budget = MAX_ENUM_PROBE_COLS
            for c in cols:
                if enum_budget <= 0:
                    break
                name = str(c.get("name") or "")
                cstats = (stats.get("columns") or {}).get(name) or {}
                distincts = cstats.get("distinct_count")
                if (
                    _type_kind(str(c.get("type") or "")) == "text"
                    and isinstance(distincts, int)
                    and 0 < distincts <= ENUM_MAX_CARDINALITY
                    and isinstance(row_count, int)
                    and row_count > 0
                ):
                    values = await _probe_enums(conn, driver, tname, name)
                    if values:
                        enum_map[(tname, name)] = values
                        enum_budget -= 1
    finally:
        try:
            await conn.close()
        except Exception:
            pass

    # 4. LLM 推断无注释列业务含义（基于真实样本/枚举）
    pending: list[dict[str, Any]] = []
    for meta in tables_meta:
        tname = str(meta.get("table_name") or "")
        samples = meta.get("sample_rows") or []
        for c in (meta.get("columns") or [])[:PROFILE_MAX_COLS_PER_TABLE]:
            name = str(c.get("name") or "")
            if str(c.get("comment") or "").strip():
                continue
            item: dict[str, Any] = {
                "table": tname,
                "column": name,
                "type": str(c.get("type") or ""),
                "samples": _column_samples(samples, name),
            }
            enums = enum_map.get((tname, name))
            if enums:
                item["enum_values"] = [e["value"] for e in enums[:10]]
            pending.append(item)
    inferred = await _infer_column_meanings(db, pending) if pending else {}

    # 5. 主外键/关联识别（复用现有推断）
    join_graph = infer_join_graph(
        [{"table_name": str(m.get("table_name") or ""), "columns": m.get("columns") or []} for m in tables_meta]
    )

    # 6. 组装画像 + 质量报告
    profile_tables: list[dict[str, Any]] = []
    total_cols = 0
    fully_null: list[str] = []
    high_null: list[str] = []
    gaps: list[str] = []
    row_counts: dict[str, Any] = {}
    for meta in tables_meta:
        tname = str(meta.get("table_name") or "")
        stats = stats_map.get(tname) or {}
        row_count = stats.get("row_count")
        row_counts[tname] = row_count
        if stats.get("gap"):
            gaps.append(f"{tname}: {stats['gap']}")
        commented = 0
        out_cols: list[dict[str, Any]] = []
        for c in (meta.get("columns") or [])[:PROFILE_MAX_COLS_PER_TABLE]:
            name = str(c.get("name") or "")
            comment = str(c.get("comment") or "").strip()
            cstats = (stats.get("columns") or {}).get(name) or {}
            null_count = cstats.get("null_count")
            null_rate = None
            if isinstance(null_count, int) and isinstance(row_count, int) and row_count > 0:
                null_rate = round(null_count / row_count, 4)
                if null_rate >= 0.999:
                    fully_null.append(f"{tname}.{name}")
                elif null_rate >= 0.5:
                    high_null.append(f"{tname}.{name}")
            entry: dict[str, Any] = {
                "name": name,
                "type": str(c.get("type") or ""),
                "comment": comment,
                "inferred_comment": inferred.get((tname, name)) or "",
                "is_key": is_key_column(name),
                "null_rate": null_rate,
                "distinct_count": cstats.get("distinct_count"),
                "samples": _column_samples(meta.get("sample_rows") or [], name),
            }
            if cstats.get("min") is not None or cstats.get("max") is not None:
                entry["min"] = str(cstats.get("min"))[:60] if cstats.get("min") is not None else None
                entry["max"] = str(cstats.get("max"))[:60] if cstats.get("max") is not None else None
            enums = enum_map.get((tname, name))
            if enums:
                entry["enum_values"] = enums
            if comment:
                commented += 1
            out_cols.append(entry)
        col_n = len(out_cols)
        total_cols += col_n
        profile_tables.append(
            {
                "table_name": tname,
                "row_count": row_count,
                "column_count": col_n,
                "comment_coverage": round(commented / col_n, 3) if col_n else None,
                "columns": out_cols,
            }
        )

    if pending and not inferred:
        gaps.append("字段含义推断不可用（LLM 未配置或调用失败），仅保留原始注释")

    profile_doc = {
        "tables": profile_tables,
        "join_graph": join_graph,
        "quality": {
            "total_tables": len(profile_tables),
            "total_columns": total_cols,
            "fully_null_columns": fully_null[:50],
            "high_null_columns": high_null[:50],
            "gaps": gaps[:20],
        },
    }
    row.profile = profile_doc
    row.table_count = len(profile_tables)
    row.column_count = total_cols
    row.row_counts = row_counts
    row.status = "ready"
    row.duration_ms = int((time.monotonic() - started) * 1000)
    await db.flush()
    return row


async def get_latest_profile(db: AsyncSession, data_source_id: str, *, ready_only: bool = True) -> DsSchemaProfile | None:
    stmt = select(DsSchemaProfile).where(DsSchemaProfile.data_source_id == str(data_source_id))
    if ready_only:
        stmt = stmt.where(DsSchemaProfile.status == "ready")
    stmt = stmt.order_by(DsSchemaProfile.version.desc()).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def profile_column_lookup(profile_row: DsSchemaProfile | None) -> dict[tuple[str, str], dict[str, Any]]:
    """(table_name, column_name_lower) -> 画像列信息，供问数 prompt 注入使用。"""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if not profile_row or not isinstance(profile_row.profile, dict):
        return out
    for table in profile_row.profile.get("tables") or []:
        tname = str(table.get("table_name") or "")
        for col in table.get("columns") or []:
            name = str(col.get("name") or "")
            if tname and name:
                out[(tname, name.lower())] = col
    return out
