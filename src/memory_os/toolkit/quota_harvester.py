"""Deterministic quota harvesting — no LLM calls, no pane injection.

codex writes exact rate-limit snapshots (used_percent per 5h/week window)
into ~/.codex/sessions/**/rollout-*.jsonl on every turn; we parse the newest
one. claude/agy never persist percentages, so for them the only passive
source is limit mentions in pane output — recorded via record_limit_mention()
from AgentStateMonitor's delta scan.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

_WINDOW_NAMES = {300: "5h", 10080: "week"}
HARVEST_TTL_SEC = 60.0


from memory_os.toolkit.quota_store import QuotaStore


def find_latest_codex_rollout(codex_home: Optional[Path] = None) -> Optional[Path]:
    if codex_home is None:
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    sessions = codex_home / "sessions"
    if not sessions.exists():
        return None
    files = sorted(
        sessions.glob("*/*/*/rollout-*.jsonl"),
        # Sort by filename (contains ISO timestamp) not st_mtime: rollout files
        # are append-only so st_mtime reflects the last write, not file age,
        # causing old sessions to sort ahead of newer ones.
        key=lambda p: p.name,
        reverse=True,
    )
    return files[0] if files else None


def parse_codex_rate_limits(rollout: Path) -> Optional[Dict[str, Any]]:
    """Extract the last rate_limits snapshot from a codex rollout file."""
    try:
        lines = rollout.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if '"rate_limits"' not in line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = rec.get("payload", {})
        rl = payload.get("rate_limits")
        if not isinstance(rl, dict):
            continue
        usage: Dict[str, Any] = {}
        for slot in ("primary", "secondary"):
            window = rl.get(slot)
            if not isinstance(window, dict):
                continue
            name = _WINDOW_NAMES.get(window.get("window_minutes"))
            if name and window.get("used_percent") is not None:
                usage[name] = {
                    "used_percent": window["used_percent"],
                    "resets_at": window.get("resets_at"),
                }
        if usage:
            return {
                "usage": usage,
                "ts": rec.get("timestamp", ""),
                "complete": False,
                "source": "rollout",
            }
    return None


def parse_codex_app_server_rate_limits(result: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(result, dict):
        return None
    snapshots = result.get("rateLimitsByLimitId")
    snapshot = snapshots.get("codex") if isinstance(snapshots, dict) else None
    if not isinstance(snapshot, dict):
        snapshot = result.get("rateLimits")
    if not isinstance(snapshot, dict):
        return None

    usage: Dict[str, Any] = {}
    for slot in ("primary", "secondary"):
        window = snapshot.get(slot)
        if not isinstance(window, dict):
            continue
        name = _WINDOW_NAMES.get(window.get("windowDurationMins"))
        if name and window.get("usedPercent") is not None:
            usage[name] = {
                "used_percent": window["usedPercent"],
                "resets_at": window.get("resetsAt"),
            }
    return {
        "usage": usage,
        "ts": time.time(),
        "complete": True,
        "source": "app_server",
    }


def read_codex_rate_limits(timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    proc: Optional[subprocess.Popen[str]] = None
    try:
        proc = subprocess.Popen(
            ["codex", "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        if proc.stdin is None or proc.stdout is None:
            return None
        initialize = {
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "memory-os-quota-probe", "version": "0.1"},
                "capabilities": {"experimentalApi": True},
            },
        }
        proc.stdin.write(json.dumps(initialize) + "\n")
        proc.stdin.flush()
        deadline = time.monotonic() + timeout
        requested = False
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select([proc.stdout], [], [], remaining)
            if not ready:
                break
            line = proc.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == 1 and not requested:
                proc.stdin.write(json.dumps({"method": "initialized"}) + "\n")
                proc.stdin.write(json.dumps({
                    "id": 2,
                    "method": "account/rateLimits/read",
                    "params": None,
                }) + "\n")
                proc.stdin.flush()
                requested = True
            elif message.get("id") == 2:
                return parse_codex_app_server_rate_limits(message.get("result"))
    except (OSError, ValueError):
        return None
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.0)
    return None


def clear_stale_limits(root: Path) -> None:
    """Expire has_limit=True entries whose reset_at is in the past.

    Non-codex agents (claude/agy) get limit state via record_limit_mention()
    which never clears it — this function provides the clearing path.
    Fallback: if no reset_at but limit_seen_at is >6h old, clear anyway."""
    store = QuotaStore(root)
    state = store.load()
    now = time.time()
    dirty = False
    for agent_id, entry in list(state.items()):
        if not isinstance(entry, dict) or not entry.get("has_limit"):
            continue
        reset_at = entry.get("reset_at")
        if reset_at is not None:
            from memory_os.toolkit.agent_limits import coerce_reset_datetime
            reset_dt = coerce_reset_datetime(reset_at)
            if reset_dt is not None:
                from datetime import datetime, timezone
                if reset_dt.timestamp() <= now:
                    entry["has_limit"] = False
                    entry.pop("reset_at", None)
                    entry.pop("attempted_switch", None)
                    dirty = True
                    continue
        seen_at = entry.get("limit_seen_at")
        if seen_at and (now - float(seen_at)) > 6 * 3600:
            entry["has_limit"] = False
            entry.pop("reset_at", None)
            entry.pop("attempted_switch", None)
            dirty = True
    if dirty:
        store.save(state)


def refresh_quota_state(
    root: Path,
    ttl: float = HARVEST_TTL_SEC,
    codex_home: Optional[Path] = None,
) -> Dict[str, Any]:
    """Merge fresh codex usage into quota_monitor_state.json; TTL-throttled.

    Returns the (possibly refreshed) full quota state for all agents."""
    clear_stale_limits(root)
    store = QuotaStore(root)
    state = store.load()
    entry = state.get("codex", {})
    if time.time() - float(entry.get("usage_harvested_at", 0)) < ttl:
        return state

    harvest = read_codex_rate_limits()
    if harvest is None:
        rollout = find_latest_codex_rollout(codex_home)
        harvest = parse_codex_rate_limits(rollout) if rollout else None
    if harvest:
        entry["usage"] = harvest["usage"]
        entry["usage_harvested_at"] = time.time()
        entry["usage_complete"] = bool(harvest.get("complete"))
        entry["usage_source"] = str(harvest.get("source", "unknown"))
        week = harvest["usage"].get("week", {})
        five = harvest["usage"].get("5h", {})
        exhausted = any(
            float(w.get("used_percent", 0)) >= 100 for w in (five, week) if w
        )
        entry["has_limit"] = exhausted
        if exhausted:
            resets = [w.get("resets_at") for w in (five, week) if w.get("used_percent", 0) >= 100 and w.get("resets_at")]
            if resets:
                entry["reset_at"] = min(resets)
        else:
            entry.pop("reset_at", None)
            entry.pop("attempted_switch", None)
        state["codex"] = entry
        store.save(state)
    return state


def record_limit_mention(root: Path, agent_id: str, text: str) -> None:
    """Passive harvest for agents that never persist quota to disk (claude/agy):
    called when a rate-limit line appears in an agent's pane delta."""
    from memory_os.toolkit.quota_monitor import AgentQuotaMonitor

    reset_at = AgentQuotaMonitor(root).parse_reset_time(text)
    store = QuotaStore(root)
    state = store.load()
    entry = state.get(agent_id, {})
    entry["has_limit"] = True
    entry["limit_seen_at"] = time.time()
    if reset_at:
        entry["reset_at"] = reset_at
    state[agent_id] = entry
    store.save(state)
