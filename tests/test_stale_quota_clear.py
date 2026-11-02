"""Tests for stale quota limit clearing."""

import json
import time
from pathlib import Path

import pytest


def test_clear_stale_limits_expired_reset_at(tmp_path: Path):
    """has_limit should be cleared when reset_at is in the past."""
    from memory_os.toolkit.quota_harvester import clear_stale_limits

    state_dir = tmp_path / "agent_context" / "agents"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "quota_monitor_state.json"
    state_file.write_text(json.dumps({
        "agy": {
            "has_limit": True,
            "reset_at": time.time() - 3600,
            "limit_seen_at": time.time() - 7200,
        }
    }))

    clear_stale_limits(tmp_path)

    result = json.loads(state_file.read_text())
    assert result["agy"]["has_limit"] is False
    assert "reset_at" not in result["agy"]


def test_clear_stale_limits_future_reset_at_untouched(tmp_path: Path):
    """has_limit should NOT be cleared when reset_at is in the future."""
    from memory_os.toolkit.quota_harvester import clear_stale_limits

    state_dir = tmp_path / "agent_context" / "agents"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "quota_monitor_state.json"
    future = time.time() + 7200
    state_file.write_text(json.dumps({
        "claude": {
            "has_limit": True,
            "reset_at": future,
            "limit_seen_at": time.time() - 100,
        }
    }))

    clear_stale_limits(tmp_path)

    result = json.loads(state_file.read_text())
    assert result["claude"]["has_limit"] is True


def test_clear_stale_limits_no_reset_at_old_seen(tmp_path: Path):
    """has_limit should be cleared when limit_seen_at is >6h old and no reset_at."""
    from memory_os.toolkit.quota_harvester import clear_stale_limits

    state_dir = tmp_path / "agent_context" / "agents"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "quota_monitor_state.json"
    state_file.write_text(json.dumps({
        "agy": {
            "has_limit": True,
            "limit_seen_at": time.time() - 25000,
        }
    }))

    clear_stale_limits(tmp_path)

    result = json.loads(state_file.read_text())
    assert result["agy"]["has_limit"] is False
