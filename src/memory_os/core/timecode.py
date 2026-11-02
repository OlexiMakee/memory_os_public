from __future__ import annotations

import os
from datetime import datetime, timezone, tzinfo
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def user_timezone(config: Optional[Any] = None) -> tzinfo:
    data = getattr(config, "data", {}) if config is not None else {}
    tz_name = (
        os.environ.get("MEMORY_OS_USER_TZ")
        or data.get("user_timezone")
        or data.get("timezone")
        or ""
    ).strip()
    if tz_name:
        if tz_name.upper() == "UTC":
            return timezone.utc
        try:
            return ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            pass
    return datetime.now().astimezone().tzinfo or timezone.utc


def now_local_iso(config: Optional[Any] = None) -> str:
    return datetime.now(user_timezone(config)).replace(microsecond=0).isoformat(timespec="seconds")


def parse_timecode(value: Any, assume_tz: tzinfo = timezone.utc) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.lower() == "fresh":
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=assume_tz)
    return parsed


def is_offset_aware(value: Any) -> bool:
    """True when the value is already an unambiguous ISO timestamp with offset.

    Offset-aware values (any zone, incl. +00:00) are canonical — rewriting
    them to another zone is the same instant and only creates churn against
    concurrent UTC writers."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def normalize_timecode(value: Any, target_tz: tzinfo, assume_tz: tzinfo = timezone.utc) -> Optional[str]:
    parsed = parse_timecode(value, assume_tz=assume_tz)
    if parsed is None:
        return None
    return parsed.astimezone(target_tz).replace(microsecond=0).isoformat(timespec="seconds")
