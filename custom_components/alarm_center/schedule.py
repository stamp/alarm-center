"""Time window helpers for quiet hours.

Free of Home Assistant imports so the awkward part - a window that wraps
past midnight, which is the normal case for quiet hours - is unit tested.
"""

from __future__ import annotations

from datetime import time


def parse_hhmm(value: str | None, default: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    """Parse "HH:MM" into (hour, minute), falling back to ``default``."""
    if not value:
        return default
    parts = str(value).strip().split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return default
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return default
    return hour, minute


def _minutes(hour: int, minute: int) -> int:
    return hour * 60 + minute


def in_window(now: time, start: str | None, end: str | None) -> bool:
    """Whether ``now`` falls inside the window from ``start`` to ``end``.

    The window is inclusive of the start and exclusive of the end, and wraps
    past midnight when end <= start - so 22:00 to 07:00 is the night, not
    the fifteen hours between them. A window whose ends are equal is treated
    as empty rather than as the whole day, because "quiet from 08:00 to
    08:00" is far more likely to be a mistake than a request for permanent
    silence.
    """
    start_h, start_m = parse_hhmm(start, (0, 0))
    end_h, end_m = parse_hhmm(end, (0, 0))

    start_min = _minutes(start_h, start_m)
    end_min = _minutes(end_h, end_m)
    now_min = _minutes(now.hour, now.minute)

    if start_min == end_min:
        return False
    if start_min < end_min:
        return start_min <= now_min < end_min
    # Wraps past midnight.
    return now_min >= start_min or now_min < end_min
