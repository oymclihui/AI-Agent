"""明细级 JOIN 扇出检测（确定性规则，不依赖 LLM）。

背景：日报表 SR_CS_SPJXCPCRBB 一个 (RQ,FDBH) 有上千行商品/批次明细，
客流表 SR_CS_KL 一个 (RQ,FDBH) 只有一行。两张表在同一 SELECT 层直接 JOIN
会把客流、客单价等指标放大几千倍（线上实测 47,824,743 vs 正确 3,039）。
另一种同样的放大：两个子查询都没聚合，再用 CROSS JOIN 把明细行乘上客流行。
2026-11-04 西安广场：真实客流 2,882，被 15,942 行明细乘成 45,944,844。
语义层提示只能"建议"模型别这么写，因此这里做硬校验，并在能确定口径时
把两边的度量列先 SUM 再关联。
"""

from __future__ import annotations

import re

DETAIL_TABLE = "SR_CS_SPJXCPCRBB"
FLOW_TABLE = "SR_CS_KL"
_TABLES = (DETAIL_TABLE, FLOW_TABLE)

# 子查询里可以安全地直接 SUM 的度量。出现维度列时不改写，交给模型重写。
_MEASURES = {
    "XSJE", "ML", "XSCB", "XSSL", "JHJE", "JHSL", "JYBS", "YYE",
    "ZKJE", "XSJE_HS", "ML_HS",
}

FANOUT_HINT = (
    "SQL 扇出错误：SR_CS_SPJXCPCRBB（日报，一个 RQ+FDBH 有上千行明细）与 "
    "SR_CS_KL（客流，一个 RQ+FDBH 只有一行）不能在同一层直接 JOIN，"
    "也不能把未聚合的明细子查询 CROSS JOIN 后再在外层 SUM。"
    "必须先用子查询各自聚合（销售: SUM(XSJE/XSCB/ML/XSSL)，客流: SUM(JYBS)、SUM(YYE)），"
    "再关联两个已经聚合的子查询。请按此范式重写，不要改变指标口径。"
)

_TABLE_RE = re.compile(
    r"\b(?:FROM|JOIN|,)\s*(" + DETAIL_TABLE + "|" + FLOW_TABLE + r")\b",
    re.IGNORECASE,
)
_AGG_RE = re.compile(r"\b(?:SUM|COUNT|AVG|MIN|MAX)\s*\(", re.IGNORECASE)
_BARE_MEASURE_RE = re.compile(
    r"^(?:[A-Za-z_][\w]*\.)?([A-Za-z_][\w]*)(?:\s+AS\s+(\S+))?$",
    re.IGNORECASE,
)


def _strip_noise(sql: str) -> str:
    """去掉字符串字面量与注释，避免把字面量里的表名误判为表引用。"""
    out = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"', "`"):
            quote = ch
            out.append(" ")
            i += 1
            while i < n:
                if sql[i] == quote:
                    if quote in ("'", '"') and i + 1 < n and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _mask_keep_len(sql: str) -> str:
    """字符串和注释换成等长空格，括号位置与原文对齐。"""
    chars = list(sql)
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"', "`"):
            quote = ch
            chars[i] = " "
            i += 1
            while i < n:
                if sql[i] == quote:
                    if quote in ("'", '"') and i + 1 < n and sql[i + 1] == quote:
                        chars[i] = " "
                        chars[i + 1] = " "
                        i += 2
                        continue
                    chars[i] = " "
                    i += 1
                    break
                chars[i] = " "
                i += 1
            continue
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                chars[i] = " "
                i += 1
            continue
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            chars[i] = " "
            chars[i + 1] = " "
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                chars[i] = " "
                i += 1
            if i < n:
                chars[i] = " "
            if i + 1 < n:
                chars[i + 1] = " "
            i += 2
            continue
        i += 1
    return "".join(chars)


def _table_layers(sql: str) -> dict[str, set[int]]:
    """返回每张表所在的 SELECT 层标记。同一层出现两张表即为直连。"""
    clean = _strip_noise(sql)
    layers: dict[str, set[int]] = {}
    stack: list[int] = []
    next_id = 0
    last = 0
    for m in _TABLE_RE.finditer(clean):
        seg = clean[last : m.start()]
        for ch in seg:
            if ch == "(":
                next_id += 1
                stack.append(next_id)
            elif ch == ")" and stack:
                stack.pop()
        last = m.start()
        layer = stack[-1] if stack else 0
        layers.setdefault(m.group(1).upper(), set()).add(layer)
    return layers


def _matching_close(masked: str, open_paren: int) -> int:
    """open_paren 是 '(' 的下标，返回配对 ')' 的下标。"""
    depth = 0
    for i in range(open_paren, len(masked)):
        ch = masked[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _subquery_bodies(sql: str) -> dict[str, list[tuple[int, int]]]:
    """每张表所在的最内层子查询正文区间 [start, end)，不含外层括号。

    表出现在顶层时区间为整段 SQL。
    """
    masked = _mask_keep_len(sql)
    bodies: dict[str, list[tuple[int, int]]] = {name: [] for name in _TABLES}
    stack: list[int] = []
    last = 0
    for m in _TABLE_RE.finditer(masked):
        seg = masked[last : m.start()]
        for offset, ch in enumerate(seg):
            idx = last + offset
            if ch == "(":
                stack.append(idx)
            elif ch == ")" and stack:
                stack.pop()
        last = m.start()
        table = m.group(1).upper()
        if stack:
            close = _matching_close(masked, stack[-1])
            if close < 0:
                continue
            span = (stack[-1] + 1, close)
        else:
            span = (0, len(sql))
        if span not in bodies[table]:
            bodies[table].append(span)
    return bodies


def _blank_nested(body: str) -> str:
    chars = list(body)
    depth = 0
    for i, ch in enumerate(body):
        if ch == "(":
            depth += 1
        if depth >= 1:
            chars[i] = " "
        if ch == ")":
            depth = max(0, depth - 1)
    return "".join(chars)


def _split_commas(text: str) -> list[str]:
    items: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            items.append(text[start:i])
            start = i + 1
    items.append(text[start:])
    return [item.strip() for item in items if item.strip()]


def _select_span(body: str) -> tuple[int, int] | None:
    blank = _blank_nested(body)
    match = re.search(r"\bSELECT\b(.*?)\bFROM\b", blank, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return match.start(1), match.end(1)


def _subquery_is_aggregated(body: str) -> bool:
    """这一层已经 GROUP BY，或选择列表全是聚合表达式。"""
    blank = _blank_nested(body)
    if re.search(r"\bGROUP\s+BY\b", blank, flags=re.IGNORECASE):
        return True
    span = _select_span(body)
    if span is None:
        return False
    items = _split_commas(body[span[0] : span[1]])
    if not items:
        return False
    return all(_AGG_RE.search(item) for item in items)


def _rewrite_select(body: str) -> str | None:
    """未聚合且选择列表全是度量列时，改成 SUM(列) AS 列。含维度列则不改。"""
    if _subquery_is_aggregated(body):
        return None
    span = _select_span(body)
    if span is None:
        return None
    items = _split_commas(body[span[0] : span[1]])
    if not items:
        return None
    rewritten: list[str] = []
    for item in items:
        if _AGG_RE.search(item):
            return None
        match = _BARE_MEASURE_RE.match(item.strip())
        if not match or match.group(1).upper() not in _MEASURES:
            return None
        expr = item.strip()
        alias = match.group(1)
        if match.group(2):
            expr = re.sub(r"\s+AS\s+\S+\s*$", "", item.strip(), flags=re.IGNORECASE)
            alias = match.group(2)
        rewritten.append(f"SUM({expr}) AS {alias}")
    new_list = " " + ", ".join(rewritten) + " "
    return body[: span[0]] + new_list + body[span[1] :]


def detect_fanout(sql: str) -> bool:
    """销售明细和客流没有先各自聚合就关联。"""
    if not sql:
        return False
    layers = _table_layers(sql)
    detail = layers.get(DETAIL_TABLE)
    flow = layers.get(FLOW_TABLE)
    if not detail or not flow:
        return False
    if detail & flow:
        return True
    bodies = _subquery_bodies(sql)
    for name in _TABLES:
        for start, end in bodies[name]:
            if not _subquery_is_aggregated(sql[start:end]):
                return True
    return False


def rewrite_fanout(sql: str) -> str | None:
    """把未聚合的度量子查询改成 SUM。改不干净时返回 None，交给模型重写。"""
    if not sql or not detect_fanout(sql):
        return None
    bodies = _subquery_bodies(sql)
    spans = []
    for name in _TABLES:
        for start, end in bodies[name]:
            if (start, end) not in spans:
                spans.append((start, end))
    spans.sort(reverse=True)
    updated = sql
    changed = False
    for start, end in spans:
        body = updated[start:end]
        if _subquery_is_aggregated(body):
            continue
        rewritten = _rewrite_select(body)
        if rewritten is None:
            return None
        updated = updated[:start] + rewritten + updated[end:]
        changed = True
    if not changed or detect_fanout(updated):
        return None
    return updated
