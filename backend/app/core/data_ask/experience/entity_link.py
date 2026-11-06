"""维度值实体归一：把「西安店」这类口语说法对到数据里的真实取值「西安广场超市」。

三层闭环：
L1 别名词典 ds_dim_alias —— 由维度真实取值自动派生别名，并保存用户确认过的写法；
L2 召回打分 —— 精确/短名/编辑距离多路召回，≥0.9 直接使用，0.6~0.9 反问候选；
L3 SQL 护栏 —— 问题点名了具体门店但生成的 SQL 没有门店过滤时，不执行、转反问。
"""
from __future__ import annotations

import re
import uuid
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataSource, DataSourceTable, DataSourceTableRole, DsDimAlias

# 参与实体归一的维度列（门店/卖场名称类）
STORE_COLUMNS = ("FDMC", "FDBHMC", "MDMC")

# 门店说法后缀：去掉后剩下的核心名字用于别名与比对
_SUFFIXES = (
    "购物中心", "生活超市", "超级市场", "超市", "门店", "分店", "商场",
    "卖场", "门市", "广场", "中心", "店",
)
_SUFFIX_RE = re.compile("(?:" + "|".join(_SUFFIXES) + ")$")
_STORE_HINT = re.compile(r"门店|分店|超市|商场|卖场|门市|广场|店")
# 问题中「X门店/X店」的写法（X 只取汉字字母，避免把日期数字带进店名）
_PHRASE_RE = re.compile(
    r"([\u4e00-\u9fa5A-Za-z]{1,8})(购物中心|生活超市|超级市场|超市|门店|分店|商场|卖场|门市|店)"
)
# 聚合口径：问的是所有门店/门店对比，不应被实体澄清拦住
_AGGREGATE = (
    "各门店", "各店", "全部门店", "所有门店", "全部门店", "全部店", "所有店", "各分店",
    "按门店", "分门店", "分店排名", "门店排名", "各个门店", "每家门店", "每家店", "每个门店",
    "每个店", "门店对比", "门店之间", "各超市", "各商场", "门店销售排名", "各卖场",
)
# 生成 SQL 里出现即视为「按门店维度过滤/分组」
_DIM_FILTER_RE = re.compile(
    r"(?:[\w\"`]+\.)?(FDMC|FDBHMC|MDMC|FDBH)\b\s*(?:=|LIKE|IN|<>|!=)", re.IGNORECASE
)
_GENERIC_ALIAS = {"门店", "分店", "超市", "商场", "卖场", "门市", "广场", "店", "中心"}


def _norm(text: str) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:“”\"'（）()]+", "", (text or "")).lower()


def _strip_alias(name: str) -> str:
    """去掉门店类后缀，得到核心名；过短则保持原样。"""
    text = (name or "").strip()
    core = _SUFFIX_RE.sub("", text)
    return core if len(core) >= 2 else text


def _alias_variants(canonical: str) -> list[tuple[str, str, float]]:
    """规范值 → [(别名, 类型, 置信度)]。"""
    base = (canonical or "").strip()
    if not base:
        return []
    out: list[tuple[str, str, float]] = [(base, "canonical", 1.0)]
    core = _strip_alias(base)
    if core != base:
        out.append((core, "strip", 0.95))
        out.append((f"{core}店", "strip", 0.93))
    # 城市/商圈短名：核心名前 2 个字（如 西安广场超市 → 西安）
    head = core[:2]
    if len(core) >= 3 and len(head) >= 2 and head not in _GENERIC_ALIAS:
        out.append((head, "city", 0.9))
    seen: set[str] = set()
    uniq: list[tuple[str, str, float]] = []
    for alias, kind, conf in out:
        key = _norm(alias)
        if key in _GENERIC_ALIAS or key in seen or len(key) < 2:
            continue
        seen.add(key)
        uniq.append((alias, kind, conf))
    return uniq


def _contain_score(question: str, alias: str) -> float:
    """别名完整出现在问题里的得分：越长越可信，两个字的城市短名给 0.9。"""
    norm_alias = _norm(alias)
    if not norm_alias or norm_alias not in question:
        return 0.0
    if len(norm_alias) >= 4:
        return 1.0
    if len(norm_alias) == 3:
        return 0.97
    return 0.9


def _fuzzy_score(phrase: str, alias: str) -> float:
    """错字/漏字兜底：编辑距离相似度，按 0.85 折算，避免误命中。"""
    if not phrase or not alias:
        return 0.0
    return SequenceMatcher(None, phrase, alias).ratio() * 0.85


def _clean_prefix(prefix: str) -> str:
    """去掉日期/时间词（「日西安」「6日」这类），只留店名核心。"""
    return re.sub(r"^(?:\d+|[年月日号时点分秒期])+", "", prefix or "")


def _phrases(question: str) -> list[str]:
    """抽出问题里像门店的说法（去掉后缀后的核心名）。"""
    text = _norm(question)
    found: list[str] = []
    for match in _PHRASE_RE.finditer(text):
        raw = match.group(0)
        prefix = _clean_prefix(match.group(1))
        if raw in _AGGREGATE or any(raw.startswith(word) for word in _AGGREGATE):
            continue
        if prefix in ("各", "每", "全", "所有", "各个", "全部") or not prefix:
            continue
        core = _strip_alias(f"{prefix}{match.group(2)}")
        if len(core) >= 2 and core not in found:
            found.append(core)
    return found


def is_aggregate_question(question: str) -> bool:
    text = _norm(question)
    return any(word in text for word in _AGGREGATE)


def _store_columns(tables: list[dict[str, Any]] | None) -> list[tuple[str, str]]:
    """返回 [(表名, 维度列名)]，按 STORE_COLUMNS 顺序。"""
    pairs: list[tuple[str, str]] = []
    for table in tables or []:
        name = str(table.get("table_name") or "")
        for col in table.get("columns") or []:
            col_name = str(col.get("name") if isinstance(col, dict) else col or "")
            if col_name.upper() in STORE_COLUMNS:
                pairs.append((name, col_name))
    # FDMC 优先（事实表门店列用得最多）
    pairs.sort(key=lambda item: STORE_COLUMNS.index(item[1].upper()) if item[1].upper() in STORE_COLUMNS else 9)
    return pairs


def _quote(name: str, driver: str) -> str:
    if driver in ("mysql", "doris", "starrocks"):
        return f"`{name}`"
    return f'"{name}"'


async def refresh_aliases(
    db: AsyncSession,
    source: DataSource,
    tables: list[dict[str, Any]] | None = None,
    *,
    limit: int = 300,
) -> dict[str, int]:
    """从各维度列抽取真实取值，重建自动别名；保留用户确认过的写法。"""
    if tables:
        table_meta = tables
    else:
        rows = (
            await db.execute(
                select(DataSourceTable).where(
                    DataSourceTable.data_source_id == str(source.id),
                    DataSourceTable.role == DataSourceTableRole.data,
                )
            )
        ).scalars().all()
        table_meta = [
            {"table_name": row.table_name, "columns": (row.column_meta or {}).get("columns") or []}
            for row in rows
        ]
    cols = _store_columns(table_meta)
    if not cols:
        return {"tables": 0, "aliases": 0}

    from app.core.data_ask.connectors.factory import build_connector_from_source

    driver = str(source.driver)
    connector = build_connector_from_source(source)
    values: dict[tuple[str, str], list[str]] = {}
    try:
        for table_name, column in cols:
            sql = (
                f"SELECT DISTINCT {_quote(column, driver)} AS V FROM {_quote(table_name, driver)} "
                f"WHERE {_quote(column, driver)} IS NOT NULL"
            )
            try:
                result = await connector.execute_select(sql, limit=limit)
            except Exception:
                continue
            bucket = values.setdefault((table_name, column), [])
            for row in result.rows:
                text = str(row[0]).strip() if row and row[0] is not None else ""
                if text and text not in bucket and len(bucket) < limit:
                    bucket.append(text)
    finally:
        try:
            await connector.close()
        except Exception:
            pass

    # 只清理自动派生的别名与过期候选；人工确认过的写法永久保留
    await db.execute(
        delete(DsDimAlias).where(
            DsDimAlias.data_source_id == str(source.id),
            DsDimAlias.source == "auto",
        )
    )
    await db.execute(
        delete(DsDimAlias).where(
            DsDimAlias.data_source_id == str(source.id),
            DsDimAlias.status == "pending",
        )
    )
    inserted = 0
    seen: set[tuple[str, str, str]] = set()
    for (table_name, column), bucket in values.items():
        for canonical in bucket:
            for alias, kind, conf in _alias_variants(canonical):
                key = (column, canonical, _norm(alias))
                if key in seen:
                    continue  # 多张表都带同一维度列时只留一份
                seen.add(key)
                db.add(
                    DsDimAlias(
                        id=uuid.uuid4().hex,
                        data_source_id=str(source.id),
                        dim_table=table_name[:128],
                        dim_column=column[:64],
                        canonical=canonical[:128],
                        alias=alias[:128],
                        alias_type=kind,
                        confidence=float(conf),
                        source="auto",
                        status="active",
                        hit_count=0,
                    )
                )
                inserted += 1
    await db.flush()
    return {"tables": len(values), "aliases": inserted}


async def _load_aliases(db: AsyncSession, data_source_id: str) -> list[DsDimAlias]:
    result = await db.execute(
        select(DsDimAlias).where(
            DsDimAlias.data_source_id == data_source_id,
            DsDimAlias.status.in_(("active", "confirmed")),
        )
    )
    return list(result.scalars().all())


def _rank(
    question: str,
    aliases: list[DsDimAlias],
    phrases: list[str],
) -> list[dict[str, Any]]:
    """按规范值聚合打分，返回降序候选。"""
    q = _norm(question)
    best: dict[str, dict[str, Any]] = {}
    for row in aliases:
        canonical = str(row.canonical or "").strip()
        alias = str(row.alias or "").strip()
        if not canonical or not alias:
            continue
        score = _contain_score(q, alias)
        if score > 0 and str(row.source or "") == "user":
            score = 1.0  # 用户确认过的写法直接定为最高分，压过城市短名等自动别名
        if score <= 0:
            for phrase in phrases:
                fuzzy = _fuzzy_score(_norm(phrase), _norm(alias))
                score = max(score, fuzzy)
        if score <= 0:
            continue
        item = best.get(canonical)
        confirmed = str(row.source or "") == "user"
        if item is None or score > item["score"]:
            best[canonical] = {
                "canonical": canonical,
                "column": str(row.dim_column or ""),
                "table": str(row.dim_table or ""),
                "alias": alias,
                "alias_type": str(row.alias_type or ""),
                "score": round(float(score), 3),
                "confirmed": confirmed,
            }
        elif confirmed:
            item["confirmed"] = True
    return sorted(best.values(), key=lambda item: item["score"], reverse=True)


async def _pending_options(
    db: AsyncSession, data_source_id: str, phrase: str, candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """为反问候选生成按钮回执 token，落 pending 别名行；点击后升级为确认。"""
    options: list[dict[str, Any]] = []
    for cand in candidates[:3]:
        token = uuid.uuid4().hex[:12]
        db.add(
            DsDimAlias(
                id=uuid.uuid4().hex,
                data_source_id=data_source_id,
                dim_table=str(cand.get("table") or "")[:128] or None,
                dim_column=str(cand.get("column") or "FDMC")[:64],
                canonical=str(cand["canonical"])[:128],
                alias=(phrase or cand["canonical"])[:128],
                alias_type="pending",
                confidence=float(cand.get("score") or 0),
                source="auto",
                status="pending",
                token=token,
                hit_count=0,
            )
        )
        options.append(
            {
                "canonical": cand["canonical"],
                "label": cand["canonical"],
                "score": cand.get("score"),
                "token": token,
            }
        )
    await db.flush()
    return options


async def clarify_options(
    db: AsyncSession, data_source_id: str, entity: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """SQL 护栏转反问时的候选按钮：已命中的规范值排第一，再补最接近的门店。"""
    if not entity:
        return []
    canonical = str(entity.get("canonical") or "")
    pool: list[dict[str, Any]] = []
    if canonical:
        pool.append({
            "canonical": canonical,
            "column": entity.get("column"),
            "table": entity.get("table"),
            "score": 1.0,
        })
    for cand in entity.get("candidates") or []:
        if str(cand.get("canonical") or "") and str(cand.get("canonical")) != canonical:
            pool.append(cand)
    return await _pending_options(db, str(data_source_id), str(entity.get("phrase") or ""), pool[:3])


async def resolve_entities(
    db: AsyncSession,
    source: DataSource,
    tables: list[dict[str, Any]] | None,
    question: str,
    *,
    direct_min: float = 0.9,
    ambiguous_min: float = 0.6,
) -> dict[str, Any]:
    """问句 → 门店实体。返回 mode=none/resolved/clarify。"""
    data_source_id = str(source.id)
    cols = _store_columns(tables)
    if not cols:
        return {"mode": "none"}

    aliases = await _load_aliases(db, data_source_id)
    if not aliases:
        try:
            await refresh_aliases(db, source, tables)
            aliases = await _load_aliases(db, data_source_id)
        except Exception:
            aliases = []
    if not aliases:
        return {"mode": "none"}

    q = _norm(question)
    phrases = _phrases(question)
    has_hint = bool(_STORE_HINT.search(q)) or bool(phrases)
    candidates = _rank(question, aliases, phrases)
    if not has_hint and not candidates:
        return {"mode": "none"}
    if is_aggregate_question(question):
        return {"mode": "none", "aggregate": True}

    top = [c for c in candidates if c["score"] >= direct_min]
    # 用户确认过的写法优先：只信确认项，避免确认后仍被其它门店的短名拖入反问
    picked = [c for c in top if c.get("confirmed")]
    if picked:
        top = picked
    leader = top[0] if top else None
    gap = (leader["score"] - top[1]["score"]) if len(top) > 1 else 1.0
    if leader and gap >= 0.08:
        hit = leader
        await db.execute(
            update(DsDimAlias)
            .where(
                DsDimAlias.data_source_id == data_source_id,
                DsDimAlias.canonical == hit["canonical"],
            )
            .values(hit_count=DsDimAlias.hit_count + 1)
        )
        return {
            "mode": "resolved",
            "phrase": hit["alias"],
            "canonical": hit["canonical"],
            "column": hit["column"],
            "table": hit["table"],
            "score": hit["score"],
            "candidates": candidates[:5],
        }

    # 直接命中多个 + 细分说法 / 或者只落在模糊区间 → 反问，给候选按钮
    band = [c for c in candidates if c["score"] >= ambiguous_min]
    if len(top) >= 2:
        ask_list = top[:3]
    elif band:
        ask_list = band[:3]
    else:
        ask_list = candidates[:3]
    phrase = phrases[0] if phrases else (candidates[0]["alias"] if candidates else "")
    if not ask_list:
        return {"mode": "none"}

    options = await _pending_options(db, data_source_id, phrase, ask_list)
    shown = "、".join(option["label"] for option in options)
    hint = f"问题里的门店「{phrase or shown}」对应到多个门店：{shown}。请确认要查哪一个。"
    if not phrases and len(ask_list) < len(candidates):
        hint = f"没有完全匹配的门店，最接近的是：{shown}。请确认要查哪一个。"
    return {
        "mode": "clarify",
        "phrase": phrase,
        "question": hint,
        "options": options,
        "candidates": candidates[:5],
    }


def entity_hint(entity: dict[str, Any] | None) -> str:
    """把归一结果写成 SQL 生成的硬约束（随 permission_hint 一并进入提示词）。"""
    if not entity or entity.get("mode") != "resolved":
        return ""
    canonical = str(entity.get("canonical") or "")
    column = str(entity.get("column") or "FDMC")
    phrase = str(entity.get("phrase") or "")
    return (
        f"Entity: 问题里的「{phrase}」在本库对应门店 {column} = '{canonical}'。"
        f"必须在 WHERE 中用 {column} = '{canonical}'（或 {column} LIKE '%{canonical}%'）过滤，"
        "不得省略该过滤条件，也不得用样本值替换这个门店。\n"
    )


def sql_missing_entity(sql: str, entity: dict[str, Any] | None, question: str) -> bool:
    """SQL 护栏：点名具体门店却没有门店过滤 → True（应转反问，不执行）。"""
    if not entity or entity.get("mode") != "resolved":
        return False
    if is_aggregate_question(question):
        return False
    canonical = _norm(str(entity.get("canonical") or ""))
    if not canonical:
        return False
    text = _norm(sql)
    if canonical in text:
        return False
    return not bool(_DIM_FILTER_RE.search(sql or ""))


def entities_payload(entity: dict[str, Any] | None) -> dict[str, Any] | None:
    """落 ask_trace.entities 的精简结果。"""
    if not entity or entity.get("mode") == "none":
        return None
    out: dict[str, Any] = {"mode": entity.get("mode")}
    for key in ("phrase", "canonical", "column", "table", "score"):
        if entity.get(key) not in (None, ""):
            out[key] = entity[key]
    if entity.get("options"):
        out["options"] = [
            {"canonical": o.get("canonical"), "score": o.get("score")} for o in entity["options"]
        ]
    if entity.get("aggregate"):
        out["aggregate"] = True
    return out


async def confirm_entity_token(db: AsyncSession, token: str) -> str:
    """企微候选按钮点击回执：把 pending 候选升级为用户确认写法。返回规范值。"""
    row = (
        await db.execute(select(DsDimAlias).where(DsDimAlias.token == str(token or "")).limit(1))
    ).scalar_one_or_none()
    if row is None:
        return ""
    canonical = str(row.canonical or "")
    row.status = "confirmed"
    row.source = "user"
    row.alias_type = "user"
    row.confidence = 1.0
    row.token = None
    # 同写法的其它待选候选作废，避免重复反问
    await db.execute(
        delete(DsDimAlias).where(
            DsDimAlias.data_source_id == row.data_source_id,
            DsDimAlias.alias == row.alias,
            DsDimAlias.status == "pending",
        )
    )
    await db.commit()
    return canonical
