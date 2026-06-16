"""Preset group chat templates (agent IDs resolved at runtime)."""
from __future__ import annotations

GROUP_CHAT_TEMPLATES: list[dict] = [
    {
        "id": "contract-review",
        "name": {"zh": "合同审查三人组", "en": "Contract Review Panel"},
        "description": {
            "zh": "法务 + 财务 + 产品顾问，轮流审查合同条款并汇总共识。",
            "en": "Legal, finance, and product advisors review contract clauses in rounds.",
        },
        "orchestration": "round_robin",
        "max_rounds": 2,
        "auto_synthesize": True,
        "agent_slots": [
            {"label": {"zh": "法务专家", "en": "Legal"}, "role_hints": ["法务", "legal", "Legal"]},
            {"label": {"zh": "财务分析师", "en": "Finance"}, "role_hints": ["财务", "finance", "Finance"]},
            {"label": {"zh": "产品顾问", "en": "Product"}, "role_hints": ["产品", "product", "Product"]},
        ],
        "moderator_slot_index": 0,
        "sample_prompt": {
            "zh": "请审查这份采购合同，重点看付款条款、违约责任和知识产权归属。",
            "en": "Review this procurement contract: payment terms, liability, and IP ownership.",
        },
    },
    {
        "id": "data-analysis",
        "name": {"zh": "数据分析小组", "en": "Data Analysis Squad"},
        "description": {
            "zh": "指标解读 + 可视化建议 + 业务洞察，适合经营分析问题。",
            "en": "Metrics, visualization, and business insight for operational questions.",
        },
        "orchestration": "round_robin",
        "max_rounds": 2,
        "auto_synthesize": True,
        "agent_slots": [
            {"label": {"zh": "指标专家", "en": "Metrics"}, "role_hints": ["指标", "KPI", "metric", "数据"]},
            {"label": {"zh": "可视化分析", "en": "Visualization"}, "role_hints": ["可视化", "图表", "visual", "chart"]},
            {"label": {"zh": "业务解读", "en": "Business"}, "role_hints": ["业务", "经营", "business", "分析"]},
        ],
        "moderator_slot_index": 2,
        "sample_prompt": {
            "zh": "分析近 12 个月销售趋势，指出异常波动并给出改进建议。",
            "en": "Analyze 12-month sales trends, flag anomalies, and suggest improvements.",
        },
    },
    {
        "id": "debate-risk",
        "name": {"zh": "风险辩论组", "en": "Risk Debate Panel"},
        "description": {
            "zh": "正方 / 反方 / 裁判，适合方案取舍与风险评估。",
            "en": "Pro, con, and judge agents for decision and risk debates.",
        },
        "orchestration": "debate",
        "max_rounds": 1,
        "auto_synthesize": True,
        "agent_slots": [
            {"label": {"zh": "正方", "en": "Pro"}, "role_hints": ["正方", "pro", "支持"]},
            {"label": {"zh": "反方", "en": "Con"}, "role_hints": ["反方", "con", "反对"]},
            {"label": {"zh": "裁判", "en": "Judge"}, "role_hints": ["裁判", "judge", "仲裁", "主持"]},
        ],
        "moderator_slot_index": 2,
        "sample_prompt": {
            "zh": "是否应该将核心系统迁移到公有云？请从成本、安全、运维三方面辩论。",
            "en": "Should we migrate core systems to public cloud? Debate cost, security, and ops.",
        },
    },
]
