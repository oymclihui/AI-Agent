"""L0 规则快判：零 token 成本的前置清晰度判定。

风格对齐 app/core/data_ask/experience/clarify.py（纯函数 + 正则）。
返回 "clear" | "underspecified" | "unknown"；unknown 交给 L1 LLM 判定。

设计要点：指标词（销售/毛利等）单独出现不算具体信号——「看看销售情况怎么样」
这类模糊问题常含指标词；只有强信号（数字/日期/实体）或明确问句式（多少/最高）
才算 clear。
"""
from __future__ import annotations

import re

# 模糊请求动词/指代——命中即视为模糊意图
_VAGUE_INTENT = re.compile(
    r"(帮我|给我|请)?(看看|看一下|分析(下|一下)?|总结(下|一下)?|说说|讲讲|介绍下?|"
    r"优化建议|有什么(问题|建议|想法)|怎么样|如何|咋样|情况|搞一下|弄一下|处理一下)"
)
_VAGUE_OBJECT = re.compile(r"(数据|情况|问题|东西|内容|结果|趋势)$")

# 强具体信号：数字/日期/时间/带量词数值
_STRONG = re.compile(
    r"((19|20)\d{2}|\d{1,2}\s*月|\d{4}[-/.]\d{1,2}|第[一二三四1234]季度|Q[1-4]|"
    r"\d+(\.\d+)?\s*(万|亿|%|元|件|台|个))",
    re.IGNORECASE,
)
# 明确问句式：问量/极值/排序类问题意图明确
_QUERY_SHAPE = re.compile(r"(多少|总共|合计|占比|最大|最小|最高|最低|前\s*\d+|top\s*\d+)", re.IGNORECASE)
# 实体：具体对象（店名/组织/业务对象）
_ENTITY = re.compile(r"[\u4e00-\u9fa5]{2,8}(店|超市|分公司|部门|客户|门店)")
# 指标/业务词（弱信号：单独出现不足以判 clear）
_METRIC = re.compile(
    r"(销售|毛利|成本|利润|库存|销量|营收|转化|留存|同比|环比|排名|商品|产品|用户|报表)",
    re.IGNORECASE,
)
_EXPORT = re.compile(r"(导出|下载|生成|发给我|发一份)")


def rule_clarity(question: str) -> str:
    text = (question or "").strip()
    if not text:
        return "underspecified"
    strong = bool(_STRONG.search(text)) or bool(_QUERY_SHAPE.search(text))
    entity = bool(_ENTITY.search(text))
    metric = bool(_METRIC.search(text))
    vague = bool(_VAGUE_INTENT.search(text)) or bool(_VAGUE_OBJECT.search(text))

    if vague:
        # 模糊意图 + 明确实体/时间 → 交 L1 精判；否则直接欠明确
        if strong or (entity and metric):
            return "unknown"
        return "underspecified"
    if strong and not _EXPORT.search(text):
        return "clear"
    if entity and metric:
        return "clear"
    if metric and not entity:
        return "unknown"
    if len(text) <= 6:
        return "underspecified"
    return "unknown"
