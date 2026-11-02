"""Agent quota display helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional


LIMIT_STATUSES = {"quota_exhausted", "rate_limited"}
MODEL_GROUP_LABELS = {
    "gemini": "Gemini",
    "claude_gpt": "Claude/GPT",
}


def coerce_reset_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            if raw.replace(".", "", 1).isdigit():
                return datetime.fromtimestamp(float(raw), timezone.utc)
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def format_reset_timer(reset_at: Any, now: Optional[datetime] = None) -> str:
    reset_dt = coerce_reset_datetime(reset_at)
    if reset_dt is None:
        return "limit active"
    now_dt = now or datetime.now(timezone.utc)
    if reset_dt.tzinfo is None:
        reset_dt = reset_dt.replace(tzinfo=timezone.utc)
    delta = reset_dt - now_dt
    if delta.total_seconds() <= 0:
        return "reset pending"
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)
    return f"resets in {hours}h {minutes}m"


def format_agent_limit_summary(
    spec: Mapping[str, Any],
    health: Optional[Mapping[str, Any]] = None,
    state: Optional[Mapping[str, Any]] = None,
    now: Optional[datetime] = None,
) -> str:
    if not _should_show_meter(spec):
        return "5h:n/a | Week:n/a"

    health_map = health or {}
    state_map = state or {}
    five_hour = _window_percent("5h", state_map, health_map)
    week = _window_percent("week", state_map, health_map)
    if state_map.get("usage_complete") is True:
        windows = []
        if five_hour is not None:
            windows.append(f"5h:{five_hour}")
        if week is not None:
            windows.append(f"Week:{week}")
        return " | ".join(windows) if windows else "No active quota windows"

    usage = state_map.get("usage")
    if state_map.get("usage_harvested_at") and isinstance(usage, Mapping) and usage:
        missing_window = "unknown"
    else:
        missing_window = "?%"

    active_window = _infer_active_exhausted_window(health_map, state_map, now)
    if active_window == "5h" and five_hour is None:
        five_hour = "100%"
    elif active_window == "week" and week is None:
        week = "100%"

    return f"5h:{five_hour or missing_window} | Week:{week or missing_window}"


def format_model_group_limit_summary(state: Optional[Mapping[str, Any]] = None) -> str:
    state_map = state or {}
    groups = state_map.get("model_groups")
    if not isinstance(groups, Mapping):
        return ""

    parts = []
    for group_id in ("gemini", "claude_gpt"):
        group = groups.get(group_id)
        if not isinstance(group, Mapping):
            continue
        five_hour = _window_percent("5h", {"usage": group}) or "?%"
        week = _window_percent("week", {"usage": group}) or "?%"
        flags = []
        for window in ("5h", "week"):
            window_data = group.get(window)
            if not isinstance(window_data, Mapping):
                continue
            if window_data.get("available") is False or window_data.get("status") == "disabled":
                flags.append(f"{window} disabled")
            elif window_data.get("available") is True:
                flags.append(f"{window} available")
        suffix = f" ({', '.join(flags)})" if flags else ""
        parts.append(f"{MODEL_GROUP_LABELS[group_id]} 5h:{five_hour} | Week:{week}{suffix}")
    return "  •  ".join(parts)


def resolve_active_usage_state(
    agent_id: str,
    state: Optional[Mapping[str, Any]] = None,
) -> tuple[Mapping[str, Any], Optional[str]]:
    state_map = state or {}
    groups = state_map.get("model_groups")
    if not isinstance(groups, Mapping) or not groups:
        usage = state_map.get("usage")
        return (usage if isinstance(usage, Mapping) else {}), None

    preferred = state_map.get("active_model_group")
    if not isinstance(preferred, str) or preferred not in groups:
        preferred = "gemini" if agent_id == "agy" else "claude_gpt"
    active_group = preferred
    def _is_exhausted(group_state: Any) -> bool:
        if not isinstance(group_state, Mapping):
            return False
        windows = [v for v in group_state.values() if isinstance(v, Mapping)]
        if not windows:
            return False
        for window in windows:
            if window.get("available") is True or window.get("status") == "available":
                return False
            try:
                if float(window.get("used_percent", 0)) < 100:
                    return False
            except (TypeError, ValueError):
                return False
        return True
    if isinstance(groups, Mapping):
        if preferred in groups and not _is_exhausted(groups.get(preferred, {})):
            active_group = preferred
        else:
            for gid, gdata in groups.items():
                if gid != preferred and isinstance(gdata, Mapping) and not _is_exhausted(gdata):
                    active_group = gid
                    break
    active_usage = groups.get(active_group)
    if isinstance(active_usage, Mapping) and active_usage:
        return active_usage, active_group

    usage = state_map.get("usage")
    return (usage if isinstance(usage, Mapping) else {}), active_group


def agent_limit_active(
    health: Optional[Mapping[str, Any]] = None,
    state: Optional[Mapping[str, Any]] = None,
    now: Optional[datetime] = None,
) -> bool:
    return _infer_active_exhausted_window(health or {}, state or {}, now) is not None


def _should_show_meter(spec: Mapping[str, Any]) -> bool:
    if spec.get("kind") != "cli_agent":
        return False
    return spec.get("cost_class", "limited") not in {"zero", "cheap", "unlimited"}


def _infer_active_exhausted_window(
    health: Mapping[str, Any],
    state: Mapping[str, Any],
    now: Optional[datetime],
) -> Optional[str]:
    if state.get("has_limit") is False and state.get("usage_harvested_at"):
        return None
    status = str(health.get("status", ""))
    reset_dt = coerce_reset_datetime(state.get("reset_at"))
    now_dt = now or datetime.now(timezone.utc)
    if reset_dt is not None and reset_dt.tzinfo is None:
        reset_dt = reset_dt.replace(tzinfo=timezone.utc)

    state_limit_active = state.get("has_limit") is True and (reset_dt is None or reset_dt > now_dt)
    if status not in LIMIT_STATUSES and not state_limit_active:
        return None

    if reset_dt is None:
        return "5h"
    if (reset_dt - now_dt).total_seconds() > 6 * 3600:
        return "week"
    return "5h"


def _window_percent(window: str, *sources: Mapping[str, Any]) -> Optional[str]:
    for source in sources:
        value = _extract_window_value(window, source)
        percent = _coerce_percent(value)
        if percent is not None:
            return percent
    return None


def _extract_window_value(window: str, source: Mapping[str, Any]) -> Any:
    flat_keys = _flat_keys(window)
    for key in flat_keys:
        if key in source:
            return source[key]

    for container_key in ("windows", "limits", "usage", "quota", "limit_usage"):
        container = source.get(container_key)
        if not isinstance(container, Mapping):
            continue
        for key in _window_keys(window):
            if key not in container:
                continue
            value = container[key]
            if isinstance(value, Mapping):
                for percent_key in ("percent", "used_percent", "usage_percent", "pct", "used_pct"):
                    if percent_key in value:
                        return value[percent_key]
                for ratio_key in ("ratio", "used_ratio", "usage_ratio"):
                    if ratio_key in value:
                        return {"ratio": value[ratio_key]}
            return value
    return None


def _flat_keys(window: str) -> list[str]:
    if window == "5h":
        return [
            "5h_percent",
            "five_hour_percent",
            "five_hour_usage_percent",
            "usage_5h_percent",
            "quota_5h_percent",
        ]
    return [
        "week_percent",
        "weekly_percent",
        "weekly_usage_percent",
        "usage_week_percent",
        "quota_week_percent",
    ]


def _window_keys(window: str) -> list[str]:
    if window == "5h":
        return ["5h", "five_hour", "five-hour"]
    return ["week", "weekly"]


def _coerce_percent(value: Any) -> Optional[str]:
    ratio = False
    if isinstance(value, Mapping):
        if "ratio" not in value:
            return None
        value = value["ratio"]
        ratio = True

    if value is None:
        return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw or raw in {"?", "?%", "n/a", "N/A"}:
            return None
        if raw.endswith("%"):
            raw = raw[:-1].strip()
        try:
            numeric = float(raw)
        except ValueError:
            return None
    elif isinstance(value, (int, float)):
        numeric = float(value)
    else:
        return None

    if ratio:
        numeric *= 100
    numeric = min(100.0, max(0.0, numeric))
    if numeric.is_integer():
        return f"{int(numeric)}%"
    rounded = round(numeric, 1)
    if rounded.is_integer():
        return f"{int(rounded)}%"
    return f"{rounded}%"
