"""Chat connector presets and context injection for connected data sources."""
from __future__ import annotations

from typing import Any

from langchain_core.messages import SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

CONNECTOR_CATALOG: dict[str, dict[str, Any]] = {
    "byd-mail": {
        "label_zh": "企业邮箱",
        "label_en": "Corporate Mail",
        "type": "imap",
        "imap_host": "imap.byd.com",
        "imap_port": 1993,
        "imap_use_ssl": True,
    },
    "wecom-mail": {
        "label_zh": "企微邮箱",
        "label_en": "WeCom Mail",
        "type": "imap",
        "imap_host": "imap.exmail.qq.com",
        "imap_port": 993,
        "imap_use_ssl": True,
    },
}


def connector_label(connector_id: str, lang: str = "zh") -> str:
    entry = CONNECTOR_CATALOG.get(connector_id) or {}
    return entry.get("label_zh" if lang == "zh" else "label_en") or connector_id


async def build_connector_messages(
    connector_id: str | None,
    *,
    user_id: str,
    db: AsyncSession | None = None,
    lang: str = "zh",
) -> list[SystemMessage]:
    if not connector_id or connector_id not in CONNECTOR_CATALOG:
        return []

    entry = CONNECTOR_CATALOG[connector_id]
    label = connector_label(connector_id, lang)
    messages: list[SystemMessage] = []

    if entry.get("type") == "imap":
        try:
            from app.core.email.mailbox_service import fetch_user_mailbox

            mails = await fetch_user_mailbox(user_id, limit=8, db=db)
            if mails:
                lines = [
                    f"[{label}] Recent mailbox messages (INBOX, up to {len(mails)}):",
                    "",
                ]
                for i, msg in enumerate(mails, 1):
                    lines.append(f"--- Mail {i} ---")
                    lines.append(f"From: {msg.get('from', '')}")
                    lines.append(f"Date: {msg.get('date', '')}")
                    lines.append(f"Subject: {msg.get('subject', '')}")
                    preview = (msg.get("body_preview") or "").strip()
                    if preview:
                        lines.append(f"Body: {preview[:600]}")
                    lines.append("")
                messages.append(SystemMessage(content="\n".join(lines)))
            else:
                messages.append(
                    SystemMessage(
                        content=f"[{label}] Mailbox connected but INBOX has no recent messages."
                    )
                )
        except Exception as exc:
            hint = (
                "请在聊天输入栏的连接器设置中填写邮箱与授权码/密码，"
                "或前往「设置 → 邮箱账户」完成配置。"
                if lang == "zh"
                else "Configure email and app password in the chat connector setup or Settings → Mailbox."
            )
            messages.append(
                SystemMessage(
                    content=(
                        f"[{label}] Mailbox not available: {exc}. {hint}"
                    )
                )
            )

    guide = (
        f"用户已启用「{label}」连接器。若问题涉及邮件，请基于上方邮箱上下文作答；"
        "若无邮件数据，请说明如何完成邮箱配置后再试。"
        if lang == "zh"
        else (
            f"The user enabled the **{label}** connector. "
            "Answer email-related questions using the mailbox context above; "
            "if none is available, explain how to configure the mailbox."
        )
    )
    messages.append(SystemMessage(content=guide))
    return messages
