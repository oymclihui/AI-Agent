"""用 matplotlib 把二维数据渲染成规整的 PNG 表格（企微 markdown 不支持表格，只能走图片）。"""
from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

_MUTED = "#667085"
_OUT_DIR = Path("/tmp/wecom_charts")
_FONT_READY = False
_LAST_SWEEP = 0.0


def _sweep(max_age: int = 7200) -> None:
    """每小时最多清理一次，删除 2 小时前的临时 PNG，避免 /tmp 无限增长。"""
    global _LAST_SWEEP
    now = time.time()
    if now - _LAST_SWEEP < 3600:
        return
    _LAST_SWEEP = now
    try:
        for item in _OUT_DIR.glob("*.png"):
            if now - item.stat().st_mtime > max_age:
                item.unlink(missing_ok=True)
    except Exception:
        pass


# 可配置主题：表头底色 / 表头文字 / 斑马纹 / 边框 / 正文
_THEMES: dict[str, dict[str, str]] = {
    "blue": {"header": "#1e40af", "header_text": "#ffffff", "zebra": "#f8fafc", "border": "#e4e7ec", "ink": "#14181f"},
    "green": {"header": "#0f766e", "header_text": "#ffffff", "zebra": "#f0fdfa", "border": "#d7e5e3", "ink": "#14211f"},
    "purple": {"header": "#6d28d9", "header_text": "#ffffff", "zebra": "#faf5ff", "border": "#e6dcf7", "ink": "#1b1428"},
    "orange": {"header": "#c2410c", "header_text": "#ffffff", "zebra": "#fff7ed", "border": "#f3e0d3", "ink": "#1f1510"},
    "dark": {"header": "#1f2937", "header_text": "#ffffff", "zebra": "#f3f5f9", "border": "#dfe3ea", "ink": "#111827"},
}
_SIZES = {"small": 10.0, "medium": 11.0, "large": 12.5}


def _apply_font(font_path: Path | None) -> None:
    global _FONT_READY
    if _FONT_READY or not font_path or not font_path.is_file():
        return
    from matplotlib import font_manager

    font_manager.fontManager.addfont(str(font_path))
    # 族名必须用字体内部名（Droid Sans Fallback），不能用文件名
    family = font_manager.FontProperties(fname=str(font_path)).get_name()
    matplotlib.rcParams["font.family"] = ["DejaVu Sans", family]
    matplotlib.rcParams["axes.unicode_minus"] = False
    _FONT_READY = True


def _fmt(value: Any, thousands: bool = True) -> str:
    v = str(value).strip()
    if "," in v:
        return v
    if re.fullmatch(r"-?\d+(?:\.\d+)?", v):
        whole, _, dec = v.partition(".")
        sign = "-" if whole.startswith("-") else ""
        whole = whole.lstrip("-") or "0"
        grouped = f"{int(whole):,}" if thousands else whole
        return f"{sign}{grouped}.{dec}" if dec else f"{sign}{grouped}"
    return v


def _num_like(text: str) -> bool:
    return bool(re.fullmatch(r"-?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|-?\d+(?:\.\d+)?%?", text.strip()))


def _text_in(text: str, fs: float) -> float:
    """按字号估算字符串渲染宽度（英寸）：CJK ≈ 1em，ASCII ≈ 0.62em。"""
    return sum((fs / 72) if ord(c) > 127 else (fs / 72 * 0.62) for c in text) * 1.06


def render_table(
    header: list[str],
    rows: list[list[Any]],
    *,
    title: str = "",
    footnote: str = "",
    max_rows: int = 50,
    font_path: Path | None = None,
    style: dict[str, Any] | None = None,
) -> str | None:
    """把 header+rows 画成一张规整的 PNG。style 支持主题/字号/斑马纹/标题开关。"""
    if not header or not rows:
        return None
    opts = style if isinstance(style, dict) else {}
    theme = _THEMES.get(str(opts.get("theme") or "blue")) or _THEMES["blue"]
    fs = _SIZES.get(str(opts.get("font_size") or "medium"), 11.0)
    zebra_on = bool(opts.get("zebra", True))
    show_title = bool(opts.get("show_title", True)) and bool(title)
    thousands = bool(opts.get("show_thousands", True))
    hint_tpl = str(opts.get("truncate_hint") or "仅显示前 {n} 行")
    try:
        dpi = max(100, min(int(opts.get("table_dpi") or 200), 400))
    except (TypeError, ValueError):
        dpi = 200
    try:
        max_w = max(4.0, min(float(opts.get("table_max_width") or 10.0), 20.0))
    except (TypeError, ValueError):
        max_w = 10.0

    ncol = len(header)
    norm = []
    for row in rows:
        cells = ["" if v is None else str(v) for v in row]
        norm.append((cells + [""] * ncol)[:ncol])
    if not norm:
        return None
    total_rows = len(norm)
    # max_rows=0 表示不截断（渲染全部行）；物理上限 1000 行，避免图片过大导致企微上传失败
    hard_cap = 1000
    limit = hard_cap if max_rows <= 0 else min(max_rows, hard_cap)
    truncated = total_rows > limit
    rows = norm[:limit]

    if font_path is None:
        # 兼容多种部署结构：向上找 4 层，取第一个存在的字体文件
        font_path = Path(__file__).resolve()
        for _ in range(4):
            font_path = font_path.parent
            candidate = font_path / "assets" / "fonts" / "DroidSansFallbackFull.ttf"
            if candidate.is_file():
                font_path = candidate
                break
        else:
            font_path = None  # 没找到，让 _apply_font 跳过
    _apply_font(font_path)
    plt.close("all")

    shown = [[_fmt(v, thousands) for v in row] for row in rows]

    # 列宽：内容最大宽度 + 左右内边距
    col_w: list[float] = []
    for i, h in enumerate(header):
        content = max((_text_in(r[i], fs) for r in shown), default=0.0)
        col_w.append(max(_text_in(str(h), fs), content) + 0.22)
    total_w = sum(col_w) + 0.08
    total_w = min(max(total_w, 2.8), max_w)

    head_h = fs / 72 * 2.0
    row_h = fs / 72 * 1.8
    title_h = 0.30 if show_title else 0.10
    foot_h = 0.32 if (footnote or truncated) else 0.10
    table_h = head_h + len(rows) * row_h
    total_h = title_h + table_h + foot_h

    fig = plt.figure(figsize=(total_w, total_h), dpi=dpi)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor("white")
    ax.axis("off")

    # bbox 让表格精确铺满预留区域，行高列宽全部可控，不会挤压重叠
    table = ax.table(
        cellText=shown,
        colLabels=[str(h) for h in header],
        cellLoc="center",
        colLoc="center",
        bbox=[0.0, foot_h / total_h, 1.0, table_h / total_h],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(fs)

    num_col = []
    for i in range(ncol):
        vals = [r[i] for r in shown if r[i].strip()]
        num_col.append(bool(vals) and all(_num_like(v) for v in vals))

    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor(theme["border"])
        cell.set_linewidth(0.7)
        if r == 0:
            cell.set_facecolor(theme["header"])
            cell.set_text_props(color=theme["header_text"])
        else:
            cell.set_facecolor(theme["zebra"] if (zebra_on and r % 2 == 0) else "white")
            cell.set_text_props(color=theme["ink"])
        cell.set_width(col_w[c] / total_w)
        cell.set_height((head_h if r == 0 else row_h) / table_h)
        text = cell.get_text()
        if c == 0:
            text.set_horizontalalignment("left")
            cell.PAD = 0.04
        elif num_col[c]:
            text.set_horizontalalignment("right")
            cell.PAD = 0.04

    if show_title:
        # 紧贴表格顶部，避免行数少时标题与表格之间出现大片空白
        fig.text(
            0.5, (foot_h + table_h) / total_h + 0.05 / total_h, title,
            fontsize=13.5, color=theme["ink"], ha="center", va="bottom",
        )
    if truncated and not footnote:
        footnote = hint_tpl.replace("{n}", str(limit))
    if footnote:
        fig.text(0.01, 0.012, footnote, fontsize=8.5, color=_MUTED, ha="left", va="bottom")

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    _sweep()
    path = _OUT_DIR / f"table_{uuid.uuid4().hex[:12]}.png"
    fig.savefig(path, format="png", bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    return str(path)
