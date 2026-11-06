"""看板 manifest：把模板快照映射成 Widget 列表（不渲染、不复制数据）。"""
from __future__ import annotations

from typing import Any

# 每个结果键的列名（与 template.build_metric_sqls 的 SELECT 顺序一一对应）
COLUMN_MAP: dict[str, list[str]] = {
    "kpi": ["销售额", "销售成本", "毛利", "毛利率%", "销量", "折扣额", "折扣率%",
            "行数", "商品数", "天数", "优惠额"],
    "daily": ["RQ", "销售额", "毛利", "毛利率%", "折扣额", "销量", "行数"],
    "fl1": ["一级品类", "销售额", "毛利", "毛利率%", "销量", "折扣额", "商品数"],
    "fl2": ["一级品类", "二级品类", "销售额", "毛利", "毛利率%", "商品数"],
    "top_sp": ["商品", "一级品类", "销售额", "毛利", "毛利率%", "销量"],
    "neg_sp": ["商品", "一级品类", "负毛利行数", "负毛利额", "销售额"],
    "neg_daily": ["RQ", "负毛利行数", "负毛利额"],
    "neg_fl1": ["一级品类", "负毛利行数", "负毛利额", "销售额"],
    "zk_fl1": ["一级品类", "折扣额", "折扣率%"],
    "fl2_ml": ["一级品类", "二级品类", "毛利", "销售额", "毛利率%"],
    "dow": ["星期", "销售额", "毛利", "天数"],
    "supplier": ["供货单位", "销售额", "毛利", "商品数"],
}

_KPI_CARDS = [
    (0, "销售额", 3),
    (2, "毛利", 3),
    (3, "毛利率", 3),
    (4, "销量", 3),
]

_PLAN: list[dict[str, Any]] = [
    *[{"key": "kpi", "type": "kpi_card", "title": label, "value_index": idx,
       "layout": {"x": i * 3, "y": 0, "w": 3, "h": 2}}
      for i, (idx, label, _w) in enumerate(_KPI_CARDS)],
    {"key": "daily", "type": "trend_line", "title": "日销售与毛利趋势",
     "layout": {"x": 0, "y": 2, "w": 12, "h": 5},
     "series": ["销售额", "毛利"]},
    {"key": "fl1", "type": "share_pie", "title": "一级品类销售额占比",
     "layout": {"x": 0, "y": 7, "w": 6, "h": 5}, "dimension": "一级品类", "metric": "销售额"},
    {"key": "fl1", "type": "rank_bar", "title": "一级品类销售额排行",
     "layout": {"x": 6, "y": 7, "w": 6, "h": 5}, "dimension": "一级品类", "metric": "销售额"},
    {"key": "fl2", "type": "rank_bar", "title": "二级品类 TOP12",
     "layout": {"x": 0, "y": 12, "w": 6, "h": 5}, "dimension": "二级品类", "metric": "销售额"},
    {"key": "top_sp", "type": "rank_bar", "title": "商品销售额 TOP10",
     "layout": {"x": 6, "y": 12, "w": 6, "h": 5}, "dimension": "商品", "metric": "销售额"},
    {"key": "neg_sp", "type": "detail_table", "title": "负毛利商品 TOP10",
     "layout": {"x": 0, "y": 17, "w": 6, "h": 5}},
    {"key": "neg_daily", "type": "trend_line", "title": "负毛利日趋势",
     "layout": {"x": 6, "y": 17, "w": 6, "h": 5}, "series": ["负毛利额"]},
    {"key": "neg_fl1", "type": "rank_bar", "title": "负毛利一级品类",
     "layout": {"x": 0, "y": 22, "w": 6, "h": 5}, "dimension": "一级品类", "metric": "负毛利额"},
    {"key": "zk_fl1", "type": "rank_bar", "title": "折扣额一级品类",
     "layout": {"x": 6, "y": 22, "w": 6, "h": 5}, "dimension": "一级品类", "metric": "折扣额"},
    {"key": "fl2_ml", "type": "rank_bar", "title": "毛利额 TOP10 二级类",
     "layout": {"x": 0, "y": 27, "w": 6, "h": 5}, "dimension": "二级品类", "metric": "毛利"},
    {"key": "supplier", "type": "rank_bar", "title": "供货单位 TOP8",
     "layout": {"x": 6, "y": 27, "w": 6, "h": 5}, "dimension": "供货单位", "metric": "销售额"},
    {"key": "dow", "type": "rank_bar", "title": "周几销售分布",
     "layout": {"x": 0, "y": 32, "w": 6, "h": 5}, "dimension": "星期", "metric": "销售额"},
]


def validate_manifest(manifest: list[dict[str, Any]], snapshot: dict[str, Any]) -> list[str]:
    """影子模式比对：列映射必须与实际行长度一致，空结果不应出卡片。"""
    issues: list[str] = []
    for w in manifest:
        rows = snapshot.get(w["data_ref"])
        if not rows:
            issues.append(f"{w['id']} 引用了空结果 {w['data_ref']}")
            continue
        first = rows[0]
        if not isinstance(first, (list, tuple)):
            issues.append(f"{w['id']} 的 {w['data_ref']} 行不是数组")
            continue
        if w["widget_type"] == "kpi_card":
            continue
        if len(first) != len(w["columns"]):
            issues.append(f"{w['id']} 的 {w['data_ref']} 列数 {len(w['columns'])} != 行宽 {len(first)}")
    return issues

def sort_rows_for_widget(widget: dict[str, Any], rows: list[Any]) -> list[Any]:
    """远端引擎不保证 ORDER BY 语义，展示前按组件语义稳定排序。"""
    if not rows:
        return rows
    cols = widget.get("columns") or []
    wtype = widget.get("widget_type")
    options = widget.get("options") or {}
    if wtype == "trend_line":
        return sorted(rows, key=lambda r: str(r[0]))
    if wtype in ("rank_bar", "share_pie", "pareto_bar"):
        metric = options.get("metric")
        if metric in cols:
            mi = cols.index(metric)
            try:
                return sorted(rows, key=lambda r: float(r[mi] or 0), reverse=True)
            except (TypeError, ValueError):
                return rows
    if wtype == "detail_table" and "负毛利额" in cols:
        mi = cols.index("负毛利额")
        try:
            return sorted(rows, key=lambda r: float(r[mi] or 0))
        except (TypeError, ValueError):
            return rows
    return rows


def build_manifest(snapshot: dict[str, Any], template_id: str = "retail_overview") -> list[dict[str, Any]]:
    """按模板计划生成 widget 列表；空结果直接跳过，避免空卡片。"""
    if template_id != "retail_overview":
        return []
    widgets: list[dict[str, Any]] = []
    seq = 0
    for plan in _PLAN:
        key = plan["key"]
        rows = snapshot.get(key)
        if not rows:
            continue
        columns = COLUMN_MAP.get(key)
        if not columns:
            continue
        if plan["type"] == "kpi_card":
            idx = plan["value_index"]
            row = rows[0]
            if idx >= len(row):
                continue
            value = row[idx]
        widget = {
            "id": f"w_{seq}",
            "widget_type": plan["type"],
            "title": plan["title"],
            "layout": dict(plan["layout"]),
            "data_ref": key,
            "columns": columns,
            "options": {
                "dimension": plan.get("dimension"),
                "metric": plan.get("metric"),
                "series": plan.get("series") or [],
                "value": value if plan["type"] == "kpi_card" else None,
            },
        }
        widgets.append(widget)
        seq += 1
    return widgets


# 组件指标 → 明细下钻所需的 SQL 表达式（与 template.py 同口径）
METRIC_EXPR: dict[str, str] = {
    "销售额": "SUM(XSJE)",
    "毛利": "SUM(ML)",
    "毛利率%": "SUM(ML)/NULLIF(SUM(XSJE),0)*100",
    "销量": "SUM(XSSL)",
    "折扣额": "SUM(ZKJE)",
    "负毛利额": "SUM(ML)",
    "负毛利行数": "COUNT(*)",
}

_DIRECT_CHILD = ("供货单位", "分店")


def build_interaction(dimensions: list[dict[str, Any]], widgets: list[dict[str, Any]]) -> dict[str, Any]:
    """生成筛选器白名单与每个组件的下钻配置（仅下发已注册维度）。"""
    filters = [
        {"field": d["field"], "label": d["name"], "type": d.get("type") or "string", "level": d.get("level", 0)}
        for d in dimensions
    ]
    product = next((d for d in dimensions if d["name"] == "商品"), None)
    for w in widgets:
        if w.get("widget_type") not in ("rank_bar", "share_pie"):
            continue
        options = w.get("options") or {}
        label = options.get("dimension")
        dim = next((d for d in dimensions if d["name"] == label), None)
        metric = options.get("metric")
        expr = METRIC_EXPR.get(str(metric))
        if dim is None or not expr or dim.get("type") == "date":
            continue
        if label in _DIRECT_CHILD:
            detail = [product["field"]] if product else []
        else:
            children = sorted(
                [d for d in dimensions if d.get("level", 0) > dim.get("level", 0)],
                key=lambda d: d.get("level", 0),
            )
            detail = [children[0]["field"]] if children else []
            if product and product["field"] not in detail and dim.get("level", 0) < product.get("level", 4):
                detail.append(product["field"])
            detail = detail[:2]
        if not detail:
            continue
        w["drill"] = {
            "enabled": True,
            "field": dim["field"],
            "label": dim["name"],
            "metric_name": metric,
            "metric_expr": expr,
            "metric_alias": "m0",
            "detail_dimensions": detail,
        }
    return {"filters": filters, "metric_expressions": dict(METRIC_EXPR)}
