"""来源子系统的基础类型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class IncomingTrigger:
    """一个待记录的来源事件（归一化后的形态）。

    - source_kind: 来源种类，如 "feishu" / "dingtalk" / "schedule"
    - external_id: 来源侧的事件唯一标识，用于幂等去重（如飞书 message_id、定时任务的时间槽）
    - thread_external_key: 该事件所属线程的来源侧键（如 "feishu:chat:xxx"）
    - actor: 发起人在该来源下的身份标识（如飞书 open_id）
    - kind / thread_kind: 事件与线程的类别，供后续阶段路由
    - payload: 原始归一化内容（文本、会话 id 等）
    """

    source_kind: str
    external_id: str
    thread_external_key: str
    kind: str = "message"
    thread_kind: str = "message"
    actor: str | None = None
    title: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    # Phase 2 — 供 Gate 判定：是否 @ 了机器人 / 发起方是否是 bot
    addressed: bool = True
    is_bot: bool = False
