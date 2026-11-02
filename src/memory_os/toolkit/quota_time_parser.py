"""Pure parsing of provider quota reset timestamps."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional


_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def _hour_24(hour: int, ampm: str = "") -> int:
    marker = ampm.upper()
    if marker == "PM" and hour < 12:
        return hour + 12
    if marker == "AM" and hour == 12:
        return 0
    return hour


def _roll_distant_past_year(target: datetime, now: datetime, explicit_year: bool) -> datetime:
    if not explicit_year and target < now and (now - target) > timedelta(days=180):
        return target.replace(year=target.year + 1)
    return target


def parse_reset_timestamp(text: str, now: datetime) -> Optional[float]:
    """Return an epoch reset timestamp parsed relative to an aware UTC instant."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)

    match = re.search(
        r"(?:again at|resets)\s+([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?\s+(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?",
        text,
    )
    if match:
        month = _MONTHS.get(match.group(1)[:3].title())
        if month:
            year = int(match.group(3)) if match.group(3) else now.year
            try:
                target = datetime(
                    year,
                    month,
                    int(match.group(2)),
                    _hour_24(int(match.group(4)), match.group(6) or ""),
                    int(match.group(5)),
                    tzinfo=timezone.utc,
                )
            except ValueError:
                target = None
            if target is not None:
                return _roll_distant_past_year(target, now, bool(match.group(3))).timestamp()

    match = re.search(
        r"(?:again at|resets)\s+(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?",
        text,
        re.IGNORECASE,
    )
    if match:
        target = now.replace(
            hour=_hour_24(int(match.group(1)), match.group(3) or ""),
            minute=int(match.group(2)),
            second=0,
            microsecond=0,
        )
        if target < now:
            target += timedelta(days=1)
        return target.timestamp()

    match = re.search(
        r"resets\s+([A-Za-z]+)\s+(\d+),\s+(\d+)(?::(\d{2}))?\s*(am|pm)?",
        text,
        re.IGNORECASE,
    )
    if match:
        month = _MONTHS.get(match.group(1)[:3].title(), 1)
        target = datetime(
            now.year,
            month,
            int(match.group(2)),
            _hour_24(int(match.group(3)), match.group(5) or ""),
            int(match.group(4) or 0),
            tzinfo=timezone.utc,
        )
        return _roll_distant_past_year(target, now, explicit_year=False).timestamp()

    duration_match = re.search(
        r"(?:resets in|again in|refreshes in)\s+([0-9a-zA-Z\s,]+)",
        text,
        re.IGNORECASE,
    )
    if duration_match:
        duration = duration_match.group(1)
        hours_match = re.search(r"(\d+)\s*(?:h|hr|hour)", duration, re.IGNORECASE)
        minutes_match = re.search(r"(\d+)\s*(?:m|min|minute)", duration, re.IGNORECASE)
        hours = int(hours_match.group(1)) if hours_match else 0
        minutes = int(minutes_match.group(1)) if minutes_match else 0
        if hours or minutes:
            return now.timestamp() + hours * 3600 + minutes * 60

    return None
