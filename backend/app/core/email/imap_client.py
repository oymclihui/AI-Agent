"""Fetch mail via IMAP (user-provided mailbox password)."""
from __future__ import annotations

import email
import imaplib
from email.header import decode_header
from typing import Any


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for chunk, enc in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(str(chunk))
    return "".join(parts)


def fetch_recent_messages(
    *,
    host: str,
    port: int,
    use_ssl: bool,
    username: str,
    password: str,
    limit: int = 10,
    folder: str = "INBOX",
) -> list[dict[str, Any]]:
    if use_ssl:
        conn = imaplib.IMAP4_SSL(host, port)
    else:
        conn = imaplib.IMAP4(host, port)

    try:
        conn.login(username, password)
        status, _ = conn.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Cannot open folder: {folder}")

        status, data = conn.search(None, "ALL")
        if status != "OK":
            return []

        ids = data[0].split()
        recent_ids = ids[-limit:] if len(ids) > limit else ids
        messages: list[dict[str, Any]] = []

        for msg_id in reversed(recent_ids):
            status, msg_data = conn.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            if not isinstance(raw, (bytes, bytearray)):
                continue
            parsed = email.message_from_bytes(raw)
            subject = _decode_header_value(parsed.get("Subject"))
            sender = _decode_header_value(parsed.get("From"))
            date = parsed.get("Date") or ""
            body = _extract_plain_body(parsed)
            messages.append(
                {
                    "id": msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                    "from": sender,
                    "subject": subject,
                    "date": date,
                    "body_preview": body[:2000],
                }
            )
        return messages
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _extract_plain_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_content_disposition():
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html" and not part.get_content_disposition():
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")[:2000]
        return ""
    payload = msg.get_payload(decode=True)
    if not payload:
        return str(msg.get_payload() or "")
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")
