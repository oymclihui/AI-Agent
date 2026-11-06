# 数据问答意图识别 (Data QA Intent)

Adapted from smart-qa-v2.0 intent engine. Use when the user asks about metrics, trends, rankings, attribution, forecasts, or BI-style questions.

## When to use

- User asks for KPI values, trends, comparisons, composition, rankings, anomalies, root causes, or forecasts
- User wants chart/KPI/table structured answers in chat
- Routing or scoping a data-analytics digital employee response

## Intent taxonomy (L1 / L2 / L3)

| Level | Intent | Trigger keywords (zh) |
|-------|--------|------------------------|
| L1 | single_metric | 是多少、有多少、多少钱、总额、当前、现在 |
| L1 | multi_metric | 和、以及、还有、同时、一起看 |
| L2 | trend_analysis | 趋势、变化、走势、波动、怎么样 |
| L2 | yoy_mom | 同比、环比、比上月、比去年、增长、下降 |
| L2 | composition | 占比、构成、比例、份额、分布 |
| L2 | dimension_compare | 各地区、各产品、分渠道、哪个最好、按 |
| L2 | ranking | TOP、排名、最高、最低、前五、前十 |
| L2 | prediction | 预计、预测、未来、下个月、明年 |
| L2 | anomaly | 异常、突增、突降、不正常、有问题 |
| L2 | attribution | 为什么、原因、归因、怎么导致 |
| L3 | drill_down | 详细看看、下钻、具体到、深入分析 |
| L1 | knowledge_query | 产品介绍、怎么用、技术架构、客户案例（无数据分析词时） |

**Rule:** If the query contains analysis words (分析、占比、对比、趋势、排名、销量), do **not** classify as knowledge_query.

## Entity extraction

**Metrics:** 销售额/营收、订单量、客单价、转化率、DAU/MAU、利润、成本、库存、复购率、坪效、翻台率、GMV、ROI

**Dimensions:** 地区/区域、产品/品类、渠道、用户/客户、门店、品牌

**Time:** 今年、去年、本月、上月、近N天/月、Q1-Q4、昨天

## Suggested visualization

| Intent | Prefer |
|--------|--------|
| single_metric | KPI card + optional sparkline |
| trend_analysis / prediction | line or area chart |
| composition | pie or stacked bar |
| dimension_compare / ranking | bar chart |
| attribution / anomaly | multi-chart + narrative |
| drill_down | bar/table drill path |

## Structured output protocol

When answering in chat, embed blocks the UI can parse (optional but recommended):

**Do not** output Python / Matplotlib / Pyecharts / ECharts code for charts — the chat UI renders charts directly from `[chart:{...}]`. Put the narrative in Markdown and the data in the chart block.

```
[kpi:{"label":"销售额","value":1250000,"prefix":"¥","trend":{"value":12.5,"direction":"up","label":"环比"}}]

[chart:{"type":"line","title":"2024年度销量趋势","showLabels":true,"data":[{"月份":"1月","销量":120},{"月份":"2月","销量":135}],"xKey":"月份","yKeys":[{"key":"销量","name":"销量(万元)"}]}]

[choices:查看详情|下钻分析|导出报告]

[choices-multiple:华东|华南|华北]

[actions:对比去年同期|分析原因|预测下月]

[switch:归因哥]
```

For line/area/bar charts, set `"showLabels":true` when the user should see values on each point (default UI behavior for ≤12 points). Use `"showLabels":false` only when there are many dense points.

Use Markdown tables when `[table:...]` is not needed. Keep JSON valid inside `[chart:{...}]` and `[kpi:{...}]`.

## Response style by intent

- **single_metric:** number first, then one-line context, then optional chart
- **attribution:** hypothesis → evidence by dimension → top 3 drivers → actions
- **prediction:** state assumptions, show forecast range, note uncertainty
- **vague query** (e.g. "看看数据"): ask one clarifying question with `[choices:...]`

## Employee routing hints (persona)

| Keywords | Suggested persona |
|----------|-------------------|
| 为什么、原因、归因、下降 | 归因分析 |
| 趋势、图表、占比、对比 | 可视化分析 |
| 是多少、指标、口径、KPI | 指标体系 |
| 周报、月报、经营 | 报表分析 |
| 预测、未来、预计 | 预测分析 |
| 异常、质量、有问题 | 数据质量 |
| 全面分析、故事、解读 | 叙事分析 |
| SQL、查询、字段 | 精准查询 |

## Web search gate (optional)

Score +0.3 for: 最新、行业报告、竞品、新闻、政策、实时行情  
Score -0.5 for: 销售额、订单、我们的、内部、SQL、数据库  
If score > 0.5 and no strong internal-data signal → suggest web_search tool; otherwise use knowledge base and tools only.

## Follow-up questions

After each answer, offer 2–4 short follow-ups matching intent (e.g. after trend → 对比去年同期、分析波动原因、预测下月).

## 案例

数字只示范版式。真实金额、门店、日期必须来自查询或算子结果，不要照抄案例里的数字。

### 案例 1：单指标

用户：西安广场店 2026年10月11日销售额是多少

- 意图：L1 `single_metric`
- 实体：指标=销售额，维度=门店「西安广场店」，时间=2026-10-11
- 图表：KPI 卡
- 回复：先给数字，再补一句口径，最后给 2–3 个追问

```
西安广场店 2026-10-11 销售额 222674.02 元。

[kpi:{"label":"销售额","value":222674.02,"prefix":"¥","trend":{"value":0,"direction":"flat","label":"2026-10-11"}}]

[choices:看毛利|看客流|对比上周同日]
```

### 案例 2：同比后接归因

用户：上周销售额为什么下降

- 意图：L2 `yoy_mom`，并进入 `attribution`。句中有「为什么」，不要判成 `knowledge_query`
- 图表：KPI + 门店条形图
- 回复：两期数字和降幅 → 拖累最大的 3 家门店 → 可执行动作

```
上周销售额 120.4 万，同比少 8.6 万（-6.7%）。下滑主要来自 3 家门店。

[kpi:{"label":"上周销售额","value":1204000,"prefix":"¥","trend":{"value":-6.7,"direction":"down","label":"同比"}}]

[chart:{"type":"bar","title":"下滑门店","showLabels":true,"data":[{"门店":"A店","差额":-32000},{"门店":"B店","差额":-21000},{"门店":"C店","差额":-15000}],"xKey":"门店","yKeys":[{"key":"差额","name":"同比差额(元)"}]}]

[actions:对比去年同期|看毛利是否同步下降|列出下滑门店]
```

### 案例 3：排名

用户：本月销售额前十的门店

- 意图：L2 `ranking`
- 实体：指标=销售额，维度=门店，时间=本月，N=10
- 图表：横向条形图，不要输出 Python 或 ECharts 代码

```
本月销售额前 10 的门店如下，第 1 名是西安广场店。

[chart:{"type":"bar","title":"本月门店销售额 TOP10","horizontal":true,"showLabels":true,"data":[{"门店":"西安广场店","销售额":186000},{"门店":"钟楼店","销售额":154000}],"xKey":"门店","yKeys":[{"key":"销售额","name":"销售额(元)"}]}]

[choices:只看下降的店|改看毛利排名|下钻到品类]
```

### 案例 4：问题太宽，只追问一次

用户：看看数据

- 意图：信息不足，不要直接编一张图
- 回复：用一组选项把范围收窄

```
想先看哪一块？

[choices:昨天销售额|本月趋势|门店排名]
```

### 案例 5：知识问答边界

用户：这个系统怎么用

- 意图：L1 `knowledge_query`（没有分析词）

用户：分析一下销量怎么用趋势看

- 意图：含「分析」「销量」「趋势」，按 `trend_analysis` 处理，不要判成知识问答
