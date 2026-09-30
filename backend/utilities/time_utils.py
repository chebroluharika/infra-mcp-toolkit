"""
Time Utilities
==============

Common time formatting and date utilities used across the dashboard.
"""

from datetime import datetime, timedelta, timezone
from typing import Union


def format_relative_time(timestamp: Union[int, float, str]) -> str:
    """
    Format timestamp as relative time string.

    Args:
        timestamp: Unix timestamp (int/float) or ISO datetime string

    Returns:
        Relative time string (e.g., '2d ago', '3h ago', 'Just now')
    """
    try:
        if isinstance(timestamp, (int, float)):
            run_time = datetime.fromtimestamp(timestamp)
        else:
            run_time = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).replace(tzinfo=None)

        delta = datetime.now() - run_time

        if delta.days > 0:
            return f"{delta.days}d ago"
        if delta.seconds >= 3600:
            return f"{delta.seconds // 3600}h ago"
        if delta.seconds >= 60:
            return f"{delta.seconds // 60}m ago"
        return "Just now"
    except (ValueError, TypeError, OSError):
        return datetime.now().strftime("%H:%M")


def get_current_time_formatted(time_zone: str = "ALL") -> str:
    """
    Get current time formatted in IST and/or GMT.

    Args:
        time_zone: "IST", "GMT", or "ALL" for both

    Returns:
        Formatted time string
    """
    now_utc = datetime.now(timezone.utc)
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    now_ist = now_utc.astimezone(ist_tz)
    time_format = "%Y-%m-%d %I:%M:%S %p"
    gmt_time_str = f"{now_utc.strftime(time_format)} GMT"
    ist_time_str = f"{now_ist.strftime(time_format)} IST"

    if time_zone == "IST":
        return ist_time_str
    if time_zone == "GMT":
        return gmt_time_str
    return f"{ist_time_str} / {gmt_time_str}"
