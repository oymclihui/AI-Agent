"""看板渲染器：数据快照 → 自包含 HTML（echarts 与字体内嵌，零外部依赖）。

铁律实现：HTML 中全部数值由快照数据程序化注入/计算，模板不含任何手写数字结论；
洞察文字由代码按快照生成（无 LLM 参与），数字均可回溯到快照字段。
"""
from __future__ import annotations

import base64
import html as _html
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

ASSETS_DIR = Path(__file__).parent / "assets"


@lru_cache(maxsize=1)
def _echarts_js() -> str:
    return (ASSETS_DIR / "echarts.min.js").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _fonts_css() -> str:
    def b64(name: str) -> str:
        return base64.b64encode((ASSETS_DIR / "fonts" / name).read_bytes()).decode("ascii")

    return (
        "@font-face{font-family:'Outfit';src:url(data:font/ttf;base64,"
        + b64("Outfit-Regular.ttf")
        + ") format('truetype');font-weight:400;}"
        "@font-face{font-family:'Outfit';src:url(data:font/ttf;base64,"
        + b64("Outfit-Bold.ttf")
        + ") format('truetype');font-weight:700;}"
        "@font-face{font-family:'JetBrains Mono';src:url(data:font/ttf;base64,"
        + b64("JetBrainsMono-Regular.ttf")
        + ") format('truetype');}"
    )


def _f2(v: Any) -> str:
    return f"{float(v):,.2f}"


def _f1(v: Any) -> str:
    return f"{float(v):,.1f}"


def _f0(v: Any) -> str:
    return f"{float(v):,.0f}"


def _esc(v: Any) -> str:
    return _html.escape(str(v if v is not None else ""))


DOW_CN = {
    "Monday": "周一", "Tuesday": "周二", "Wednesday": "周三", "Thursday": "周四",
    "Friday": "周五", "Saturday": "周六", "Sunday": "周日",
}
DOW_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _num(rows: list[list[Any]], idx: int, default: float = 0.0) -> list[float]:
    out: list[float] = []
    for r in rows:
        try:
            out.append(float(r[idx]))
        except Exception:
            out.append(default)
    return out


def render_retail_dashboard(
    snap: dict[str, Any],
    *,
    title: str,
    source_name: str,
    anchor_detail: dict[str, Any],
    generated_at: datetime | None = None,
) -> str:
    """渲染零售经营看板。snap 为 builder.fetch_snapshot 的输出。"""
    kpi = snap["kpi"][0]
    XSJE, XSCB, ML, MLR = float(kpi[0]), float(kpi[1]), float(kpi[2]), float(kpi[3])
    XSSL, ZKJE, ZKR = float(kpi[4]), float(kpi[5]), float(kpi[6])
    ROWS, SPS, DAYS, YHJE = int(kpi[7]), int(kpi[8]), int(kpi[9]), float(kpi[10])
    day_avg = XSJE / DAYS if DAYS else 0.0

    daily = snap["daily"]
    fl1, fl2 = snap["fl1"], snap["fl2"]
    top_sp, neg_sp = snap["top_sp"], snap["neg_sp"]
    neg_daily, neg_fl1 = snap["neg_daily"], snap["neg_fl1"]
    zk_fl1, fl2_ml = snap["zk_fl1"], snap["fl2_ml"]
    dow, supplier = snap["dow"], snap["supplier"]
    anchor = snap.get("anchor") or {}

    gen_at = generated_at or datetime.now()
    period = f"{anchor.get('min_rq') or ''} 至 {anchor.get('max_rq') or ''}"

    # ── 派生指标（全部由快照计算）──
    neg_ml_total = sum(float(r[2]) for r in neg_daily)
    neg_rows_total = sum(int(r[1]) for r in neg_daily)
    neg_days = [(str(d[0]), float(d[2])) for d in daily if float(d[2]) < 0]
    mlr_sorted = sorted(daily, key=lambda r: float(r[3]))
    worst_days = mlr_sorted[:2] if len(mlr_sorted) >= 2 else mlr_sorted
    fl1_total = sum(float(r[1]) for r in fl1) or 1.0
    fl1_low = min(fl1, key=lambda r: float(r[3])) if fl1 else None
    neg_peak = min(neg_daily, key=lambda r: float(r[2])) if neg_daily else None
    dow_sorted = sorted(dow, key=lambda r: DOW_ORDER.index(str(r[0])) if str(r[0]) in DOW_ORDER else 99)
    dow_worst = min(dow, key=lambda r: float(r[2])) if dow else None
    zk_top = max(zk_fl1, key=lambda r: float(r[2])) if zk_fl1 else None
    sup_pos = sorted(supplier, key=lambda r: float(r[2]), reverse=True)
    sup_best = sup_pos[0] if sup_pos else None
    sup_neg = [r for r in supplier if float(r[2]) < 0]
    top1 = top_sp[0] if top_sp else None
    neg_sp3 = neg_sp[:3]
    neg_sp3_sum = sum(float(r[3]) for r in neg_sp3)
    fl2_best = max(fl2, key=lambda r: float(r[4])) if fl2 else None

    # ── 表格行 ──
    def top_sp_rows() -> str:
        out = []
        for i, r in enumerate(top_sp, 1):
            mlr = float(r[4])
            cls = ' class="neg"' if mlr < 0 else ""
            badge = ' <span class="tag tag-bad">负毛利</span>' if mlr < 0 else ""
            out.append(
                f"<tr><td class='rk'>{i}</td><td>{_esc(r[0])}{badge}</td><td>{_esc(r[1])}</td>"
                f"<td class='num'>{_f2(r[2])}</td><td class='num'{cls}>{_f2(r[3])}</td>"
                f"<td class='num'{cls}>{mlr:.2f}%</td><td class='num'>{_f1(r[5])}</td></tr>")
        return "\n".join(out)

    def neg_sp_rows() -> str:
        out = []
        for i, r in enumerate(neg_sp, 1):
            out.append(
                f"<tr><td class='rk'>{i}</td><td>{_esc(r[0])}</td><td>{_esc(r[1])}</td>"
                f"<td class='num'>{int(r[2])}</td><td class='num neg'>{_f2(r[3])}</td>"
                f"<td class='num'>{_f2(r[4])}</td></tr>")
        return "\n".join(out)

    def supplier_rows() -> str:
        out = []
        for i, r in enumerate(supplier, 1):
            ml_v = float(r[2])
            cls = ' class="neg"' if ml_v < 0 else ""
            out.append(
                f"<tr><td class='rk'>{i}</td><td>{_esc(r[0])}</td>"
                f"<td class='num'>{_f2(r[1])}</td><td class='num'{cls}>{_f2(r[2])}</td>"
                f"<td class='num'>{int(r[3])}</td></tr>")
        return "\n".join(out)

    def fl2_ml_rows() -> str:
        out = []
        for i, r in enumerate(fl2_ml, 1):
            out.append(
                f"<tr><td class='rk'>{i}</td><td>{_esc(r[0])} / {_esc(r[1])}</td>"
                f"<td class='num'>{_f2(r[2])}</td><td class='num'>{_f2(r[3])}</td>"
                f"<td class='num'>{float(r[4]):.2f}%</td></tr>")
        return "\n".join(out)

    # ── 图表数据（JS 注入防 </script> 闭合）──
    dash_json = json.dumps({
        "daily": daily, "fl1": fl1, "fl2": fl2, "negDaily": neg_daily,
        "negFl1": neg_fl1, "zkFl1": zk_fl1,
        "dow": [[DOW_CN.get(str(r[0]), str(r[0])), r[1], r[2]] for r in dow_sorted],
    }, ensure_ascii=False, default=str).replace("</", "<\\/")

    mark_points = ",".join(
        "{ coord: ['%s', %s], value: '%.1f' }" % (str(d[0])[5:], float(d[3]), float(d[3]))
        for d in worst_days
    )

    charts_js = "var DASH = " + dash_json + ";\n" + r'''
(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();
  var FONT = 'Outfit, "Microsoft YaHei", sans-serif';
  function mk(id) {
    var c = echarts.init(document.getElementById(id), null, { renderer: 'svg' });
    window.addEventListener('resize', function() { c.resize(); });
    return c;
  }
  var baseAxis = { axisLine: { lineStyle: { color: rule } }, axisLabel: { color: muted, fontFamily: FONT } };
  function tt(extra) {
    return Object.assign({ trigger: 'axis', appendToBody: true,
      textStyle: { fontFamily: FONT, color: ink },
      backgroundColor: bg2, borderColor: rule }, extra || {});
  }

  var dates = DASH.daily.map(function(r){ return String(r[0]).slice(5); });
  var sales = DASH.daily.map(function(r){ return +r[1]; });
  var mlr   = DASH.daily.map(function(r){ return +r[3]; });
  mk('chart-daily').setOption({
    animation: false, tooltip: tt(), textStyle: { fontFamily: FONT },
    legend: { data: ['销售额(元)', '毛利率(%)'], textStyle: { color: muted }, top: 0 },
    grid: { left: 70, right: 56, top: 42, bottom: 46 },
    xAxis: Object.assign({ type: 'category', data: dates, axisLabel: { color: muted, rotate: 45, fontSize: 11 } }, baseAxis),
    yAxis: [
      Object.assign({ type: 'value', name: '销售额(元)', nameTextStyle: { color: muted },
        splitLine: { lineStyle: { color: rule } } }, baseAxis),
      Object.assign({ type: 'value', name: '毛利率(%)', nameTextStyle: { color: muted },
        splitLine: { show: false } }, baseAxis)
    ],
    series: [
      { name: '销售额(元)', type: 'bar', data: sales, barMaxWidth: 16,
        itemStyle: { color: accent + 'cc', borderRadius: [3,3,0,0] } },
      { name: '毛利率(%)', type: 'line', yAxisIndex: 1, data: mlr, symbolSize: 5,
        lineStyle: { color: accent2, width: 2 }, itemStyle: { color: accent2 },
        markPoint: { symbolSize: 46,
          itemStyle: { color: accent2 },
          label: { color: '#fff', fontSize: 10, fontFamily: FONT },
          data: [__MARK_POINTS__] } }
    ]
  });

  mk('chart-fl1').setOption({
    animation: false, textStyle: { fontFamily: FONT },
    tooltip: { trigger: 'item', appendToBody: true,
      formatter: function(p){ return p.name + '：' + Number(p.value).toLocaleString() + ' 元（' + p.percent + '%）'; } },
    legend: { bottom: 0, textStyle: { color: muted } },
    series: [{ type: 'pie', radius: ['46%', '70%'], center: ['50%', '46%'],
      label: { color: ink, formatter: '{b}\n{d}%' },
      itemStyle: { borderColor: bg2, borderWidth: 2 },
      data: DASH.fl1.map(function(r, i){
        var colors = [accent, accent2, muted, accent + '66', '#3aa17e', '#f0a032'];
        return { name: r[0], value: +r[1], itemStyle: { color: colors[i % 6] } };
      }) }]
  });

  mk('chart-fl1-rate').setOption({
    animation: false, tooltip: tt({ trigger: 'axis', axisPointer: { type: 'shadow' } }),
    textStyle: { fontFamily: FONT },
    grid: { left: 60, right: 50, top: 20, bottom: 30 },
    xAxis: Object.assign({ type: 'value', name: '%', nameTextStyle: { color: muted },
      splitLine: { lineStyle: { color: rule } } }, baseAxis),
    yAxis: Object.assign({ type: 'category',
      data: DASH.fl1.map(function(r){ return r[0]; }).reverse() }, baseAxis),
    series: [{ type: 'bar', barMaxWidth: 22,
      data: DASH.fl1.map(function(r){ return +r[3]; }).reverse(),
      label: { show: true, position: 'right', color: ink,
        formatter: function(p){ return p.value.toFixed(2) + '%'; } },
      itemStyle: { color: function(p){ return p.value < 5 ? accent2 : accent; }, borderRadius: [0,3,3,0] } }]
  });

  var fl2r = DASH.fl2.slice().reverse();
  mk('chart-fl2').setOption({
    animation: false, tooltip: tt(), textStyle: { fontFamily: FONT },
    legend: { data: ['销售额(元)', '毛利率(%)'], textStyle: { color: muted }, top: 0 },
    grid: { left: 110, right: 56, top: 40, bottom: 30 },
    xAxis: [
      Object.assign({ type: 'value', splitLine: { lineStyle: { color: rule } } }, baseAxis),
      Object.assign({ type: 'value', splitLine: { show: false } }, baseAxis)
    ],
    yAxis: Object.assign({ type: 'category',
      data: fl2r.map(function(r){ return r[0] + '·' + r[1]; }),
      axisLabel: { color: muted, fontSize: 11 } }, baseAxis),
    series: [
      { name: '销售额(元)', type: 'bar', barMaxWidth: 13,
        data: fl2r.map(function(r){ return +r[2]; }),
        itemStyle: { color: accent + 'cc', borderRadius: [0,3,3,0] } },
      { name: '毛利率(%)', type: 'scatter', xAxisIndex: 1, symbolSize: 9,
        data: fl2r.map(function(r){ return +r[4]; }),
        itemStyle: { color: accent2 } }
    ]
  });

  mk('chart-neg').setOption({
    animation: false, tooltip: tt(), textStyle: { fontFamily: FONT },
    legend: { data: ['负毛利金额(元)', '负毛利行数'], textStyle: { color: muted }, top: 0 },
    grid: { left: 76, right: 60, top: 42, bottom: 46 },
    xAxis: Object.assign({ type: 'category',
      data: DASH.negDaily.map(function(r){ return String(r[0]).slice(5); }),
      axisLabel: { color: muted, rotate: 45, fontSize: 11 } }, baseAxis),
    yAxis: [
      Object.assign({ type: 'value', name: '金额(元)', nameTextStyle: { color: muted },
        splitLine: { lineStyle: { color: rule } } }, baseAxis),
      Object.assign({ type: 'value', name: '行数', nameTextStyle: { color: muted },
        splitLine: { show: false } }, baseAxis)
    ],
    series: [
      { name: '负毛利金额(元)', type: 'bar', barMaxWidth: 14,
        data: DASH.negDaily.map(function(r){ return +r[2]; }),
        itemStyle: { color: accent2 + 'cc', borderRadius: [3,3,0,0] } },
      { name: '负毛利行数', type: 'line', yAxisIndex: 1, symbolSize: 5,
        data: DASH.negDaily.map(function(r){ return r[1]; }),
        lineStyle: { color: muted, width: 1.6, type: 'dashed' }, itemStyle: { color: muted } }
    ]
  });

  mk('chart-zk').setOption({
    animation: false, tooltip: tt({ trigger: 'axis', axisPointer: { type: 'shadow' } }),
    textStyle: { fontFamily: FONT },
    grid: { left: 60, right: 50, top: 20, bottom: 30 },
    xAxis: Object.assign({ type: 'value', name: '%', nameTextStyle: { color: muted },
      splitLine: { lineStyle: { color: rule } } }, baseAxis),
    yAxis: Object.assign({ type: 'category',
      data: DASH.zkFl1.map(function(r){ return r[0]; }).reverse() }, baseAxis),
    series: [{ type: 'bar', barMaxWidth: 22,
      data: DASH.zkFl1.map(function(r){ return +r[2]; }).reverse(),
      label: { show: true, position: 'right', color: ink,
        formatter: function(p){ return p.value.toFixed(2) + '%'; } },
      itemStyle: { color: accent + 'cc', borderRadius: [0,3,3,0] } }]
  });

  mk('chart-dow').setOption({
    animation: false, tooltip: tt(), textStyle: { fontFamily: FONT },
    legend: { data: ['销售额(元)', '毛利(元)'], textStyle: { color: muted }, top: 0 },
    grid: { left: 76, right: 30, top: 42, bottom: 30 },
    xAxis: Object.assign({ type: 'category', data: DASH.dow.map(function(r){ return r[0]; }) }, baseAxis),
    yAxis: Object.assign({ type: 'value', splitLine: { lineStyle: { color: rule } } }, baseAxis),
    series: [
      { name: '销售额(元)', type: 'bar', barMaxWidth: 18,
        data: DASH.dow.map(function(r){ return +r[1]; }),
        itemStyle: { color: accent + 'cc', borderRadius: [3,3,0,0] } },
      { name: '毛利(元)', type: 'bar', barMaxWidth: 18,
        data: DASH.dow.map(function(r){ return +r[2]; }),
        itemStyle: { color: function(p){ return p.value < 0 ? accent2 : accent2 + '55'; },
          borderRadius: [3,3,0,0] } }
    ]
  });
})();
'''.replace("__MARK_POINTS__", mark_points)

    # ── 洞察（全部数值由快照计算，文字模板化，无 LLM）──
    insights: list[str] = []
    if neg_daily and ML:
        share = abs(neg_ml_total) / ML * 100 if ML else 0.0
        names = "、".join(f"{_esc(r[0])}（{_f2(r[3])} 元）" for r in neg_sp3)
        neg_fl1_top = _esc(neg_fl1[0][0]) if neg_fl1 else ""
        neg_fl1_top_ml = _f2(neg_fl1[0][2]) if neg_fl1 else "0"
        insights.append(
            f"<b>负毛利是第一失血点：</b>全期负毛利 <span class=\"bad\">¥{_f2(neg_ml_total)}</span>"
            f"（{neg_rows_total:,} 行），相当于全期毛利的 <span class=\"bad\">{share:.1f}%</span>。"
            f"其中 {neg_fl1_top} 占 {neg_fl1_top_ml} 元为最大头；负毛利 TOP3 单品 {names}，合计 {_f2(neg_sp3_sum)} 元，"
            f"<mark class=\"key\">建议立即核查其进价、损耗与售价策略</mark>。")
    if len(neg_days) >= 2 and neg_peak is not None:
        peak = neg_peak
        insights.append(
            f"<b>负毛利异常日必须复盘：</b>全期共 {len(neg_days)} 个负毛利日"
            f"（{' / '.join(d[0][5:] for d in neg_days)}）；{_esc(str(peak[0]))} 单日负毛利 {_f2(peak[2])} 元 / {int(peak[1])} 行为峰值，"
            f"<mark class=\"key\">疑似集中调价 / 盘点损耗 / 大宗折价出清，需调取当日调价单与盘点记录</mark>。")
    if top1 is not None and float(top1[3]) <= 0:
        insights.append(
            f"<b>高销售 ≠ 高毛利：</b>销售第 1 名 {_esc(top1[0])}（{_f2(top1[2])} 元）毛利 {_f2(top1[3])} 元、"
            f"毛利率 {float(top1[4]):.2f}%，<mark class=\"key\">建议重谈供货条件或调整零售价，"
            f"否则「卖得越多亏得越多」</mark>。")
    if fl2_best is not None and sup_best is not None:
        insights.append(
            f"<b>结构性亮点可复制：</b>{_esc(fl2_best[1])} 毛利率 {float(fl2_best[4]):.2f}%、"
            f"供应商 {_esc(sup_best[0])} 毛利 {_f2(sup_best[2])} 元为最优供应结构。"
            f"<mark class=\"key\">建议扩大高毛利品类排面与 SKU，对冲低毛利板块</mark>。")
    if fl1_low is not None:
        insights.append(
            f"<b>{_esc(fl1_low[0])} 毛利率最低：</b>销售额 {_f2(fl1_low[1])} 元、毛利率仅 {float(fl1_low[3]):.2f}%，"
            f"<mark class=\"key\">占用排面与资金却几乎不贡献毛利，建议重谈扣点或压缩低效 SKU</mark>。")
    if zk_top is not None and ZKR:
        insights.append(
            f"<b>折扣率 {ZKR:.2f}% 需评估 ROI：</b>全期折扣 {_f2(ZKJE)} 元（另优惠 {_f2(YHJE)} 元），"
            f"{_esc(zk_top[0])} 折扣率 {float(zk_top[2]):.2f}% 最高。"
            f"<mark class=\"key\">建议评估促销 ROI：折扣换来的销量是否覆盖了折扣成本</mark>。")
    if sup_neg:
        names = "、".join(_esc(r[0]) for r in sup_neg[:3])
        insights.append(
            f"<b>毛利为负的供应商：</b>{names} 全期毛利为负，"
            f"<mark class=\"key\">建议重谈供货条件或替换货源</mark>。")
    if dow_worst is not None and float(dow_worst[2]) < 0:
        insights.append(
            f"<b>星期节律异常：</b>{DOW_CN.get(str(dow_worst[0]), str(dow_worst[0]))} 全期毛利 {_f2(dow_worst[2])} 元为负，"
            f"<mark class=\"key\">与负毛利异常日的星期分布叠加分析，排查周期性调价行为</mark>。")
    if not insights:
        insights.append("本期数据结构健康：未检出负毛利行与明显异常波动，建议保持现有品类与价格策略。")

    insights_html = "\n      ".join(f"<li>{t}</li>" for t in insights)

    # ── 锚点页脚披露（偏差点必显式披露）──
    a_items = anchor_detail.get("items") or []
    a_status = anchor_detail.get("status") or "pass"
    a_asof = anchor_detail.get("baseline_as_of") or ""
    def _a_txt(key: str, label: str) -> str:
        it = next((x for x in a_items if x.get("key") == key), None)
        if not it:
            return ""
        v = it.get("value")
        val = _f2(v) if v is not None else "缺失"
        if it.get("status") == "pass":
            return f"{label} <b>{val}</b>（与基线一致）"
        dev = it.get("deviation")
        dev_pct = f"{float(dev) * 100:.2f}%" if dev is not None else "—"
        return (f"{label} <b class=\"neg\">{val}</b>（基线 {_f2(it.get('baseline'))}，"
                f"偏差 {dev_pct}，已披露）")
    anchor_line = "；".join(x for x in (
        _a_txt("month_xsje", "当月销售额"),
        _a_txt("month_ml", "当月毛利"),
        _a_txt("recent3_xsje", "最近3天销售额"),
    ) if x)
    anchor_badge = {
        "pass": '<span style="color:#1fae7a;font-weight:700">锚点校验通过</span>',
        "warn": '<span style="color:#e05561;font-weight:700">锚点存在偏差（数据可能已更新），见下披露</span>',
        "fail": '<span style="color:#e05561;font-weight:700">锚点校验失败，见下披露</span>',
    }.get(a_status, "")

    # 负毛利为空时隐藏专题块的提示
    neg_section_sub = (
        f"全期负毛利 <b class=\"neg\">¥{_f2(neg_ml_total)}</b>（{neg_rows_total:,} 行）。"
        + (f"{_esc(neg_fl1[0][0])} 占 {_f2(neg_fl1[0][2])} 元为最大头；" if neg_fl1 else "")
        + (f"{_esc(str(neg_peak[0]))} 单日 {_f2(neg_peak[2])} 元 / {int(neg_peak[1])} 行为峰值。" if neg_peak else "")
        if neg_daily else
        "本期未检出负毛利行，价格与成本体系健康。"
    )

    html = f'''<!-- Generated by AI-Agent Dashboard Skill · template=retail_overview -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)}</title>
<style>
  {_fonts_css()}
  :root {{
    --bg: #f5f7fb; --bg2: #ffffff; --ink: #1a2233; --muted: #5b6b84;
    --rule: #e3e8f0; --accent: #2f6bff; --accent2: #e05561;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--ink);
    font-family: Outfit, "Microsoft YaHei", sans-serif; font-size: 15px; line-height: 1.65; }}
  .wrap {{ max-width: 1240px; margin: 0 auto; padding: 32px 22px 60px; }}
  header.mast {{ background: var(--bg2); border: 1px solid var(--rule); border-radius: 14px;
    padding: 26px 30px; border-left: 5px solid var(--accent); }}
  header.mast h1 {{ margin: 0 0 6px; font-size: 25px; letter-spacing: .3px; }}
  header.mast .sub {{ color: var(--muted); font-size: 13.5px; }}
  .caliber {{ margin-top: 12px; font-size: 12.5px; color: var(--muted);
    background: var(--bg); border: 1px dashed var(--rule); border-radius: 8px; padding: 8px 14px; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 20px 0 6px; }}
  .kpi {{ background: var(--bg2); border: 1px solid var(--rule); border-radius: 12px; padding: 16px 18px; }}
  .kpi .k {{ color: var(--muted); font-size: 12.5px; }}
  .kpi .v {{ font-family: 'JetBrains Mono', monospace; font-size: 22px; font-weight: 700; margin: 3px 0 1px; }}
  .kpi .s {{ color: var(--muted); font-size: 11.5px; }}
  .kpi.warn .v {{ color: var(--accent2); }}
  h2.sec {{ font-size: 18px; margin: 34px 0 4px; padding-left: 12px; border-left: 4px solid var(--accent); }}
  p.sec-sub {{ color: var(--muted); font-size: 13px; margin: 0 0 12px 16px; }}
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  figure.chart-figure {{ margin: 0 0 16px; background: var(--bg2); border: 1px solid var(--rule);
    border-radius: 12px; padding: 16px 18px 10px; }}
  figure.chart-figure figcaption {{ font-size: 14px; font-weight: 700; margin-bottom: 8px; }}
  figure.chart-figure .note {{ font-size: 12px; color: var(--muted); font-weight: 400; margin-left: 8px; }}
  .table-wrap {{ overflow-x: auto; overflow-y: auto; max-height: 600px; background: var(--bg2);
    border: 1px solid var(--rule); border-radius: 12px; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; background: #f0f3f9; color: var(--muted); font-weight: 700;
    padding: 10px 14px; border-bottom: 1px solid var(--rule); white-space: nowrap; font-size: 12.5px; }}
  td {{ padding: 9px 14px; border-bottom: 1px solid var(--rule); }}
  tr:last-child td {{ border-bottom: none; }}
  td.num {{ font-family: 'JetBrains Mono', monospace; text-align: right; white-space: nowrap; }}
  td.rk {{ color: var(--muted); width: 34px; }}
  .neg {{ color: var(--accent2); font-weight: 700; }}
  .tag {{ display: inline-block; border-radius: 4px; padding: 1px 7px; font-size: 11px; font-weight: 700; }}
  .tag-bad {{ background: rgba(224,85,97,.12); color: var(--accent2); }}
  .insight {{ background: var(--bg2); border: 1px solid var(--rule); border-radius: 12px; padding: 20px 26px; }}
  .insight ol {{ margin: 0; padding-left: 20px; }}
  .insight li {{ margin: 10px 0; }}
  .insight b {{ color: var(--accent); }}
  .insight .bad {{ color: var(--accent2); font-weight: 700; }}
  mark.key {{ background: none; color: var(--accent); font-weight: 600; }}
  footer {{ margin-top: 36px; border-top: 1px solid var(--rule); padding-top: 16px;
    color: var(--muted); font-size: 12.3px; }}
  @media (max-width: 900px) {{ .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }} .grid-2 {{ grid-template-columns: 1fr; }} }}
  @media print {{ .kpi-grid {{ grid-template-columns: repeat(4, 1fr); }} }}
</style>
</head>
<body>
<div class="wrap">

  <header class="mast">
    <h1>{_esc(title)}</h1>
    <div class="sub">数据期间 <b>{period}</b>（{DAYS} 天） · 数据源 {_esc(source_name)} · 表 {_esc(snap.get("_table", ""))}（商品进销存日报，{ROWS:,} 行） · 生成于 {gen_at.strftime("%Y-%m-%d %H:%M")}</div>
    <div class="caliber">口径说明：销售额 / 毛利 / 折扣均为<b>全行净额</b>（含退货冲减行，与真值基线一致）；毛利率 = 毛利 ÷ 销售额；折扣率 = 折扣 ÷（销售额 + 折扣）；负毛利专题统计 ML &lt; 0 的行。全部数值由数据源 SQL 直查聚合，未作任何估计。</div>
  </header>

  <div class="kpi-grid">
    <div class="kpi"><div class="k">销售额（全期）</div><div class="v">¥{_f2(XSJE)}</div><div class="s">日均 ¥{_f2(day_avg)}</div></div>
    <div class="kpi"><div class="k">毛利（全期）</div><div class="v">¥{_f2(ML)}</div><div class="s">成本 ¥{_f2(XSCB)}</div></div>
    <div class="kpi"><div class="k">综合毛利率</div><div class="v">{MLR:.2f}%</div><div class="s">动销商品 {SPS:,} 个</div></div>
    <div class="kpi"><div class="k">销售数量</div><div class="v">{_f0(XSSL)}</div><div class="s">覆盖 {DAYS} 天</div></div>
    <div class="kpi"><div class="k">折扣金额</div><div class="v">¥{_f2(ZKJE)}</div><div class="s">另优惠金额 ¥{_f2(YHJE)}</div></div>
    <div class="kpi"><div class="k">综合折扣率</div><div class="v">{ZKR:.2f}%</div><div class="s">折扣 ÷（销售额+折扣）</div></div>
    <div class="kpi warn"><div class="k">负毛利金额（全期）</div><div class="v">¥{_f2(neg_ml_total)}</div><div class="s">负毛利行 {neg_rows_total:,} 行</div></div>
    <div class="kpi warn"><div class="k">负毛利天数</div><div class="v">{len(neg_days)} 天</div><div class="s">{" / ".join(d[0][5:] for d in neg_days) if neg_days else "无"}</div></div>
  </div>

  <h2 class="sec">一、经营日趋势</h2>
  <p class="sec-sub">{DAYS} 天销售额与毛利率走势。{f"<b>{len(neg_days)} 个负毛利日</b>需重点复盘；" if neg_days else ""}毛利率最低点 {float(worst_days[0][3]):.2f}%（{_esc(str(worst_days[0][0]))}）。</p>
  <figure class="chart-figure">
    <figcaption>日销售额 × 毛利率走势<span class="note">红色标注：毛利率最低的两个日期</span></figcaption>
    <div id="chart-daily" style="width:100%;min-height:400px"></div>
  </figure>

  <h2 class="sec">二、品类结构</h2>
  <p class="sec-sub">{_esc(fl1[0][0]) if fl1 else ""}贡献 {float(fl1[0][1]) / fl1_total * 100:.1f}% 销售额、毛利率 {float(fl1[0][3]):.2f}%；{f"毛利率最低为 {_esc(fl1_low[0])}（{float(fl1_low[3]):.2f}%）。" if fl1_low else ""}</p>
  <div class="grid-2">
    <figure class="chart-figure">
      <figcaption>一级品类销售额占比</figcaption>
      <div id="chart-fl1" style="width:100%;min-height:360px"></div>
    </figure>
    <figure class="chart-figure">
      <figcaption>一级品类毛利率对比<span class="note">低于 5% 标红</span></figcaption>
      <div id="chart-fl1-rate" style="width:100%;min-height:360px"></div>
    </figure>
  </div>
  <figure class="chart-figure">
    <figcaption>二级品类销售额 TOP12 × 毛利率<span class="note">红点为毛利率（右轴）</span></figcaption>
    <div id="chart-fl2" style="width:100%;min-height:460px"></div>
  </figure>
  <div class="table-wrap">
    <table>
      <thead><tr><th>#</th><th>品类（一级 / 二级）</th><th style="text-align:right">毛利额(元)</th><th style="text-align:right">销售额(元)</th><th style="text-align:right">毛利率</th></tr></thead>
      <tbody>{fl2_ml_rows()}</tbody>
    </table>
  </div>

  <h2 class="sec">三、商品榜</h2>
  <p class="sec-sub">{f"销售额 TOP1 {_esc(top1[0])}（{_f2(top1[2])} 元）毛利 {_f2(top1[3])} 元、毛利率 {float(top1[4]):.2f}%。" if top1 else ""}高销售是否转化为毛利，逐行核对。</p>
  <div class="table-wrap">
    <table>
      <thead><tr><th>#</th><th>商品</th><th>品类</th><th style="text-align:right">销售额(元)</th><th style="text-align:right">毛利(元)</th><th style="text-align:right">毛利率</th><th style="text-align:right">销量</th></tr></thead>
      <tbody>{top_sp_rows()}</tbody>
    </table>
  </div>

  <h2 class="sec">四、负毛利专题</h2>
  <p class="sec-sub">{neg_section_sub}</p>
  <figure class="chart-figure">
    <figcaption>负毛利金额 × 负毛利行数（按日）</figcaption>
    <div id="chart-neg" style="width:100%;min-height:400px"></div>
  </figure>
  <div class="table-wrap">
    <table>
      <thead><tr><th>#</th><th>商品</th><th>品类</th><th style="text-align:right">负毛利行数</th><th style="text-align:right">负毛利合计(元)</th><th style="text-align:right">负毛利行销售额(元)</th></tr></thead>
      <tbody>{neg_sp_rows()}</tbody>
    </table>
  </div>

  <h2 class="sec">五、折扣与星期节律</h2>
  <div class="grid-2">
    <figure class="chart-figure">
      <figcaption>一级品类折扣率{f"<span class='note'>{_esc(zk_top[0])} {float(zk_top[2]):.2f}% 最高</span>" if zk_top else ""}</figcaption>
      <div id="chart-zk" style="width:100%;min-height:320px"></div>
    </figure>
    <figure class="chart-figure">
      <figcaption>星期几销售 × 毛利{f"<span class='note'>{DOW_CN.get(str(dow_worst[0]), str(dow_worst[0]))} 毛利最低</span>" if dow_worst else ""}</figcaption>
      <div id="chart-dow" style="width:100%;min-height:320px"></div>
    </figure>
  </div>

  <h2 class="sec">六、供应商 TOP8</h2>
  <p class="sec-sub">{f"{_esc(sup_best[0])} 毛利 {_f2(sup_best[2])} 元为最优；" if sup_best else ""}{f"毛利为负供应商：{'、'.join(_esc(r[0]) for r in sup_neg[:3])}，需重谈条件。" if sup_neg else "TOP8 供应商毛利均为正。"}</p>
  <div class="table-wrap">
    <table>
      <thead><tr><th>#</th><th>供应商</th><th style="text-align:right">销售额(元)</th><th style="text-align:right">毛利(元)</th><th style="text-align:right">供应商品数</th></tr></thead>
      <tbody>{supplier_rows()}</tbody>
    </table>
  </div>

  <h2 class="sec">七、专家洞察与行动建议</h2>
  <div class="insight">
    <ol>
      {insights_html}
    </ol>
  </div>

  <footer>
    数据核对（锚点基线 as of {_esc(a_asof)}）：{anchor_badge} —— {anchor_line}。
    全部图表与表格数值由数据源（{_esc(source_name)} / {_esc(snap.get("_table", ""))}）SQL 直查聚合生成，可复算、无估计值。
  </footer>
</div>

<script>{_echarts_js()}</script>
<script>{charts_js}</script>
</body>
</html>
'''
    return html


def card_kpis(snap: dict[str, Any]) -> list[dict[str, str]]:
    """消息卡片 KPI 摘要（数值同样来自快照）。"""
    kpi = snap["kpi"][0]
    neg_ml_total = sum(float(r[2]) for r in snap.get("neg_daily") or [])
    return [
        {"label": "销售额", "value": f"¥{_f2(kpi[0])}"},
        {"label": "毛利", "value": f"¥{_f2(kpi[2])}"},
        {"label": "毛利率", "value": f"{float(kpi[3]):.2f}%"},
        {"label": "负毛利", "value": f"¥{_f2(neg_ml_total)}"},
    ]
