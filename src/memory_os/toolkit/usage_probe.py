"""Idle-gated /usage probe for CLI agents that never persist quota to disk.

Injects a slash command into the agent's own pane, parses the rendered
screen, closes it with Esc, and records percentages via
QuotaStore. Strictly gated: the pane must be idle, the
command must be known to exist for that CLI (typing an unknown command
gets autocompleted to a random menu item — verified live on agy), and
results are TTL-cached by the harvester layer.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# CLIs with verified usage commands
USAGE_COMMANDS = {"claude": "/usage", "agy": "/usage"}

_BUSY_MARKERS = ("working (", "esc to interrupt", "press ctrl+c again")
_PERCENT_RE = re.compile(r"(\d{1,3})\s*%\s*used", re.IGNORECASE)
_MODEL_GROUP_LABELS = {
    "gemini": "Gemini",
    "claude_gpt": "Claude/GPT",
}


def parse_usage_screen(text: str) -> Dict[str, Any]:
    """Extract {"5h": {...}, "week": {...}} from a rendered /usage screen."""
    # Pre-process text to join wrapped lines for "resets" or "refreshes"
    lines = text.splitlines()
    merged_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        low = line.lower()
        if "resets" in low or "refreshes in" in low:
            if i + 1 < len(lines):
                next_line = lines[i+1].strip()
                next_low = next_line.lower()
                if next_line and (
                    any(tz in next_low for tz in ("am", "pm", "utc", "europe", "kyiv", "gmt"))
                    or re.search(r"^\d+", next_line)
                ):
                    line = line.rstrip() + " " + next_line
                    i += 1
        merged_lines.append(line)
        i += 1
    text = "\n".join(merged_lines)

    low_text = text.lower()
    is_new_style = "gemini models" in low_text or "claude and gpt" in low_text

    if not is_new_style:
        # Old Claude-only parser
        usage: Dict[str, Any] = {}
        section: Optional[str] = None
        for line in text.splitlines():
            low = line.lower()
            if "current session" in low:
                section = "5h"
            elif "week" in low and "opus" in low:
                section = "week_opus"
            elif "week" in low:
                section = "week"
            m = _PERCENT_RE.search(line)
            if m and section:
                usage.setdefault(section, {})["used_percent"] = min(100, int(m.group(1)))
                continue
            if section and section in usage and "resets" in low:
                usage[section].setdefault("resets_note", " ".join(line.split()))
        return {k: v for k, v in usage.items() if k in ("5h", "week")}

    # New style parser
    result: Dict[str, Dict[str, Any]] = {"gemini": {}, "claude_gpt": {}}
    group: Optional[str] = None
    window: Optional[str] = None

    for line in text.splitlines():
        low = line.lower().strip()
        if not low:
            continue

        if "gemini models" in low:
            group = "gemini"
            continue
        elif "claude and gpt" in low:
            group = "claude_gpt"
            continue

        if low.startswith("weekly limit"):
            window = "week"
            continue
        elif low.startswith("five hour limit"):
            window = "5h"
            continue

        if group and window:
            # Check for % remaining
            m_rem = re.search(r"(\d+(?:\.\d+)?)\s*%\s*remaining", low)
            if m_rem:
                rem_val = float(m_rem.group(1))
                used_val = max(0, min(100, int(100 - rem_val)))
                result[group].setdefault(window, {})["used_percent"] = used_val

            # Check for % used (just in case)
            m_used = re.search(r"(\d+(?:\.\d+)?)\s*%\s*used", low)
            if m_used and "remaining" not in low:
                used_val = min(100, int(float(m_used.group(1))))
                result[group].setdefault(window, {})["used_percent"] = used_val

            # Check for numeric suffix from bar (e.g. "] 51.63")
            m_bar = re.search(r"\]\s*(\d+(?:\.\d+)?)(?:\s*%?)?$", low)
            if m_bar:
                val = float(m_bar.group(1))
                used_val = max(0, min(100, int(100 - val)))
                result[group].setdefault(window, {})["used_percent"] = used_val

            if "disabled: you have hit your weekly limit" in low:
                result[group].setdefault(window, {})["used_percent"] = 100
                result[group][window]["status"] = "disabled"
                result[group][window]["available"] = False
                result[group][window]["reason"] = " ".join(line.split())

            if "quota available" in low:
                result[group].setdefault(window, {}).setdefault("used_percent", 0)
                result[group][window]["status"] = "available"
                result[group][window]["available"] = True

            if "refreshes in" in low or "resets" in low:
                result[group].setdefault(window, {})["resets_note"] = " ".join(line.split())

    return {group: usage for group, usage in result.items() if usage}


def is_grouped_usage(parsed: Dict[str, Any]) -> bool:
    return any(key in parsed for key in _MODEL_GROUP_LABELS)


def _group_is_exhausted(group: Dict[str, Any]) -> bool:
    """True when ALL windows in a model group are exhausted or disabled."""
    windows = [v for v in group.values() if isinstance(v, dict)]
    if not windows:
        return False
    return all(_window_is_exhausted(w) for w in windows)


def _pick_active_group(preferred: str, groups: Dict[str, Any]) -> str:
    """Return preferred group unless it's exhausted and another group is available."""
    if preferred in groups and not _group_is_exhausted(groups[preferred]):
        return preferred
    for gid, gdata in groups.items():
        if gid != preferred and isinstance(gdata, dict) and not _group_is_exhausted(gdata):
            return gid
    return preferred


def split_agent_usage(agent_id: str, parsed: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if not is_grouped_usage(parsed):
        return parsed, {}

    groups = {
        key: value
        for key, value in parsed.items()
        if key in _MODEL_GROUP_LABELS and isinstance(value, dict) and value
    }
    preferred = "gemini" if agent_id == "agy" else "claude_gpt"
    active_group = _pick_active_group(preferred, groups)
    usage = groups.get(active_group) or next(iter(groups.values()), {})
    return usage, groups


def _window_is_exhausted(window: Dict[str, Any]) -> bool:
    if window.get("available") is False or window.get("status") == "disabled":
        return True
    try:
        return float(window.get("used_percent", 0)) >= 100
    except (TypeError, ValueError):
        return False


def persist_usage_state(root: Path, agent_id: str, parsed: Dict[str, Any]) -> Dict[str, Any]:
    from memory_os.toolkit.quota_store import QuotaStore
    usage, model_groups = split_agent_usage(agent_id, parsed)
    store = QuotaStore(root)
    state = store.load()

    entry = state.get(agent_id, {})
    entry["usage"] = usage
    if model_groups:
        entry["model_groups"] = model_groups
        preferred = "gemini" if agent_id == "agy" else "claude_gpt"
        entry["active_model_group"] = _pick_active_group(preferred, model_groups)
    else:
        entry.pop("model_groups", None)
        entry.pop("active_model_group", None)
    entry["usage_harvested_at"] = time.time()
    exhausted = any(_window_is_exhausted(w) for w in usage.values() if isinstance(w, dict))
    entry["has_limit"] = exhausted

    if exhausted:
        from memory_os.toolkit.quota_monitor import AgentQuotaMonitor

        monitor = AgentQuotaMonitor(root)
        reset_candidates = []
        for window in usage.values():
            if not isinstance(window, dict) or not _window_is_exhausted(window):
                continue
            note = window.get("resets_note") or window.get("reason")
            if note:
                parsed_reset = monitor.parse_reset_time(str(note))
                if parsed_reset:
                    reset_candidates.append(parsed_reset)
        if not reset_candidates and model_groups:
            for group_usage in model_groups.values():
                if not isinstance(group_usage, dict):
                    continue
                for window in group_usage.values():
                    if not isinstance(window, dict):
                        continue
                    note = window.get("resets_note") or window.get("reason")
                    if note:
                        parsed_reset = monitor.parse_reset_time(str(note))
                        if parsed_reset:
                            reset_candidates.append(parsed_reset)
        if reset_candidates:
            entry["reset_at"] = min(reset_candidates)
    else:
        entry.pop("reset_at", None)

    state[agent_id] = entry
    store.save(state)
    return usage


def pane_is_idle(pane_text: Optional[str]) -> bool:
    if not pane_text:
        return False
    lines = [line.strip() for line in pane_text.splitlines() if line.strip()]
    if not lines:
        return False

    tail = "\n".join(lines[-15:]).lower()
    if any(marker in tail for marker in _BUSY_MARKERS):
        return False

    # Check if any of the last few lines starts with the prompt character and has content,
    # meaning the user has typed something and is not idle.
    for line in reversed(lines[-3:]):
        stripped_line = line.strip()
        if stripped_line.startswith(">"):
            content = stripped_line[1:].strip()
            # If the user has typed anything after the prompt, they are actively entering text
            if content:
                return False

    return True


def probe_pane_usage(
    root: Path,
    agent_id: str,
    timeout: float = 8.0,
    poll_interval: float = 0.5,
) -> Optional[Dict[str, Any]]:
    """Run the agent's usage command in its pane and harvest percentages.

    Returns the usage dict on success, None when skipped (busy pane,
    unknown command) or when parsing found nothing."""
    command = USAGE_COMMANDS.get(agent_id)
    if not command:
        return None

    # Check if the user recently sent a message to the agent's inbox or generated an event (< 1.0s ago)
    # to avoid interrupting active prompt submission / command execution
    now = time.time()
    for path in [
        root / "agent_context" / "inbox" / f"{agent_id}.jsonl",
        root / "agent_context" / "task_events.jsonl",
    ]:
        if path.exists():
            try:
                mtime = path.stat().st_mtime
                if now - mtime < 1.0:
                    return None
            except OSError:
                pass

    from memory_os.toolkit.multiplexer_manager import MultiplexerManager

    mgr = MultiplexerManager(root)
    target = mgr.resolve_pane_target(agent_id)

    before = mgr.capture_pane(target, lines=40)
    if not pane_is_idle(before):
        return None

    mgr.send_keys(target, command, submit=True, unlock_buffers=False, delay_sec=0.6)

    usage: Dict[str, Any] = {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(poll_interval)
        screen = mgr.capture_pane(target, lines=60) or ""
        parsed = parse_usage_screen(screen)
        usage, _model_groups = split_agent_usage(agent_id, parsed)
            
        if usage:
            break

    # Close the usage screen regardless of parse outcome
    mgr.send_shortcut(target, "escape")

    if not usage:
        return None

    return persist_usage_state(root, agent_id, parsed)
