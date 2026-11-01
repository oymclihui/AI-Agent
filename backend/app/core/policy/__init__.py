"""超级智能体 · 策略(Policy) + 准入(Gate) + 授权(Mandate) 子系统 — Phase 2。

在 Phase 1 的触发/线程之上，加入「谁能让智能体主动接单」的确定性授权层：
- Policy：带版本的接单规则 + 各来源允许名单/ bot 名单；
- Gate：确定性判定触发强度（explicit / inferred / not_admitted）；
- Mandate：对被接受的工作授予的授权记录。

模型研判(Assessment)与真正的执行留待 Phase 3。详见 docs/超级智能体演进蓝图.md。
"""
from app.core.policy.service import (
    ACCEPT_MODES,
    get_current_policy,
    get_policy_view,
    update_policy,
)
from app.core.policy.gate import evaluate_gate

__all__ = [
    "ACCEPT_MODES",
    "get_current_policy",
    "get_policy_view",
    "update_policy",
    "evaluate_gate",
]
