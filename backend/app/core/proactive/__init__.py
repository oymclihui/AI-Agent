"""主动工作引擎（蓝图阶段三）：规则命中 → observe 记录 / auto 推送。"""
from app.core.proactive.engine import start_proactive_engine, stop_proactive_engine

__all__ = ["start_proactive_engine", "stop_proactive_engine"]
