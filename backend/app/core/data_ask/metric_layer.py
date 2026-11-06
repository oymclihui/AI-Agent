"""指标层 v1（蓝图 L1）：意图 → 指标组合 → 确定性拼 SQL。

路由优先级（见 service.py）：sql_override > memory_sql(金标) > 指标层 > LLM。
指标层命中条件：问题能唯一解析出 {指标, 时间, 维度}，且维度在注册表内；
解析不唯一 / 出现预测、环比同比、归因、未标注相对时间等词时返回 None，
交还 LLM 路由。

设计约束：
- 日期条件只产出两种形态：RQ = 'x'（单日）/ RQ BETWEEN 'a' AND 'b'（区间），
  与 comparison.py 的对比改写、date_scope 的单日收敛正则保持兼容。
- 注册表按「列签名」激活（schema 模式驱动）：数据源里存在
  {RQ,FDBH,XSJE,ML,...} / {RQ,FDBH,JYBS,...} 列组合时零售指标自动生效，
  不绑定具体数据源 ID。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# ─────────────────────────── 指标注册表 ───────────────────────────


@dataclass(frozen=True)
class MetricDef:
    key: str
    name: str                    # 结果列别名（中文）
    synonyms: tuple[str, ...]    # 同义词组（含名称本身，最长优先匹配）
    src: str                     # a=销售日报表 b=客流表 x=跨表
    expr: str                    # 聚合表达式模板，{T0}/{T1}=表/子查询别名占位
    unit: str
    ratio: bool = False          # 比率型（展示时按百分比解释）


def _m(key, name, syn, src, expr, unit, ratio=False):
    return MetricDef(key, name, tuple(dict.fromkeys((name, *syn))), src, expr, unit, ratio)


METRICS: dict[str, MetricDef] = {
    m.key: m for m in [
        _m("sales_amount", "销售额",
           ("销售金额", "营业额", "营收", "销售收入", "卖了多少钱", "卖了多少"),
           "a", "ROUND(SUM({T0}.XSJE), 2)", "元"),
        _m("gross_profit", "毛利", ("毛利额",), "a",
           "ROUND(SUM({T0}.ML), 2)", "元"),
        _m("gross_margin", "毛利率", ("利润率",), "a",
           "ROUND(SUM({T0}.ML)/NULLIF(SUM({T0}.XSJE), 0)*100, 2)", "%", ratio=True),
        _m("sales_cost", "销售成本", ("成本",), "a",
           "ROUND(SUM({T0}.XSCB), 2)", "元"),
        _m("txn_count", "交易笔数",
           ("交易次数", "笔数", "客流", "客流量", "成交笔数", "单数"),
           "b", "SUM({T1}.JYBS)", "笔"),
        _m("kl_revenue", "客流营业额", ("客流表营业额",), "b",
           "ROUND(SUM({T1}.YYE), 2)", "元"),
        _m("avg_ticket", "客单价",
           ("平均客单价", "单均", "每单平均", "单笔金额", "平均每单", "平均客单"),
           "x", "ROUND(SUM({T0}.XSJE)/NULLIF(SUM({T1}.JYBS), 0), 2)", "元"),
        _m("store_count", "门店数",
           ("门店数量", "多少家门店", "几家店", "门店家数", "店铺数", "多少家店"),
           "a", "COUNT(DISTINCT {T0}.FDBH)", "家"),
        _m("daily_avg_sales", "日均销售额",
           ("日均销售", "平均每天销售额", "平均日销售额", "每天平均销售额", "日均营收"),
           "a", "ROUND(SUM({T0}.XSJE)/NULLIF(COUNT(DISTINCT {T0}.RQ), 0), 2)", "元"),
        _m("per_store_sales", "店均销售额",
           ("单店销售额", "平均每店销售额", "每店平均销售额", "单店销售", "店均"),
           "a", "ROUND(SUM({T0}.XSJE)/NULLIF(COUNT(DISTINCT {T0}.FDBH), 0), 2)", "元"),
    ]
}

_DIM_STORE = re.compile(r"按门店|各门店|每个门店|分店|门店维度|哪个门店|哪家店|各店|每家店|门店分别|门店")
_DIM_DAY = re.compile(r"每天|按天|每日|按日|趋势|走势|哪一天|哪天|按日期|各天|日维度|分日")
_DIM_MONTH = re.compile(r"按月|每月|各月|月度|哪个月|月维度|分月")
_UNKNOWN_DIM = re.compile(
    r"按(?:业务员|员工|品类|商品|货号|条码|供应商|区域|城市|导购|会员)|"
    r"业务员维度|品类维度|商品维度|员工维度|会员维度"
)

_DECLINE = re.compile(
    r"预测|预估|未来|下月|下周|明年|环比|同比|对比|相比|变化|增长|下降|涨幅|跌幅|"
    r"原因|为什么|为啥|分析|解释|贡献|占比|份额|结构|拆解|明细|清单|名单|导出"
)
# 相对时间词出现但无 _resolve_relative_time 标注（MAX 查询失败等）→ 口径不明，交还 LLM
_REL_WORDS = re.compile(r"昨天|昨日|今天|今日|前天|最近|本周|上周|本月|上月|今年|去年|本年|上年")

_TOP_N = re.compile(r"前\s*([0-9一二三四五六七八九十]+)\s*名?|top\s*([0-9]+)", re.I)
_DESC = re.compile(r"最高|最大|最多|最好|排名|排行|前列|靠前")
_ASC = re.compile(r"最低|最少|最小|最差|垫底")

_STORE_NAME = re.compile(
    r"[\u4e00-\u9fa5A-Za-z0-9]{2,10}"
    r"(?:广场店|超市|分店|便利店|门市|商场|购物中心|旗舰店|专卖店|专营店|连锁店|大卖场|卖场|门店)"
)
# 「门店」类泛化词（按门店/各门店/哪家店…）是维度诉求，不算具体门店名
_STORE_GENERIC = re.compile(r"按门店|各门店|每个门店|哪个门店|哪家店|各店|每家店|门店维度|门店分别|门店数|门店数量|多少家店")

# _resolve_relative_time 追加的机器可读标注
_RE_ANNOTATION = re.compile(
    r"（其中「[^」]*」指\s*(\d{4}-\d{2}-\d{2})(?:\s*至\s*(\d{4}-\d{2}-\d{2}))?[^）]*）"
)
_RE_LATEST_HINT = re.compile(r"数据最新日期为\s*(\d{4}-\d{2}-\d{2})")
_RE_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_RE_CN_YMD = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?")
_RE_CN_MD = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?")
_RE_CN_YM = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月")
_RE_CN_M = re.compile(r"(\d{1,2})\s*月(?![\d日号])")


@dataclass
class TimeRange:
    start: str
    end: str
    origin: str          # annotation / explicit / default_latest

    @property
    def single(self) -> bool:
        return self.start == self.end


@dataclass
class MetricIntent:
    metrics: list[MetricDef]
    dimension: str | None      # store / day / month / None
    time: TimeRange | None
    order: str | None          # desc / asc / None
    limit: int | None
    matched_text: list[str] = field(default_factory=list)


# ─────────────────────────── schema 检测 ───────────────────────────

def _table_columns(table: dict[str, Any]) -> dict[str, str]:
    """upper(列名) -> 实际列名。"""
    out: dict[str, str] = {}
    for c in table.get("columns") or []:
        name = str((c.get("name") if isinstance(c, dict) else c) or "").strip()
        if name:
            out[name.upper()] = name
    return out


def detect_retail_tables(
    all_tables: list[dict[str, Any]] | None,
) -> tuple[dict[str, str] | None, dict[str, str] | None, dict[str, str]]:
    """按列签名找销售日报表(A)/客流表(B)。返回 (A列映射, B列映射, 表名映射)。"""
    tbl_a: dict[str, str] | None = None
    tbl_b: dict[str, str] | None = None
    name_a = name_b = ""
    for t in all_tables or []:
        cols = _table_columns(t)
        names = set(cols)
        tname = str(t.get("table_name") or "")
        if tbl_a is None and {"RQ", "FDBH", "XSJE", "ML"} <= names:
            tbl_a, name_a = cols, tname
        if tbl_b is None and {"RQ", "FDBH", "JYBS"} <= names:
            tbl_b, name_b = cols, tname
    return tbl_a, tbl_b, {"a": name_a, "b": name_b}


# ─────────────────────────── 时间解析 ───────────────────────────

def _md(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def _month_end(y: int, m: int) -> str:
    from calendar import monthrange
    return date(y, m, monthrange(y, m)[1]).isoformat()


def parse_time(question: str, latest_hint: str | None) -> TimeRange | None:
    """解析问题中的时间。解析不出显式时间返回 None（由调用方决定默认口径）。"""
    text = str(question or "")

    # 1) 相对时间标注（_resolve_relative_time 产物，最权威）
    m = _RE_ANNOTATION.search(text)
    if m:
        start, end = m.group(1), m.group(2) or m.group(1)
        return TimeRange(start, end, "annotation")

    # 2) 显式 ISO 日期：两个 → 区间；一个 → 单日
    isos = [_md(int(g[0]), int(g[1]), int(g[2])) for g in _RE_ISO.findall(text)]
    isos = [d for d in isos if d]
    if len(isos) >= 2:
        lo, hi = sorted(isos[:2])
        return TimeRange(lo, hi, "explicit")
    if len(isos) == 1:
        return TimeRange(isos[0], isos[0], "explicit")

    base_year = int((latest_hint or date.today().isoformat())[:4])

    # 2.5) 中文年月日 → 单日。必须先于「年月」整月解析，
    #      否则「2026年10月7日」会被扩成整月 2026-10-01~2026-10-31
    m = _RE_CN_YMD.search(text)
    if m:
        d = _md(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return TimeRange(d, d, "explicit")

    # 3) 中文年月 → 整月
    m = _RE_CN_YM.search(text)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return TimeRange(_md(y, mo, 1), _month_end(y, mo), "explicit")

    # 4) 中文月日（年份取最新营业日所在年），两个 → 区间
    mds = _RE_CN_MD.findall(text)
    days = [_md(base_year, int(a), int(b)) for a, b in mds]
    days = [d for d in days if d]
    if len(days) >= 2:
        lo, hi = sorted(days[:2])
        return TimeRange(lo, hi, "explicit")
    if len(days) == 1:
        return TimeRange(days[0], days[0], "explicit")

    # 5) 裸月份 → 整月
    m = _RE_CN_M.search(text)
    if m and 1 <= int(m.group(1)) <= 12:
        mo = int(m.group(1))
        return TimeRange(_md(base_year, mo, 1), _month_end(base_year, mo), "explicit")

    return None


# ─────────────────────────── 意图解析 ───────────────────────────

def _cn_num(token: str) -> int | None:
    token = token.strip()
    if token.isdigit():
        return int(token)
    s = token.translate(str.maketrans("一二三四五六七八九十", "1234567890"))
    return int(s) if s.isdigit() else None


def parse_metric_intent(
    question: str,
    latest_hint: str | None,
    *,
    has_a: bool,
    has_b: bool,
) -> MetricIntent | None:
    text = str(question or "").strip()
    if not text:
        return None
    if _DECLINE.search(text):
        return None
    if _UNKNOWN_DIM.search(text):
        return None
    if _REL_WORDS.search(text) and not _RE_ANNOTATION.search(text):
        return None

    # 指标匹配：同义词最长优先（保证「毛利率」先于「毛利」、「日均销售额」先于「销售额」），
    # 命中后从文本摘除，避免指标名里的词（如「门店数」的「门店」）误触发维度扫描
    synonyms: list[tuple[str, MetricDef]] = []
    for met in METRICS.values():
        if met.src == "b" and not has_b:
            continue
        if met.src in ("a", "x") and not has_a:
            continue
        if met.src == "x" and not has_b:
            continue
        for syn in met.synonyms:
            synonyms.append((syn, met))
    synonyms.sort(key=lambda x: len(x[0]), reverse=True)

    remain = text
    matched: list[MetricDef] = []
    matched_text: list[str] = []
    for syn, met in synonyms:
        if syn in remain:
            if all(met.key != m.key for m in matched):
                matched.append(met)
                matched_text.append(syn)
            remain = remain.replace(syn, "　")
    if not matched or len(matched) > 4:
        return None
    # 含明确门店名 → 指标层无法做门店值过滤，交还 LLM（否则门店条件被丢弃）。
    # 先摘掉「按门店 / 各门店 / 多少家店」这类泛化维度词，避免误判。
    if _STORE_NAME.search(_STORE_GENERIC.sub("　", text)):
        return None

    # 维度（在摘除指标词后的剩余文本上扫描）
    dimension: str | None = None
    if _DIM_STORE.search(remain):
        dimension = "store"
    elif _DIM_MONTH.search(remain):
        dimension = "month"
    elif _DIM_DAY.search(remain):
        dimension = "day"

    # 排序 / TopN
    order: str | None = None
    limit: int | None = None
    m = _TOP_N.search(remain)
    if m:
        n = _cn_num(m.group(1) or m.group(2) or "")
        if n and 0 < n <= 50:
            limit = n
            order = "desc"
    if _DESC.search(remain):
        order = "desc"
        limit = limit or 1
    elif _ASC.search(remain):
        order = "asc"
        limit = limit or 1
    if order and dimension is None:
        # 「销售额最高」类无维度排序词 → 默认按日找峰值日
        dimension = "day"

    return MetricIntent(
        metrics=matched, dimension=dimension,
        time=parse_time(text, latest_hint),
        order=order, limit=limit, matched_text=matched_text,
    )


# ─────────────────────────── SQL 拼装 ───────────────────────────

def _date_where(tr: TimeRange, rq_col: str) -> str:
    if tr.single:
        return f"{rq_col} = '{tr.start}'"
    return f"{rq_col} BETWEEN '{tr.start}' AND '{tr.end}'"


def build_metric_sql(
    intent: MetricIntent,
    cols_a: dict[str, str] | None,
    cols_b: dict[str, str] | None,
    names: dict[str, str],
) -> tuple[str, str]:
    """确定性拼装。返回 (sql, explanation)；前置条件不满足返回 ("", "")。"""
    cols_a = cols_a or {}
    cols_b = cols_b or {}
    if intent.time is None:
        return "", ""

    srcs = {m.src for m in intent.metrics}
    need_cross = (
        "x" in srcs
        or len(srcs) > 1
        or ("b" in srcs and intent.dimension == "store" and bool(cols_a.get("FDMC")))
    )
    if need_cross and (not cols_a or not cols_b):
        return "", ""
    if "a" in srcs and not cols_a:
        return "", ""
    if "b" in srcs and not cols_b:
        return "", ""

    rq_a = cols_a.get("RQ", "RQ")
    where_a = _date_where(intent.time, rq_a)

    def alias_list(t0: str, t1: str) -> str:
        return ", ".join(f"{met.expr.format(T0=t0, T1=t1)} AS {met.name}" for met in intent.metrics)

    expl_metric = "、".join(
        f"{m.name}={m.expr.replace('{T0}.', '').replace('{T1}.', '')}" for m in intent.metrics
    )
    dim_cn = {"store": "按门店", "day": "按日", "month": "按月"}.get(intent.dimension, "汇总")
    time_cn = intent.time.start if intent.time.single else f"{intent.time.start} 至 {intent.time.end}"
    origin_cn = {"annotation": "相对时间已解析", "explicit": "显式日期",
                 "default_latest": "默认最新营业日"}[intent.time.origin]

    order_by = ""
    metric_pos = ""    # 指标（首个）所在列位置，排名排序用

    if need_cross:
        # ── 跨表：预聚合子查询 JOIN（规避行数基数放大） ──
        rq_b = cols_b["RQ"]
        where_b = _date_where(intent.time, rq_b)
        fdmc = cols_a.get("FDMC")
        with_fdmc = intent.dimension == "store" and bool(fdmc)

        agg_a_cols = [
            f"SUM({cols_a[c]}) AS {c}"
            for c in ("XSJE", "ML", "XSCB")
            if c in cols_a and any(m.src in ("a", "x") for m in intent.metrics)
        ] or [f"SUM({cols_a.get('XSJE', 'XSJE')}) AS XSJE"]
        sub_a = (
            f"(SELECT {rq_a}, {cols_a['FDBH']}" + (f", {fdmc}" if with_fdmc else "") +
            f", {', '.join(agg_a_cols)}\n"
            f"  FROM {names['a']}\n WHERE {where_a}\n"
            f" GROUP BY {rq_a}, {cols_a['FDBH']}" + (f", {fdmc}" if with_fdmc else "") + ") t0"
        )
        sub_b = (
            f"(SELECT {rq_b}, {cols_b['FDBH']}, SUM({cols_b['JYBS']}) AS JYBS"
            + (f", SUM({cols_b['YYE']}) AS YYE" if "YYE" in cols_b else "") +
            f"\n  FROM {names['b']}\n WHERE {where_b}\n"
            f" GROUP BY {rq_b}, {cols_b['FDBH']}) t1"
        )
        join = (f"{sub_a}\nJOIN {sub_b}\n"
                f"  ON t0.{rq_a} = t1.{rq_b} AND t0.{cols_a['FDBH']} = t1.{cols_b['FDBH']}")

        if with_fdmc:
            sql = (f"SELECT t0.{cols_a['FDBH']} AS 门店编码, t0.{fdmc} AS 门店, "
                   f"{alias_list('t0', 't1')}\nFROM {join}\n"
                   f"GROUP BY t0.{cols_a['FDBH']}, t0.{fdmc}")
            order_by, metric_pos = "3", "3"
        elif intent.dimension in ("day", "month"):
            g = f"t0.{rq_a}" if intent.dimension == "day" else f"SUBSTR(t0.{rq_a}, 1, 7)"
            gcol = "日期" if intent.dimension == "day" else "月份"
            sql = f"SELECT {g} AS {gcol}, {alias_list('t0', 't1')}\nFROM {join}\nGROUP BY {g}"
            order_by, metric_pos = "1", "2"
        else:
            sql = f"SELECT {alias_list('t0', 't1')}\nFROM {join}"
            metric_pos = "1"
    else:
        # ── 单表 ──
        src = intent.metrics[0].src
        if src == "b":
            table, rq, where = names["b"], cols_b["RQ"], _date_where(intent.time, cols_b["RQ"])
        else:
            table, rq, where = names["a"], rq_a, where_a

        def _plain(met: MetricDef) -> str:
            return met.expr.replace("{T0}.", "").replace("{T1}.", "")

        cols = ", ".join(f"{_plain(m)} AS {m.name}" for m in intent.metrics)

        if intent.dimension == "store" and src == "a" and cols_a.get("FDMC"):
            sql = (f"SELECT {cols_a['FDBH']} AS 门店编码, {cols_a['FDMC']} AS 门店, {cols}\n"
                   f"FROM {table}\nWHERE {where}\n"
                   f"GROUP BY {cols_a['FDBH']}, {cols_a['FDMC']}")
            order_by, metric_pos = "3", "3"
        elif intent.dimension in ("day", "month"):
            g = rq if intent.dimension == "day" else f"SUBSTR({rq}, 1, 7)"
            gcol = "日期" if intent.dimension == "day" else "月份"
            sql = f"SELECT {g} AS {gcol}, {cols}\nFROM {table}\nWHERE {where}\nGROUP BY {g}"
            order_by, metric_pos = "1", "2"
        else:
            sql = f"SELECT {cols}\nFROM {table}\nWHERE {where}"
            metric_pos = "1"

    # 排序 / 限制：显式排名（最高/前N）按指标列排；否则维度默认序（门店=降序，日/月=时间升序）
    if intent.order and metric_pos:
        direction = "DESC" if intent.order == "desc" else "ASC"
        sql += f"\nORDER BY {metric_pos} {direction}"
    elif order_by:
        default_dir = "DESC" if intent.dimension == "store" else "ASC"
        sql += f"\nORDER BY {order_by} {default_dir}"
    if intent.limit:
        sql += f"\nLIMIT {intent.limit}"
    elif intent.dimension == "store":
        sql += f"\nLIMIT 50"

    explanation = (
        f"指标层确定性生成：{expl_metric}；"
        f"时间 {time_cn}（{origin_cn}）；{dim_cn}"
        + (f"；排序{intent.order}取前 {intent.limit} 名" if intent.order and intent.limit else "")
    )
    return sql, explanation


# ─────────────────────────── 路由入口 ───────────────────────────

async def _latest_rq(source: Any, table: str, rq_col: str) -> str | None:
    from app.core.data_ask.connectors.factory import build_connector_from_source

    try:
        conn = build_connector_from_source(source)
        try:
            qr = await conn.execute_select(f"SELECT MAX({rq_col}) FROM {table}", limit=1)
        finally:
            await conn.close()
        if qr.rows and qr.rows[0][0] is not None:
            return str(qr.rows[0][0])[:10]
    except Exception:
        return None
    return None


async def try_metric_route(
    source: Any,
    question: str,
    all_tables: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """指标层路由入口。命中返回路由信息 dict，未命中返回 None（交还 LLM）。"""
    cols_a, cols_b, names = detect_retail_tables(all_tables)
    if not cols_a and not cols_b:
        return None

    text = str(question or "")
    hint: str | None = None
    m = _RE_LATEST_HINT.search(text)
    if m:
        hint = m.group(1)
    else:
        m = _RE_ANNOTATION.search(text)
        if m:
            hint = m.group(2) or m.group(1)

    intent = parse_metric_intent(
        text, hint, has_a=bool(cols_a), has_b=bool(cols_b),
    )
    if intent is None:
        return None

    # 无显式时间 → 默认最新营业日（查库一次，轻量）
    if intent.time is None:
        if hint is None:
            if cols_a:
                hint = await _latest_rq(source, names["a"], cols_a["RQ"])
            if not hint and cols_b:
                hint = await _latest_rq(source, names["b"], cols_b["RQ"])
            if not hint:
                return None
        intent.time = TimeRange(hint, hint, "default_latest")

    sql, explanation = build_metric_sql(intent, cols_a, cols_b, names)
    if not sql:
        return None
    return {
        "sql": sql,
        "explanation": explanation,
        "route": "metric",
        "confidence": "high",
        "metric_keys": [m.key for m in intent.metrics],
        "metric_names": [m.name for m in intent.metrics],
        "dimension": intent.dimension,
        "time": {"start": intent.time.start, "end": intent.time.end,
                 "origin": intent.time.origin},
        "matched_text": intent.matched_text,
    }
