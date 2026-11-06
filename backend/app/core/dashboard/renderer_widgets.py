"""Widget 化看板渲染：与 render_retail_dashboard 并行存在，互不修改。"""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from app.core.dashboard.widgets import render_widget


def _esc(value: Any) -> str:
    return escape(str("" if value is None else value))


def _css() -> str:
    return """
:root{--bg:#f4f6fa;--card:#fff;--ink:#17202e;--muted:#66758c;--rule:#e4e9f2;--accent:#2563eb}
*{box-sizing:border-box}
body{margin:0;padding:22px;background:var(--bg);color:var(--ink);
 font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.head{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:14px}
.head h1{margin:0;font-size:20px}
.head .sub{color:var(--muted);font-size:12px}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:12px}
.card{background:var(--card);border:1px solid var(--rule);border-radius:12px;padding:12px 14px;
 box-shadow:0 1px 2px rgba(16,24,40,.04);min-width:0}
.card h3{margin:0 0 8px;font-size:13px;font-weight:600;color:#334155}
.kpi{background:linear-gradient(135deg,#fff,#f8fbff);border:1px solid var(--rule);border-radius:12px;
 padding:14px 16px}
.kpi-label{font-size:12px;color:var(--muted)}
.kpi-value{font-size:22px;font-weight:700;margin-top:4px;letter-spacing:-.02em}
.empty{color:var(--muted);font-size:12px;padding:24px 0;text-align:center}
.tbl-wrap{max-height:300px;overflow:auto}
table{width:100%;border-collapse:collapse;font-size:11.5px}
th{position:sticky;top:0;background:#f1f5fb;text-align:left;padding:6px 8px;border-bottom:1px solid var(--rule)}
td{padding:5px 8px;border-bottom:1px solid #f1f4f9;white-space:nowrap}
.hint{font-size:11px;color:var(--muted);margin-top:6px}
.facts{margin:0;padding-left:18px;font-size:12px;line-height:1.8}
footer{margin-top:18px;color:var(--muted);font-size:11px}
"""


def render_widgets_dashboard(
    manifest: list[dict[str, Any]],
    snapshot: dict[str, Any],
    meta: dict[str, Any],
) -> str:
    """按 manifest 渲染 HTML；布局使用 12 列栅格。"""
    title = meta.get("title") or "经营看板"
    source_name = meta.get("source_name") or ""
    generated_at = meta.get("generated_at") or datetime.now()
    ctx: dict[str, Any] = {}

    cards: list[str] = []
    for widget in manifest:
        layout = widget.get("layout") or {}
        style = (
            f"grid-column:{int(layout.get('x', 0)) + 1} / span {int(layout.get('w', 4))};"
            f"grid-row:{int(layout.get('y', 0)) + 1} / span {int(layout.get('h', 4))};"
        )
        inner = render_widget(widget, snapshot, ctx)
        cls = "kpi" if widget.get("widget_type") == "kpi_card" else "card"
        heading = "" if cls == "kpi" else f"<h3>{_esc(widget.get('title'))}</h3>"
        cards.append(f'<div class="{cls}" style="{style}">{heading}{inner}</div>')

    from app.core.dashboard.renderer import _echarts_js

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{_esc(title)}</title>
<style>{_css()}</style>
<script>{_echarts_js()}</script>
</head><body>
<div class="head">
  <div><h1>{_esc(title)}</h1>
  <div class="sub">数据源：{_esc(source_name)} · 生成于 {generated_at:%Y-%m-%d %H:%M}</div></div>
</div>
<div class="grid">{''.join(cards)}</div>
<footer>全部数值由数据源 SQL 直查聚合生成，未做估算或填充。</footer>
</body></html>"""
