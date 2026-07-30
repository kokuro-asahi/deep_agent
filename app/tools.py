from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def get_current_time(timezone_name: str = "Asia/Shanghai") -> str:
    """Get the current time for an IANA timezone, such as Asia/Shanghai or UTC."""
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return f"Unknown timezone: {timezone_name}"
    return datetime.now(timezone).isoformat(timespec="seconds")


def get_agent_tools() -> list[Callable[..., Any]]:
    return [
        get_current_time,
    ]
