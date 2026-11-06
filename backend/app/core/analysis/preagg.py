"""P6 预聚合：注册表驱动的本地物化 + 执行器拦截（蓝图「预聚合视图 / 缓存」）。

- refresh_preagg：远端源 GROUP BY 拉取 → 元数据库本地表全量替换；
- try_preagg：AnalysisSpec 命中注册规格（维度集合 / 指标表达式 / 粒度一致，
  过滤字段全部落在分组维度）时直接查本地表，否则返回 None 回退直查；
- studio.refresh_preaggs：beat 每分钟检查到期注册项并刷新。

只登记可重聚合指标（SUM/COUNT/MIN/MAX）：整体/跨期口径由本地表二次聚合得出，
AVG 等不可重算指标在登记时即拒绝，保证数字与直查一致。
"""
from __future__ import annotations

import datetime
import logging
import re
import time
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.analysis.spec import IDENT, _date_expr, query_timeout
from app.core.data_ask.connectors.factory import build_connector_from_source
from app.core.data_ask.govern.column_policy import validate_sql_columns
from app.core.data_ask.govern.sql_guard import validate_select_sql
from app.db.models import DataSource, PreAggregate

logger = logging.getLogger("studio_p6")

_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
PreSessionLocal = async_sessionmaker(_engine, expire_on_commit=False)

_REAGG = re.compile(r"^\s*(SUM|COUNT|MIN|MAX)\s*\(", re.I)
_FORBIDDEN = re.compile(r"(;|--|/\*|\*/)", re.I)
_GRAN_LEN = {"day": 10, "month": 7}
_BATCH = 500


def preagg_table_name(preagg_id: str) -> str:
    return f"analysis_preagg_{str(preagg_id).replace('-', '')[:12]}"


def _norm_expr(expr: str) -> str:
    return re.sub(r"\s+", "", str(expr or "")).upper()


def _agg_fn(expr: str) -> str:
    m = _REAGG.match(expr or "")
    return m.group(1).upper() if m else ""


def validate_preagg_def(dims: list[str], metrics: list[dict[str, Any]],
                        time_field: str, granularity: str) -> str | None:
    """登记校验，返回错误消息或 None。"""
    if not dims and not time_field:
        return "至少需要一个分组维度或时间维度"
    if len(dims) > 4:
        return "维度最多 4 个"
    for d in dims:
        if not IDENT.match(str(d)):
            return f"维度字段非法: {d}"
    if not (1 <= len(metrics) <= 6):
        return "指标需要 1-6 个"
    for m in metrics:
        expr = str(m.get("expr") or "")
        if _FORBIDDEN.search(expr) or not _REAGG.match(expr):
            return f"指标仅支持可重聚合表达式（SUM/COUNT/MIN/MAX）: {expr}"
        if not IDENT.match(str(m.get("alias") or "")):
            return f"指标别名非法: {m.get('alias')}"
    if time_field and not IDENT.match(time_field):
        return f"时间字段非法: {time_field}"
    if granularity not in ("", "day", "month"):
        return "粒度仅支持 day / month"
    return None


# ── 本地物化 ──────────────────────────────────────────────

async def _ensure_local_table(db: AsyncSession, pa: PreAggregate) -> str:
    """本地表列布局：c0=期间(VARCHAR32)，c1..c{len(dims)}=维度(TEXT)，其后=指标(DOUBLE)。"""
    tname = preagg_table_name(str(pa.id))
    dims = list(pa.dimensions or [])
    metrics = list(pa.metrics or [])
    cols = ["c0 VARCHAR(32)"]
    cols += [f"c{i + 1} TEXT" for i in range(len(dims))]
    cols += [f"c{len(dims) + 1 + i} DOUBLE PRECISION" for i in range(len(metrics))]
    await db.execute(text(f'CREATE TABLE IF NOT EXISTS {tname} ({", ".join(cols)})'))
    return tname


async def refresh_preagg(db: AsyncSession, pa: PreAggregate) -> int:
    """远端拉取并全量替换本地表，返回行数；失败抛异常（状态写入由调用方处理）。"""
    source = await db.get(DataSource, str(pa.data_source_id))
    if source is None:
        raise RuntimeError("数据源不存在")
    driver = str(getattr(source, "driver", "") or "")
    table = str(pa.source_table or "").strip()
    if not IDENT.match(table):
        raise RuntimeError("source_table 非法")

    dims = list(pa.dimensions or [])
    metrics = list(pa.metrics or [])
    select_parts: list[str] = []
    group_parts: list[str] = []
    if pa.granularity:
        select_parts.append(f"{_date_expr(pa.time_field, pa.granularity, driver)} AS t_period")
        group_parts.append("t_period")
    for i, d in enumerate(dims):
        select_parts.append(f"{d} AS d{i}")
        group_parts.append(f"d{i}")
    for i, m in enumerate(metrics):
        select_parts.append(f"{m['expr']} AS m{i}")
    sql = f"SELECT {', '.join(select_parts)} FROM {table} GROUP BY {', '.join(group_parts)}"

    ok, msg = validate_select_sql(sql, allowed_tables={table}, dialect=driver)
    if not ok:
        raise RuntimeError(f"SQL 被拒绝: {msg}")
    ok, msg = validate_sql_columns(
        sql, semantic_model=getattr(source, "semantic_model", None) or {},
        user_is_admin=True, scope=None)
    if not ok:
        raise RuntimeError(f"字段被拒绝: {msg}")

    connector = build_connector_from_source(source)
    try:
        qr = await connector.execute_select(sql, limit=200000, timeout_s=query_timeout())
    finally:
        await connector.close()

    tname = await _ensure_local_table(db, pa)
    await db.execute(text(f"DELETE FROM {tname}"))
    n_cols = 1 + len(dims) + len(metrics)
    placeholders = ", ".join(f":c{i}" for i in range(n_cols))
    col_names = ", ".join(f"c{i}" for i in range(n_cols))
    insert_sql = text(f"INSERT INTO {tname} ({col_names}) VALUES ({placeholders})")
    buf: list[dict[str, Any]] = []
    total = 0
    for r in qr.rows:
        vals = list(r) + [None] * (n_cols - len(r))
        row: dict[str, Any] = {}
        k = 0
        if pa.granularity:
            row["c0"] = str(vals[0])[:32] if vals[0] is not None else None
            k = 1
        for i in range(len(dims)):
            v = vals[k + i]
            row[f"c{k + i}"] = None if v is None else str(v)
        base = 1 + len(dims)
        for i in range(len(metrics)):
            v = vals[base + i]
            try:
                row[f"c{base + i}"] = float(v) if v is not None else None
            except (TypeError, ValueError):
                row[f"c{base + i}"] = None
        buf.append(row)
        if len(buf) >= _BATCH:
            await db.execute(insert_sql, buf)
            total += len(buf)
            buf = []
    if buf:
        await db.execute(insert_sql, buf)
        total += len(buf)
    pa.last_refresh_at = datetime.datetime.now(datetime.timezone.utc)
    pa.last_status = "ok"
    pa.last_rows = total
    return total


async def refresh_due_preaggs() -> None:
    """beat 入口：刷新所有到期且启用的预聚合。"""
    async def _run() -> None:
        async with PreSessionLocal() as db:
            now = datetime.datetime.now(datetime.timezone.utc)
            rows = (
                await db.execute(select(PreAggregate).where(PreAggregate.active.is_(True)))
            ).scalars().all()
            for pa in rows:
                if pa.last_refresh_at and (now - pa.last_refresh_at) < datetime.timedelta(
                    minutes=max(1, int(pa.refresh_interval_min or 60))
                ):
                    continue
                try:
                    await refresh_preagg(db, pa)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("preagg %s refresh failed: %s", pa.id, exc)
                    pa.last_status = str(exc)[:255]
            await db.commit()

    from app.core.tasks_runtime import run_in_persistent_loop
    run_in_persistent_loop(_run())


# ── 执行器拦截 ────────────────────────────────────────────

def _match(pa: PreAggregate, spec: dict[str, Any]) -> bool:
    if not pa.active or spec["type"] in ("detail", "impact", "cohort", "funnel"):
        return False
    if spec.get("order_by"):
        return False
    dims = list(spec["dimensions"])
    pa_dims = list(pa.dimensions or [])
    if len(dims) > len(pa_dims) or not set(dims) <= set(pa_dims):
        return False  # 规格维度须为预聚合维度子集（本地只按规格维度分组，其余跨组聚合）
    pa_metrics = list(pa.metrics or [])
    pa_exprs = [_norm_expr(m["expr"]) for m in pa_metrics]
    if any(_norm_expr(m["expr"]) not in pa_exprs for m in spec["metrics"]):
        return False  # 规格指标须为预聚合指标的子集（本地按列取数再聚合）
    tr = spec.get("time_range")
    if tr:
        # 规格带时间口径：粒度必须与预聚合一致（本地按期间过滤，不再二次聚合时间）
        if not pa.granularity or tr.get("granularity") != pa.granularity:
            return False
    # 规格无时间口径：任意粒度的预聚合都可跨期二次聚合（本地 SUM 全部期间）
    for f in spec.get("filters") or []:
        fld = str(f.get("field") or "")
        if fld == pa.time_field and pa.time_field:
            return False  # 时间条件只认 time_range，其余时间过滤回退直查
        if fld not in dims:
            return False
        if str(f.get("op") or "") not in ("eq", "ne", "in"):
            return False
    return True


def _dim_filter_sql(op: str, col: str, value: Any, params: dict[str, Any]) -> str:
    key = f"p{len(params)}"
    if op == "eq":
        params[key] = str(value)
        return f"{col} = :{key}"
    if op == "ne":
        params[key] = str(value)
        return f"{col} <> :{key}"  # 与远端一致：NULL 不满足 <>，天然排除
    values = list(value) if isinstance(value, (list, tuple)) else [value]
    if not values:
        return "1 = 0"
    keys = []
    for v in values:
        k = f"p{len(params)}"
        params[k] = str(v)
        keys.append(f":{k}")
    if op == "in":
        return f"{col} IN ({', '.join(keys)})"
    raise ValueError(f"unsupported op: {op}")


async def try_preagg(db: AsyncSession, source: DataSource, spec: dict[str, Any]) -> dict[str, Any] | None:
    """命中注册预聚合则从本地表出数；任何异常都回退直查（返回 None）。"""
    matched: PreAggregate | None = None
    try:
        rows_pa = (
            await db.execute(
                select(PreAggregate).where(
                    PreAggregate.data_source_id == str(source.id),
                    PreAggregate.active.is_(True),
                )
            )
        ).scalars().all()
        for pa in rows_pa:
            if _match(pa, spec):
                matched = pa
                break
    except Exception as exc:  # noqa: BLE001
        logger.warning("preagg lookup failed: %s", exc)
        return None
    if matched is None:
        return None
    pa = matched
    started = time.perf_counter()
    try:
        dims = list(spec["dimensions"])
        pa_dims = list(pa.dimensions or [])
        pa_metrics = list(pa.metrics or [])
        params: dict[str, Any] = {}

        sel: list[str] = []
        grp: list[str] = []
        is_ts = bool(spec.get("time_range"))
        if is_ts:
            sel.append("c0")  # 本地表列布局：c0=期间，c1..=维度，其后=指标
            grp.append("c0")
        dim_col: dict[str, str] = {}
        for d in dims:
            i = pa_dims.index(d)
            col = f"c{i + 1}"
            dim_col[d] = col
            sel.append(col)
            grp.append(col)
        for m in spec["metrics"]:
            expr = _norm_expr(m["expr"])
            i = next(j for j, pm in enumerate(pa_metrics) if _norm_expr(pm["expr"]) == expr)
            fn = _agg_fn(m["expr"])
            agg = "SUM" if fn in ("SUM", "COUNT") else fn
            sel.append(f"{agg}(c{1 + len(pa_dims) + i})")
        where: list[str] = []
        if is_ts and pa.granularity:
            glen = _GRAN_LEN.get(pa.granularity, 10)
            tr = spec["time_range"]
            if tr.get("start"):
                params["ps"] = str(tr["start"])[:glen]
                where.append("c0 >= :ps")
            if tr.get("end"):
                params["pe"] = str(tr["end"])[:glen]
                where.append("c0 <= :pe")
        for f in spec.get("filters") or []:
            fld = str(f.get("field") or "")
            where.append(_dim_filter_sql(str(f.get("op")), dim_col[fld], f.get("value"), params))

        sql = f"SELECT {', '.join(sel)} FROM {preagg_table_name(str(pa.id))}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        if grp:
            sql += " GROUP BY " + ", ".join(grp)
        if is_ts:
            sql += " ORDER BY c0 ASC"
        elif dims and spec["metrics"]:
            sql += f" ORDER BY {len(dims) + 1} DESC"  # 第一个指标列，与标准路径一致
        sql += f" LIMIT {int(spec['limit'])}"

        res = await db.execute(text(sql), params)
        raw = [list(r) for r in res.all()]
        columns = ([("t_period")] if is_ts else []) + dims + [m["alias"] for m in spec["metrics"]]
        # 与标准路径一致的确定性排序（本地引擎同样不承诺次序之外的语义）
        if is_ts:
            raw.sort(key=lambda r: str(r[0]))
        elif dims:
            mi = len(dims)
            if mi < len(columns):
                raw.sort(key=lambda r: _to_float(r[mi]) or 0.0, reverse=True)

        from app.core.analysis.derived import DerivedError, derive
        from app.core.analysis.facts import build_facts
        from app.core.analysis.spec import chart_hint, spec_hash
        chart = chart_hint(spec)
        try:
            result = derive(spec, columns, raw)
        except DerivedError as exc:
            raise RuntimeError(str(exc)) from exc
        refreshed = str(pa.last_refresh_at or "")
        preagg_fact = {
            "text": f"预聚合命中：{pa.name}（本地物化 {pa.last_rows} 行，"
                    f"刷新于 {refreshed[:19].replace('T', ' ')}，口径 {pa.granularity or '全期'}）",
            "from": f"preagg:{pa.id}",
        }
        elapsed_ms = int((__import__("time").perf_counter() - started) * 1000)
        if result is not None:
            result["facts"] = [preagg_fact] + list(result.get("facts") or [])
            result["facts"] = [
                f if f.get("from") != "rows" else {**f, "text": f["text"] + "（基于预聚合数据）"}
                for f in result["facts"]
            ]
            facts = result["facts"]
            columns = result["columns"]
            raw = result["rows"]
            chart = result["chart"]
        else:
            facts = [preagg_fact] + build_facts(spec, columns, raw)
        return {
            "run_id": str(uuid.uuid4()),
            "spec_hash": spec_hash(spec),
            "spec": spec,
            "columns": columns,
            "rows": raw,
            "row_count": len(raw),
            "facts": facts,
            "chart": chart,
            "query": {
                "sql": sql,
                "elapsed_ms": elapsed_ms,
                "truncated": False,
                "preagg": {
                    "id": str(pa.id), "name": pa.name,
                    "table": preagg_table_name(str(pa.id)),
                    "refreshed_at": refreshed,
                    "rows": int(pa.last_rows or 0),
                },
            },
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("preagg %s serve failed, fallback: %s", pa.id, exc)
        return None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── Celery 任务 ───────────────────────────────────────────

def register_task() -> None:
    from app.worker import celery_app

    @celery_app.task(name="studio.refresh_preaggs")
    def refresh_preaggs_task() -> None:  # noqa: F811
        """每分钟检查到期预聚合并刷新（studio.refresh_preaggs）。"""
        refresh_due_preaggs()


register_task()
