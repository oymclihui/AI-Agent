from app.core.email.imap_client import fetch_recent_messages
from app.core.email.smtp_client import send_email, smtp_configured

__all__ = ["fetch_recent_messages", "send_email", "smtp_configured"]
