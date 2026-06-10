from langchain_core.tools import tool


@tool
async def fetch_mail(limit: int = 10, folder: str = "INBOX") -> str:
    """
    Fetch recent emails from the current user's corporate mailbox via IMAP.
    The user must configure mailbox email and password in Settings first.
    Args:
        limit: Number of recent messages (1-20, default 10)
        folder: IMAP folder name (default INBOX)
    """
    from app.core.auth.context import get_current_user_id
    from app.core.email.mailbox_service import fetch_user_mailbox

    user_id = get_current_user_id()
    if not user_id:
        return "Error: no user context. Run this tool from an authenticated agent session."

    limit = max(1, min(int(limit), 20))
    folder = (folder or "INBOX").strip() or "INBOX"

    try:
        messages = await fetch_user_mailbox(user_id, limit=limit, folder=folder)
    except Exception as exc:
        return f"Failed to fetch mail: {exc}"

    if not messages:
        return f"No messages found in folder '{folder}'."

    lines = [f"Recent {len(messages)} message(s) from {folder}:", ""]
    for i, msg in enumerate(messages, 1):
        lines.append(f"--- Mail {i} ---")
        lines.append(f"From: {msg.get('from', '')}")
        lines.append(f"Date: {msg.get('date', '')}")
        lines.append(f"Subject: {msg.get('subject', '')}")
        preview = (msg.get("body_preview") or "").strip()
        if preview:
            lines.append(f"Body: {preview[:800]}")
        lines.append("")
    return "\n".join(lines)


FetchMailTool = fetch_mail
