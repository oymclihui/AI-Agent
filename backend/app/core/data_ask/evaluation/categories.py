"""问题类目分类器：规则关键词匹配。

用于弱项分布（哪类问题老错）与主动学习缺口识别（哪类问题还没问过）。
纯确定性规则，不引入 LLM，保证可解释、可复现。
"""
from __future__ import annotations

CATEGORIES = [
    "aggregation", "trend", "comparison", "ranking",
    "ratio", "detail", "forecast", "ml",
]

CATEGORY_LABELS: dict[str, dict[str, str]] = {
    "aggregation": {"zh": "聚合汇总", "en": "Aggregation"},
    "trend":       {"zh": "趋势变化", "en": "Trend"},
    "comparison":  {"zh": "对比分析", "en": "Comparison"},
    "ranking":     {"zh": "排名 TopN", "en": "Ranking"},
    "ratio":       {"zh": "占比比率", "en": "Ratio"},
    "detail":      {"zh": "明细查询", "en": "Detail"},
    "forecast":    {"zh": "预测", "en": "Forecast"},
    "ml":          {"zh": "机器学习", "en": "ML"},
}

# 主动学习巡检的六大基础类目（forecast/ml 属进阶能力，不计入缺口）
CANONICAL_CATEGORIES = ["aggregation", "trend", "comparison", "ranking", "ratio", "detail"]

# 顺序即优先级：越特定的类目越先匹配
_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("forecast", ("预测", "forecast", "predict", "未来", "下月", "下周", "明年", "预估", "将会")),
    ("ml", ("聚类", "cluster", "分群", "异常检测", "anomaly", "outlier",
            "相关性", "correlation", "分类分析", "classify", "特征重要", "kmeans")),
    ("trend", ("趋势", "走势", "变化", "环比", "同比", "增长", "下滑", "下降",
              "按月", "按周", "按日", "按季", "每月", "每周", "每日", "trend", "近几")),
    ("ranking", ("排名", "排行", "前十", "前10", "前五", "前5", "前三", "前3",
                "top", "最高", "最低", "最多", "最少", "第几")),
    ("comparison", ("对比", "比较", "相比", "versus", " vs ", "差异", "哪个更", "哪家更", "和高")),
    ("ratio", ("占比", "比例", "分布", "构成", "份额", "百分比", "毛利率", "利润率",
              "周转率", "转化率", "比率", "ratio", "proportion")),
    ("detail", ("明细", "列表", "列出", "哪些", "详情", "清单", "每一", "各个", "分别")),
    ("aggregation", ("合计", "总数", "总额", "总和", "平均", "均值", "累计",
                    "多少", "几个", "sum", "avg", "total")),
]


def classify_question(question: str) -> str:
    """把自然语言问题归类到八大类目之一，默认 aggregation。"""
    q = (question or "").lower()
    for category, keywords in _RULES:
        if any(kw in q for kw in keywords):
            return category
    return "aggregation"


def category_label(category: str, lang: str = "zh") -> str:
    labels = CATEGORY_LABELS.get(category) or {}
    return labels.get(lang) or labels.get("zh") or category
