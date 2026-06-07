from langchain_core.tools import tool


@tool
def get_datetime(timezone: str = "UTC") -> str:
    """
    Returns the current date and time.
    Args:
        timezone: Timezone name (e.g. 'UTC', 'Asia/Shanghai', 'America/New_York').
    """
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        return now.strftime(f"%Y-%m-%d %H:%M:%S {timezone}")
    except Exception:
        now = datetime.utcnow()
        return now.strftime("%Y-%m-%d %H:%M:%S UTC")


DatetimeTool = get_datetime
