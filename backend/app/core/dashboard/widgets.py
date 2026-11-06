"""Widget 注册表：每个组件只负责把 (数据契约) 渲染成 HTML 片段。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from typing import Any, Callable


@dataclass(frozen=True)
class WidgetDef:
    type: str
    min_cols: int
    render: Callable[[dict, dict, dict], str]


WIDGET_REGISTRY: dict[str, WidgetDef] = {}


def register_widget(wtype: str, min_cols: int = 1):
    def deco(fn: Callable[[dict, dict, dict], str]):
        WIDGET_REGISTRY[wtype] = WidgetDef(wtype, min_cols, fn)
        return fn
    return deco


def _esc(value: Any) -> str:
    return escape(str("" if value is None else value))


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return _esc(value)
    if digits == 0:
        return f"{num:,.0f}"
    return f"{num:,.{digits}f}"


def _chart(wid: str, option: dict, height: int = 320) -> str:
    payload = json.dumps(option, ensure_ascii=False)
    return (
        f'<div id="{wid}" style="width:100%;height:{height}px"></div>'
        f'<script>(function(){{var el=document.getElementById("{wid}");'
        f'if(!el||!window.echarts)return;var c=echarts.init(el);c.setOption({payload});'
        f'window.addEventListener("resize",function(){{c.resize();}});}})();</script>'
    )


def _rows(widget: dict, snap: dict) -> list[list[Any]]:
    return snap.get(widget.get("data_ref") or "") or []


def _col(widget: dict, name: str | None) -> int | None:
    for i, c in enumerate(widget.get("columns") or []):
        if str(c) == str(name):
            return i
    return None


@register_widget("kpi_card", min_cols=1)
def render_kpi_card(widget: dict, snap: dict, ctx: dict) -> str:
    value = (widget.get("options") or {}).get("value")
    return (
        f'<div class="kpi"><div class="kpi-label">{_esc(widget.get("title"))}</div>'
        f'<div class="kpi-value">{_fmt(value)}</div></div>'
    )


@register_widget("trend_line", min_cols=2)
def render_trend_line(widget: dict, snap: dict, ctx: dict) -> str:
    rows = _rows(widget, snap)
    if not rows:
        return '<div class="empty">数据不足</div>'
    columns = widget.get("columns") or []
    series_names = (widget.get("options") or {}).get("series") or columns[1:]
    idx = [(_col(widget, name), name) for name in series_names]
    idx = [(i, n) for i, n in idx if i is not None]
    option = {
        "tooltip": {"trigger": "axis"},
        "legend": {"data": [n for _, n in idx], "top": 0},
        "grid": {"left": 46, "right": 18, "top": 34, "bottom": 28},
        "xAxis": {"type": "category", "data": [str(r[0]) for r in rows]},
        "yAxis": {"type": "value"},
        "series": [{"name": n, "type": "line", "smooth": True, "showSymbol": False,
                    "data": [_num(r[i]) for r in rows]} for i, n in idx],
    }
    return _chart(widget["id"], option)


@register_widget("rank_bar", min_cols=2)
def render_rank_bar(widget: dict, snap: dict, ctx: dict) -> str:
    rows = _rows(widget, snap)
    if not rows:
        return '<div class="empty">数据不足</div>'
    dim = _col(widget, (widget.get("options") or {}).get("dimension"))
    metric = _col(widget, (widget.get("options") or {}).get("metric"))
    if dim is None or metric is None:
        return '<div class="empty">字段不匹配</div>'
    labels = [str(r[dim]) for r in rows]
    values = [_num(r[metric]) for r in rows]
    option = {
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 96, "right": 26, "top": 14, "bottom": 22},
        "xAxis": {"type": "value"},
        "yAxis": {"type": "category", "data": labels, "inverse": True},
        "series": [{
            "type": "bar",
            "data": [{"value": v, "itemStyle": {"color": "#dc2626" if v < 0 else "#2563eb"}} for v in values],
            "label": {"show": True, "position": "right", "formatter": "{c}"},
        }],
    }
    return _chart(widget["id"], option)


@register_widget("share_pie", min_cols=2)
def render_share_pie(widget: dict, snap: dict, ctx: dict) -> str:
    rows = _rows(widget, snap)
    if not rows:
        return '<div class="empty">数据不足</div>'
    dim = _col(widget, (widget.get("options") or {}).get("dimension"))
    metric = _col(widget, (widget.get("options") or {}).get("metric"))
    if dim is None or metric is None:
        return '<div class="empty">字段不匹配</div>'
    pairs = [(str(r[dim]), _num(r[metric])) for r in rows]
    head, tail = pairs[:8], pairs[8:]
    if tail:
        head.append(("其他", sum(v for _, v in tail)))
    option = {
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
        "legend": {"type": "scroll", "bottom": 0},
        "series": [{"type": "pie", "radius": ["38%", "66%"], "center": ["50%", "44%"],
                    "data": [{"name": n, "value": v} for n, v in head]}],
    }
    return _chart(widget["id"], option)


@register_widget("detail_table", min_cols=2)
def render_detail_table(widget: dict, snap: dict, ctx: dict) -> str:
    rows = _rows(widget, snap)
    if not rows:
        return '<div class="empty">数据不足</div>'
    columns = widget.get("columns") or []
    head = "".join(f"<th>{_esc(c)}</th>" for c in columns)
    body = []
    for r in rows[:50]:
        cells = "".join(f"<td>{_fmt(v) if isinstance(v, (int, float)) else _esc(v)}</td>" for v in r)
        body.append(f"<tr>{cells}</tr>")
    more = f'<div class="hint">共 {len(rows)} 行，仅展示前 50 行</div>' if len(rows) > 50 else ""
    return f'<div class="tbl-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>{more}'


@register_widget("insight_text", min_cols=1)
def render_insight_text(widget: dict, snap: dict, ctx: dict) -> str:
    facts = (widget.get("options") or {}).get("facts") or []
    if not facts:
        return '<div class="empty">暂无结论</div>'
    items = "".join(f"<li>{_esc(f.get('text'))}</li>" for f in facts if isinstance(f, dict))
    return f"<ul class='facts'>{items}</ul>"


def render_widget(widget: dict, snap: dict, ctx: dict) -> str:
    wtype = widget.get("widget_type")
    definition = WIDGET_REGISTRY.get(wtype) or WIDGET_REGISTRY.get("detail_table")
    if definition is None or definition.render is None:
        return '<div class="empty">未知组件</div>'
    return definition.render(widget, snap, ctx)
