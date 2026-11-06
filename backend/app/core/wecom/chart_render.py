"""把问数结果的图表数据渲染成 PNG，供企业微信图片消息使用。

图表类型按数据特征选择：时间序列用折线，占比构成用饼图，分类对比用柱状/条形，
量纲不一致或数据点不足时不出图（此类结果用文字更清楚）。
"""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import FuncFormatter

_FONT = Path(__file__).resolve()
for _ in range(4):
    _FONT = _FONT.parent
    candidate = _FONT / "assets" / "fonts" / "DroidSansFallbackFull.ttf"
    if candidate.is_file():
        _FONT = candidate
        break
else:
    _FONT = candidate  # 没找到也保持最后候选，让后续 .is_file() 来判
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


_INK = "#14181f"
_MUTED = "#667085"
_GRID = "#e4e7ec"

# 主色/辅色跟随表格主题，保证同一条消息里图表与表格配色一致
_THEME_COLORS: dict[str, tuple[str, str]] = {
    "blue": ("#2563eb", "#0e9f8e"),
    "green": ("#0f766e", "#0ea5a4"),
    "purple": ("#6d28d9", "#a855f7"),
    "orange": ("#c2410c", "#f59e0b"),
    "dark": ("#1f2937", "#4b5563"),
}

_KINDS = {"auto", "bar", "barh", "line", "area", "pie"}

_UNIT_RE = re.compile(r"[（(]([^）)]+)[）)]\s*$")
_TIME_RES = (
    re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$"),
    re.compile(r"^\d{4}年\d{1,2}月(\d{1,2}日)?$"),
    re.compile(r"^\d{1,2}月(\d{1,2}日)?$"),
    re.compile(r"^\d{1,2}[-/.]\d{1,2}$"),
    re.compile(r"^\d{1,2}:\d{2}$"),
    re.compile(r"^(周|星期)[一二三四五六日天]$"),
    re.compile(r"^\d{1,2}时$"),
)
_SHARE_WORDS = ("占比", "构成", "比例", "份额", "分布", "结构")
_RATE_WORDS = ("率", "占比", "比例", "百分点")


def _apply_font() -> None:
    global _FONT_READY
    if _FONT_READY or not _FONT.is_file():
        return
    font_manager.fontManager.addfont(str(_FONT))
    # 拉丁字符与数字用 DejaVu，中文回退到 Droid Sans Fallback
    matplotlib.rcParams["font.family"] = ["DejaVu Sans", "Droid Sans Fallback"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    _FONT_READY = True


def _fmt(value: float) -> str:
    text = f"{value:,.3f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _series(chart: dict[str, Any]) -> list[tuple[str, list[float | None]]]:
    items: list[tuple[str, list[float | None]]] = []
    for dataset in chart.get("datasets") or []:
        values: list[float | None] = []
        for raw in dataset.get("data") or []:
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                values.append(None)
        items.append((str(dataset.get("label") or ""), values))
    if not items and chart.get("values"):
        values = []
        for raw in chart["values"]:
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                values.append(None)
        items.append((str(chart.get("series") or ""), values))
    return items


def _units(labels: list[str]) -> set[str]:
    units: set[str] = set()
    for label in labels:
        match = _UNIT_RE.search(label)
        if match:
            units.add(match.group(1).strip())
    return units


def _is_time_axis(labels: list[str]) -> bool:
    if len(labels) < 3:
        return False
    hits = sum(1 for label in labels if any(pattern.match(label.strip()) for pattern in _TIME_RES))
    return hits >= max(3, int(len(labels) * 0.6))


def _mixed_metrics(labels: list[str]) -> bool:
    """标签里同时有比率类与金额/数量类指标时，画在同一坐标轴上会互相淹没。"""
    rate = [label for label in labels if any(word in label for word in _RATE_WORDS)]
    other = [label for label in labels if label not in rate]
    return bool(rate) and bool(other)


def _magnitude_gap(labels: list[str], numeric: list[float]) -> bool:
    """少量标签但数值相差千倍以上，多半是把不同量纲的指标并排画了。"""
    if len(labels) > 4:
        return False
    positive = [abs(value) for value in numeric if value]
    if len(positive) < 2:
        return False
    return max(positive) / min(positive) > 1000


def _choose_kind(labels: list[str], series: list[tuple[str, list[float | None]]], chart: dict[str, Any]) -> str | None:
    if len(labels) < 2:
        return None
    # 同一对象上的多个指标量纲不同（元、%、件），画在一起没有可比性
    units = _units(labels)
    if len(units) >= 2:
        return None
    numeric = [value for values in (values for _, values in series) for value in values if value is not None]
    if len(numeric) < 2 or not any(value != 0 for value in numeric):
        return None
    if _mixed_metrics(labels) or _magnitude_gap(labels, numeric):
        return None

    title = str(chart.get("title") or "")
    hint = str(chart.get("type") or "bar").lower()
    if _is_time_axis(labels):
        return "area" if hint == "area" else "line"
    if hint == "pie" or any(word in title for word in _SHARE_WORDS):
        return "pie"
    if len(labels) > 8 or max(len(label) for label in labels) > 8:
        return "barh"
    if len(series) > 1 and len(labels) > 12:
        return "line"
    return "bar"


def _thin_axis(ax, labels: list[str], *, horizontal: bool = False) -> None:
    """类别较多时只显示部分刻度，避免标签挤在一起。"""
    axis = ax.yaxis if horizontal else ax.xaxis
    if len(labels) > 10:
        step = max(1, len(labels) // 8)
        ticks = list(range(0, len(labels), step))
        axis.set_ticks(ticks)
        axis.set_ticklabels([labels[index] for index in ticks])
        plt.setp(axis.get_ticklabels(), rotation=30, ha="right")
    elif not horizontal and (len(labels) > 6 or max(len(label) for label in labels) > 5):
        plt.setp(axis.get_ticklabels(), rotation=20, ha="right")


def render_chart(chart: dict[str, Any] | None, *, style: dict[str, Any] | None = None) -> str | None:
    """返回 PNG 路径；数据不适合出图时返回 None。style 控制类型/尺寸/标签/图例/配色。"""
    if not isinstance(chart, dict):
        return None
    opts = style if isinstance(style, dict) else {}
    accent, accent2 = _THEME_COLORS.get(str(opts.get("theme") or "blue"), _THEME_COLORS["blue"])
    show_values = bool(opts.get("show_value_labels", True))
    show_legend = bool(opts.get("show_legend", True))
    try:
        width = max(4.0, min(float(opts.get("chart_width") or 7.6), 14.0))
        height = max(2.5, min(float(opts.get("chart_height") or 4.4), 10.0))
    except (TypeError, ValueError):
        width, height = 7.6, 4.4
    try:
        dpi = int(opts.get("chart_dpi") or 200)
    except (TypeError, ValueError):
        dpi = 200
    dpi = max(100, min(dpi, 400))
    try:
        max_labels = int(opts.get("chart_max_labels") or 0)
    except (TypeError, ValueError):
        max_labels = 0

    labels = [str(item) for item in (chart.get("labels") or [])]
    series = _series(chart)
    if not labels or not series:
        return None
    size = min(len(labels), *(len(values) for _, values in series))
    if size < 2:
        return None
    labels = labels[:size]
    series = [(name, values[:size]) for name, values in series]
    if max_labels > 1 and len(labels) > max_labels:
        labels = labels[:max_labels]
        series = [(name, values[:max_labels]) for name, values in series]

    kind = _choose_kind(labels, series, chart)
    if kind is None:
        return None
    forced = str(opts.get("chart_type") or "auto").lower()
    if forced in _KINDS and forced != "auto" and (forced != "pie" or len(series) == 1):
        kind = forced

    _apply_font()
    plt.close("all")
    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    try:
        if kind == "pie":
            pairs = [(label, abs(value or 0.0)) for label, value in zip(labels, series[0][1])]
            pairs.sort(key=lambda item: item[1], reverse=True)
            if len(pairs) > 8:
                rest = sum(value for _, value in pairs[7:])
                pairs = pairs[:7] + [("其他", rest)]
            pairs = [(label, value) for label, value in pairs if value > 0]
            if len(pairs) < 2:
                return None
            labels = [label for label, _ in pairs]
            values = [value for _, value in pairs]
            colors = plt.get_cmap("tab20")(range(len(values)))
            ax.pie(
                values,
                labels=labels,
                autopct=(lambda pct: f"{pct:.1f}%" if pct >= 3 else "") if show_values else None,
                colors=colors,
                textprops={"fontsize": 11, "color": _INK},
                wedgeprops={"linewidth": 0.6, "edgecolor": "white"},
            )
            ax.axis("equal")
        elif kind in {"line", "area"}:
            for index, (name, values) in enumerate(series):
                points = [value if value is not None else float("nan") for value in values]
                ax.plot(
                    labels,
                    points,
                    marker="o",
                    markersize=4,
                    linewidth=2,
                    color=accent if index % 2 == 0 else accent2,
                    label=name or None,
                )
                if kind == "area" and index == 0:
                    ax.fill_between(labels, points, color=accent, alpha=0.12)
            ax.grid(axis="y", color=_GRID, linewidth=0.8)
            ax.tick_params(colors=_MUTED, labelsize=11)
            ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
            _thin_axis(ax, labels)
        else:
            values = [value or 0.0 for value in series[0][1]]
            if kind == "barh":
                order = sorted(range(len(values)), key=lambda index: values[index])
                labels = [labels[index] for index in order]
                values = [values[index] for index in order]
                bars = ax.barh(labels, values, color=accent, height=0.62)
                if show_values:
                    ax.bar_label(bars, labels=[_fmt(value) for value in values], padding=4, fontsize=10, color=_INK)
                ax.grid(axis="x", color=_GRID, linewidth=0.8)
                ax.tick_params(colors=_MUTED, labelsize=11)
                ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
            else:
                bars = ax.bar(labels, values, color=accent, width=0.62)
                if show_values:
                    ax.bar_label(bars, labels=[_fmt(value) for value in values], padding=4, fontsize=10, color=_INK)
                ax.grid(axis="y", color=_GRID, linewidth=0.8)
                ax.tick_params(colors=_MUTED, labelsize=11)
                ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
                _thin_axis(ax, labels)

        title = str(chart.get("title") or "").strip()
        if title and opts.get("show_chart_title", False):
            ax.set_title(title, fontsize=14, color=_INK, pad=14)
        if kind != "pie":
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.spines["left"].set_color(_GRID)
            ax.spines["bottom"].set_color(_GRID)
            if show_legend and len(series) > 1 and kind not in {"line", "area"}:
                ax.legend(loc="best", frameon=False, fontsize=11)

        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        _sweep()
        path = _OUT_DIR / f"chart_{uuid.uuid4().hex[:12]}.png"
        fig.savefig(path, format="png", bbox_inches="tight", pad_inches=0.25)
        return str(path)
    finally:
        plt.close(fig)
