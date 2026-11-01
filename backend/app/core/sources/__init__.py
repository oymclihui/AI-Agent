"""超级智能体 · 来源(Source)子系统 — Phase 1。

把「事件进入系统」标准化为不可变的 Trigger 并按 Thread 聚合，幂等落库，
作为后续 Eval / 工单(Ticket) 阶段的统一输入。详见 docs/超级智能体演进蓝图.md。
"""
from app.core.sources.base import IncomingTrigger
from app.core.sources.intake import record_trigger
from app.core.sources.registry import SOURCE_KINDS, source_label

__all__ = ["IncomingTrigger", "record_trigger", "SOURCE_KINDS", "source_label"]
