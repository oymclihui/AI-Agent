"""企微授权准入（蓝图阶段三）：白名单 + 准入表 + off/observe/auto 三档。

每条入站消息先过 evaluate()：
- 白名单 → explicit（直接执行）
- 准入表按序匹配（chattype × mentioned × in_whitelist）→ explicit / inferred / ignore
- inferred 的处理看 accept_mode：
    auto    → 正常执行（Mandate 记 basis=inferred）
    observe → 不执行，只记录「本会做什么」（report.stage=observe，可评审）
    off     → 静默忽略

默认配置与改造前行为一致（所有人按 inferred + auto 正常应答），
管理员通过 SystemSetting「wecom_bot.policy」收紧：
{
  "version": 2,
  "accept_mode": "auto",
  "whitelist": ["zhangsan"],
  "rules": [
    {"chattype": "group",  "mentioned": false, "in_whitelist": false, "action": "ignore"},
    {"chattype": "group",  "mentioned": true,  "in_whitelist": false, "action": "inferred"},
    {"chattype": "single", "in_whitelist": false, "action": "inferred"}
  ]
}
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SystemSetting

logger = structlog.get_logger(__name__)

POLICY_KEY = "wecom_bot.policy"

# 与改造前行为一致的默认策略：任何人任何消息都应答（inferred + auto）
DEFAULT_POLICY: dict[str, Any] = {
    "version": 1,
    "accept_mode": "auto",
    "whitelist": [],
    "rules": [
        {"chattype": "group", "mentioned": False, "in_whitelist": False, "action": "ignore"},
        {"chattype": "group", "mentioned": True, "in_whitelist": False, "action": "inferred"},
        {"chattype": "single", "in_whitelist": False, "action": "inferred"},
    ],
}

_ACTIONS = {"explicit", "inferred", "ignore"}
_MODES = {"off", "observe", "auto"}


@dataclass
class Decision:
    action: str          # explicit / inferred / ignore
    basis: str           # whitelist / rule / default
    accept_mode: str     # off / observe / auto
    version: int
    reason: str = ""
    rule: dict[str, Any] = field(default_factory=dict)

    def mandate(self, scope: str = "data-ask") -> dict[str, Any]:
        """落库的 Mandate：准入依据 + Policy 版本 + 范围 + 判定时间。"""
        return {
            "basis": self.action,
            "via": self.basis,
            "policy_version": self.version,
            "accept_mode": self.accept_mode,
            "scope": scope,
            "decided_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }


def _normalize(raw: Any) -> dict[str, Any]:
    cfg = raw if isinstance(raw, dict) else {}
    policy = {
        "version": int(cfg.get("version") or DEFAULT_POLICY["version"]),
        "accept_mode": str(cfg.get("accept_mode") or "auto"),
        "whitelist": [str(u) for u in (cfg.get("whitelist") or []) if u],
        "rules": [r for r in (cfg.get("rules") or []) if isinstance(r, dict)],
    }
    if policy["accept_mode"] not in _MODES:
        policy["accept_mode"] = "auto"
    if not policy["rules"]:
        policy["rules"] = list(DEFAULT_POLICY["rules"])
    return policy


async def load_policy(db: AsyncSession) -> dict[str, Any]:
    try:
        row = await db.get(SystemSetting, POLICY_KEY)
        return _normalize(row.value if row else None)
    except Exception as exc:
        logger.warning("wecom_policy_load_failed", error=str(exc)[:200])
        return _normalize(None)


def _match(rule: dict[str, Any], *, chattype: str, mentioned: bool, in_whitelist: bool) -> bool:
    if "chattype" in rule and str(rule.get("chattype")) != chattype:
        return False
    if "mentioned" in rule and bool(rule.get("mentioned")) != mentioned:
        return False
    if "in_whitelist" in rule and bool(rule.get("in_whitelist")) != in_whitelist:
        return False
    return True


def evaluate(
    policy: dict[str, Any],
    *,
    userid: str,
    chattype: str,
    mentioned: bool,
) -> Decision:
    """对一条入站消息做准入判定（纯函数，便于测试）。"""
    version = int(policy.get("version") or 1)
    mode = str(policy.get("accept_mode") or "auto")
    in_whitelist = userid in set(policy.get("whitelist") or [])
    if in_whitelist:
        return Decision("explicit", "whitelist", mode, version, reason="白名单用户")
    for rule in policy.get("rules") or []:
        if _match(rule, chattype=chattype, mentioned=mentioned, in_whitelist=False):
            action = str(rule.get("action") or "")
            if action in _ACTIONS:
                return Decision(
                    action, "rule", mode, version,
                    reason=f"命中准入表（{chattype}{'/@' if mentioned else ''}→{action}）",
                    rule=rule,
                )
    return Decision("inferred", "default", mode, version, reason="未命中准入表，按 inferred 处理")


# ── 续作（蓝图阶段四）：同线程后续消息免评估直入原 Mandate，策略变更则 handback 重评估 ──
_SUBSCRIPTION_TTL_MIN = 30


async def _latest_mandate(db: AsyncSession, userid: str) -> tuple[str, dict[str, Any]] | None:
    """最近 30 分钟内同用户最近一条带 Mandate 的任务（同信道即同线程）。"""
    from sqlalchemy import select

    from app.db.models import TaskRecord

    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=_SUBSCRIPTION_TTL_MIN)
    rows = (
        await db.execute(
            select(TaskRecord.id, TaskRecord.report)
            .where(
                TaskRecord.user_id == userid,
                TaskRecord.channel == "wecom",
                TaskRecord.created_at >= since,
                TaskRecord.report.is_not(None),
            )
            .order_by(TaskRecord.created_at.desc())
            .limit(5)
        )
    ).all()
    for task_id, report in rows:
        mandate = (report or {}).get("mandate") if isinstance(report, dict) else None
        if isinstance(mandate, dict) and mandate.get("basis"):
            return str(task_id), mandate
    return None


async def decide(
    db: AsyncSession,
    *,
    userid: str,
    chattype: str,
    mentioned: bool,
) -> tuple[Decision, dict[str, Any], tuple[str, dict[str, Any]] | None]:
    """准入判定入口：加载 Policy → 同线程续作命中则免评估，否则重新评估。

    返回 (decision, policy, prev)。prev 为 (task_id, mandate)，命中续作时非空。
    续作不扩权：沿用原 action/档位；Policy 版本或 accept_mode 变了就 handback 重评估。
    """
    policy = await load_policy(db)
    prev = await _latest_mandate(db, userid)
    if prev:
        _, mandate = prev
        version = int(mandate.get("policy_version") or 0)
        mode = str(mandate.get("accept_mode") or "")
        basis = str(mandate.get("basis") or "")
        if (
            basis in _ACTIONS
            and version == int(policy.get("version") or 1)
            and mode == str(policy.get("accept_mode") or "auto")
        ):
            decision = Decision(
                basis, "subscription", mode, version,
                reason="同会话续作，沿用原 Mandate（免评估）",
            )
            return decision, policy, prev
    return evaluate(policy, userid=userid, chattype=chattype, mentioned=mentioned), policy, None
