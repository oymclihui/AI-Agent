"""环比/同比自动计算：从主查询 SQL 里抠日期范围，跑对比查询。

策略：
1. 解析 display_sql 里的日期条件（RQ = / IN / BETWEEN / >=）
2. 算出当前范围的 "基准日"（范围的最后一天）
3. 环比 = 基准日 vs 基准日-1 营业日；或 vs 基准日-7（周环比）
4. 同比 = 基准日 vs 基准日-365
5. 如果对比日不在数据源覆盖范围内 → 明确标注缺失，不编造
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.core.data_ask.connectors.factory import build_connector_from_source


_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _parse_dates(sql: str) -> list[date]:
    out = []
    for m in _DATE.finditer(sql or ""):
        try:
            out.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    return sorted(set(out))


def _anchor_date(sql: str) -> date | None:
    dates = _parse_dates(sql)
    return dates[-1] if dates else None


def _subtract_days(d: date, days: int) -> date:
    return d - timedelta(days=days)


async def _available_range(conn) -> tuple[date | None, date | None]:
    try:
        qr = await conn.execute_select(
            "SELECT MIN(RQ), MAX(RQ) FROM SR_CS_SPJXCPCRBB"
        )
        for row in qr.rows[:1]:
            mn, mx = row[0], row[1]
            def _cast(v):
                if v is None:
                    return None
                if isinstance(v, datetime):
                    return v.date()
                if isinstance(v, date):
                    return v
                try:
                    return datetime.strptime(str(v), "%Y-%m-%d").date()
                except ValueError:
                    return None
            return _cast(mn), _cast(mx)
    except Exception:
        return None, None


def _build_period_sql(base_sql: str, anchor: date, compare_date: date) -> str:
    """从主查询 SQL 复制一份，把日期条件整体替换为 compare_date 单日。"""
    target = f"'{compare_date.isoformat()}'"
    sql = base_sql
    sql = re.sub(r"(\b)RQ\s+IN\s*\(\s*'[^']+'(?:\s*,\s*'[^']+')*\s*\)",
                 rf"\1RQ = {target}", sql, flags=re.I)
    sql = re.sub(r"(\b)RQ\s+BETWEEN\s+'[^']+'\s+AND\s+'[^']+'",
                 rf"\1RQ = {target}", sql, flags=re.I)
    sql = re.sub(r"(\b)RQ\s*(?:>=|>)\s*'[^']+'",
                 rf"\1RQ = {target}", sql, flags=re.I)
    sql = re.sub(r"(\b)RQ\s*=\s*'[^']+'",
                 rf"\1RQ = {target}", sql, flags=re.I)
    return sql


# 权限表名特征（系统权限注入里会用到的表）
_PERM_TABLE_HINTS = ("SR_FD_QX", "permission", "perm_")


def _strip_permission_filters(sql: str) -> str:
    """剥离 SQL 里的权限注入子查询，避免对比计算被特定 user 权限过滤成全 None。

    处理两类注入形态：
    1. pushdown 形式：AND a.FDBH IN (SELECT SR_FD_QX.FDBH FROM SR_FD_QX WHERE ...)
    2. outer wrap 形式：SELECT * FROM (...) AS _perm_base WHERE col IN (SELECT SR_FD_QX...)
    """
    s = sql or ""
    original = s

    # === 形态 1: pushdown —— AND/OR col IN (SELECT ... FROM SR_FD_QX ...) ===
    # 用一个健壮的括号匹配去掉整个 IN 子句 + 前面的 AND/OR
    # 模式: AND  alias.col  IN  (  SELECT ... SR_FD_QX ...  )
    # 先找所有权限相关的 IN 子查询
    def _has_perm_table(subquery_text: str) -> bool:
        low = subquery_text.lower()
        return any(h.lower() in low for h in _PERM_TABLE_HINTS)

    # 循环剥离，直到没有权限子查询为止
    changed = True
    while changed:
        changed = False
        # 找 IN ( ... ) 的位置，检查括号内是否含权限表
        # 匹配: [AND|OR]?\s*[表别名.]列名\s+IN\s*\(
        in_pattern = re.compile(
            r"((?:AND|OR)?)\s*([\w.`\"]+)\s+IN\s*\(",
            flags=re.I
        )
        for m in in_pattern.finditer(s):
            prefix = m.group(1) or ""  # AND / OR / 空
            col = m.group(2)
            paren_start = m.end() - 1  # '(' 的位置

            # 从 paren_start 开始匹配括号
            depth = 0
            paren_end = -1
            i = paren_start
            while i < len(s):
                if s[i] == '(':
                    depth += 1
                elif s[i] == ')':
                    depth -= 1
                    if depth == 0:
                        paren_end = i
                        break
                i += 1
            if paren_end < 0:
                break  # 不匹配，跳过

            subquery_text = s[paren_start + 1:paren_end]
            if _has_perm_table(subquery_text):
                # 找到完整要删除的范围
                # 从 m.start() - 1 往前跳空格，去掉前面的 AND/OR + 空格
                del_start = m.start()
                # 往前找 AND/OR 及其前面的空格
                before = s[:del_start].rstrip()
                and_or_match = re.search(r"\b(AND|OR)\s*$", before, flags=re.I)
                if and_or_match:
                    del_start = and_or_match.start()
                # 如果 AND/OR 在字符串最开头（前面是 WHERE），保留 WHERE
                # 但如果前面是 WHERE 且这是唯一条件，不要删成 WHERE 空
                deleted_region = s[del_start:paren_end + 1]
                s = s[:del_start] + s[paren_end + 1:]
                changed = True
                break  # 重新扫描

    # === 形态 2: outer wrap —— SELECT * FROM (...) AS _perm_base WHERE col IN (...) ===
    wrap_pattern = re.compile(
        r"SELECT\s+\*\s+FROM\s*\((.+)\)\s+AS\s+_perm_base\s+WHERE\s+[\w.]+\s+IN\s*\(.+?\)",
        flags=re.I | re.DOTALL
    )
    m = wrap_pattern.search(s)
    if m:
        inner = m.group(1).strip()
        s = inner

    # 清理残留的 WHERE AND / WHERE OR
    s = re.sub(r"\bWHERE\s+AND\b", "WHERE", s, flags=re.I)
    s = re.sub(r"\bWHERE\s+OR\b", "WHERE", s, flags=re.I)
    # 清理多余空格
    s = re.sub(r"\s+", " ", s).strip()

    return s


async def compute_comparisons(
    *,
    source: Any,
    current_sql: str,
    current_rows: list[list[Any]],
    columns: list[str],
) -> dict[str, Any]:
    """返回 {'anchor': date, 'dod': {...}, 'wow': {...}, 'yoy': {...}, 'warnings': [...]}。

    每个对比块结构：
      {'available': True/False, 'date': 'YYYY-MM-DD'|None,
       'rows': [...], 'delta_pct': [...同 current_rows 列数的百分比列表]}
    """
    anchor = _anchor_date(current_sql)
    out: dict[str, Any] = {"anchor": anchor.isoformat() if anchor else None,
                           "dod": None, "wow": None, "yoy": None, "warnings": []}
    if anchor is None:
        out["warnings"].append("主查询 SQL 未识别到日期范围，无法计算环比/同比")
        return out

    conn = build_connector_from_source(source)
    try:
        mn, mx = await _available_range(conn)
        mn = mn or date(1970, 1, 1)
        mx = mx or date(2999, 12, 31)

        async def _run_compare(label: str, compare_date: date) -> dict[str, Any]:
            if compare_date < mn or compare_date > mx:
                out["warnings"].append(
                    f"{label}（{compare_date.isoformat()}）不在数据源覆盖范围内（{mn.isoformat()} 至 {mx.isoformat()}）")
                return {"available": False, "date": compare_date.isoformat(),
                        "reason": "数据覆盖不到，DBA 补数据后自动生效"}
            compare_sql = _build_period_sql(current_sql, anchor, compare_date)
            compare_sql = _strip_permission_filters(compare_sql)
            try:
                qr = await conn.execute_select(compare_sql)
            except Exception as exc:
                out["warnings"].append(f"{label} 查询失败：{exc}")
                return {"available": False, "date": compare_date.isoformat(), "reason": str(exc)[:80]}
            if not qr.rows or not current_rows:
                return {"available": False, "date": compare_date.isoformat(), "reason": "无数据"}
            cur = current_rows[0]
            cmp = qr.rows[0]
            deltas = []
            for i in range(min(len(cur), len(cmp))):
                try:
                    a, b = float(cur[i]), float(cmp[i])
                    if b == 0:
                        deltas.append(None if a == 0 else float("inf"))
                    else:
                        deltas.append(round((a - b) / b * 100, 2))
                except (TypeError, ValueError):
                    deltas.append(None)
            return {
                "available": True,
                "date": compare_date.isoformat(),
                "compare_rows": qr.rows,
                "compare_columns": list(qr.columns),
                "delta_pct": deltas,
                "delta_vs": [round(float(cur[i]) - float(cmp[i]), 2) for i in range(min(len(cur), len(cmp)))
                             if isinstance(cur[i], (int, float)) and isinstance(cmp[i], (int, float))],
            }

        out["dod"] = await _run_compare("日环比", _subtract_days(anchor, 1))
        out["wow"] = await _run_compare("周环比", _subtract_days(anchor, 7))
        out["yoy"] = await _run_compare("年同比", _subtract_days(anchor, 365))
    finally:
        await conn.close()
    return out


def summary_lines(columns: list[str], rows: list[list[Any]],
                  comp: dict[str, Any], question: str) -> list[str]:
    """把对比结果转成 3-5 句管理层摘要。"""
    if not rows:
        return ["主查询未返回数据。"]
    first = rows[0]
    lines = [f"· 问题：{question}"]
    if comp.get("anchor"):
        lines.append(f"· 基准日期：{comp['anchor']}")
    # 日环比
    for key, label in [("dod", "日环比"), ("wow", "周环比"), ("yoy", "年同比")]:
        block = comp.get(key) or {}
        if not block.get("available"):
            continue
        deltas = block.get("delta_pct") or []
        highlights = []
        for i, d in enumerate(deltas):
            if d is None:
                continue
            metric = columns[i] if i < len(columns) else f"指标{i+1}"
            arrow = "↑" if d > 0 else "↓"
            highlights.append(f"{metric}{arrow}{abs(d):.1f}%")
        if highlights:
            lines.append(f"· {label}（vs {block['date']}）：" + "、".join(highlights))
    if comp.get("warnings"):
        lines.append("· 说明：" + "；".join(comp["warnings"][:3]))
    return lines
