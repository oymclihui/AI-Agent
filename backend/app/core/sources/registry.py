"""已知来源种类的轻量注册表（供只读巡检接口展示）。"""
from __future__ import annotations

SOURCE_KINDS: dict[str, str] = {
    "feishu": "飞书机器人消息",
    "dingtalk": "钉钉机器人消息",
    "schedule": "数字员工定时任务",
}


def source_label(kind: str) -> str:
    return SOURCE_KINDS.get(kind, kind)
