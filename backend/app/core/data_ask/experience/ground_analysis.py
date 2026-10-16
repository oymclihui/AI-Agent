"""Keep analysis prose tied to numbers that already appear in the result."""
from __future__ import annotations

import re
from typing import Any

# 数字（含可选负号）：必须在 result_numbers 与 _line_ok 里用同一套，
# 否则「负号算不算」不一致会让负值行被误删。
# 负号前不能紧跟字母/数字，避免把商品名里的「115g-135g」拆出一个假的 -135。
_NUMBER = re.compile(r"(?<![0-9A-Za-z])-?\d+(?:\.\d+)?")
_LIST_MARK = re.compile(r"^\s*\d+[\.、\)]\s*")
# 千分位逗号：模型常把 142801.11 写成 142,801.11，
# 若不去除会被拆成 142 与 801.11 两个「未授权数字」而整行被丢弃。
_THOUSANDS = re.compile(r"(?<=\d),(?=\d)")
# 日期/时间/序号等非数据声明：句子里复述「10月10日」「2026年」属上下文，
# 不应被当成「未授权的数据数字」而把整行删掉。
_DATE_TIME = re.compile(
    r"\d{4}\s*年"
    r"|\d{4}\s*[-/]\s*\d{1,2}(?:\s*[-/]\s*\d{1,2})?"
    r"|\d{1,2}\s*[月日号]"
    r"|\d{1,2}\s*[:：]\s*\d{1,2}"
    r"|第\s*\d+|Q[1-4]"
)
# 只有加粗文字 / ATX 标题的整行，视为小标题。
_BOLD_ONLY = re.compile(r"^\s*\*\*[^*]+\*\*\s*[:：]?\s*$")
_ATX = re.compile(r"^\s*#{1,6}\s+\S")
# 常见小节名（「建议：」这类纯文字标题）也要能被识别，
# 否则模型漏写内容时会留下一个光秃秃的「建议：」。
_SECTION = re.compile(
    r"^\s*\**\s*(建议|核心结论|数据概览|深入分析|结论|要点|总结|分析|概览|洞察|发现|风险|行动)\s*[:：]?\s*\**\s*$"
)
# Markdown 表格分隔行，如 |---|---|
_TABLE_SEP = re.compile(r"^\s*\|[\s:\-|]+\|\s*$")
# 小数尾随零：DECIMAL 列（如毛利 -127.87）会被原样抄成 -127.870000000，
# 这里只去掉尾随零、不改变数值大小（不做四舍五入）。
# 只处理 3 位以上的小数，避免把金额 491780.90 变成 491780.9。
_DECIMAL = re.compile(r"(?<![\d.])(\d+\.\d{3,})(?![\d.])")
# 护栏把内容全部清空时的占位符；调用方据此改用「由结果表直接生成」的兜底文案。
EMPTY_FALLBACK = "请直接查看表格中的数值。"


def _unseparate(text: str) -> str:
    """去掉数字中的千分位逗号。"""
    return _THOUSANDS.sub("", text)


def result_numbers(rows: list[list[Any]] | None) -> set[str]:
    found: set[str] = set()
    for row in rows or []:
        for cell in row:
            if isinstance(cell, bool) or cell is None:
                continue
            if isinstance(cell, (int, float)):
                found.add(_canon(cell))
            # 同时按文本扫描：保证与 _clause_ok 用同一套正则、正负号一致。
            for match in _NUMBER.findall(_unseparate(str(cell))):
                found.add(_canon(match))
    return found


def format_allowed_numbers(rows: list[list[Any]] | None) -> str:
    nums = sorted(result_numbers(rows), key=lambda item: (len(item), item))
    if not nums:
        return "可用数字: （结果中没有数值，不要写任何具体数字）\n"
    return "可用数字: " + "、".join(nums) + "\n"


def ground_analysis(text: str, rows: list[list[Any]] | None) -> str:
    allowed = result_numbers(rows)
    lines = [_clean_line(line, allowed) for line in (text or "").splitlines()]
    lines = _normalize_tables(lines)
    lines = _drop_orphan_headings(lines)
    cleaned = tidy_numbers("\n".join(lines).strip())
    if cleaned:
        return cleaned
    return EMPTY_FALLBACK


def tidy_numbers(text: str) -> str:
    """去掉数值里多余的尾随零（-127.870000000 → -127.87），数值本身不变。

    只处理 3 位以上的小数；金额（2 位小数）原样保留。
    """
    def _trim(match: re.Match[str]) -> str:
        head, _, frac = match.group(1).partition(".")
        frac = frac.rstrip("0")
        if not frac:
            return head
        if len(frac) == 1:
            frac += "0"
        return f"{head}.{frac}"

    return _DECIMAL.sub(_trim, text or "")


def _clean_line(line: str, allowed: set[str]) -> str:
    """守住「不出现未授权数字」：含违规数字的行整行丢弃。

    只丢整行、不做半句截断——截断容易留下「…虽排名第五」这种残句，
    可读性更差；被丢空的标题由 _drop_orphan_headings 一并清理。
    """
    return line if _line_ok(line, allowed) else ""


def _line_ok(line: str, allowed: set[str]) -> bool:
    body = _DATE_TIME.sub("", _LIST_MARK.sub("", line))
    for match in _NUMBER.findall(_unseparate(body)):
        if _canon(match) not in allowed:
            return False
    return True


def _is_heading(line: str) -> bool:
    return bool(_BOLD_ONLY.match(line) or _ATX.match(line) or _SECTION.match(line))


def _drop_orphan_headings(lines: list[str]) -> list[str]:
    """小标题后面没有任何正文时丢弃该标题，避免出现空标题。"""
    out: list[str] = []
    total = len(lines)
    for idx, line in enumerate(lines):
        if _is_heading(line):
            nxt = idx + 1
            while nxt < total and not lines[nxt].strip():
                nxt += 1
            if nxt >= total or _is_heading(lines[nxt]):
                continue
        out.append(line)
    return out


def _normalize_tables(lines: list[str]) -> list[str]:
    """修正表格结构：丢掉没有表头的分隔行，以及只有表头没有数据行的空表。"""
    out: list[str] = []
    idx = 0
    total = len(lines)
    while idx < total:
        line = lines[idx]
        if _TABLE_SEP.match(line):
            prev = next((item for item in reversed(out) if item.strip()), "")
            if not prev.strip().startswith("|"):
                idx += 1          # 没有表头的分隔行在 markdown 里没有意义
                continue
            nxt = idx + 1
            while nxt < total and not lines[nxt].strip():
                nxt += 1
            if nxt >= total or not lines[nxt].strip().startswith("|"):
                out.pop()         # 只有表头、没有数据行的空表
                idx += 1
                continue
        out.append(line)
        idx += 1
    return out


def _canon(value: Any) -> str:
    number = float(value)
    if number.is_integer() and abs(number) < 1e12:
        return str(int(number))
    text = format(number, "f").rstrip("0").rstrip(".")
    return text
