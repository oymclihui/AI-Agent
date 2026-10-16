"""Socratic questioning core: clarity gate, judge, engine.

S1 范围：核心判定与提问引擎 + 智能体配置（agents.metadata_.socratic_config）。
原则：懂则直答，惑则善问；判定失败一律静默降级直答，提问能力永不阻塞回答。
"""
from app.core.socratic.engine import socratic_precheck  # noqa: F401
