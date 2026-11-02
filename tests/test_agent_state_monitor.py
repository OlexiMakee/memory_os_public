"""Tests for AgentStateMonitor — adaptive tmux pane state detection."""

import json
import time
import pytest
from pathlib import Path

from memory_os.toolkit.agent_state_monitor import (
    AgentStateMonitor,
    DONE, ACTIVE, STUCK, RATE_LIMITED, DELEGATE,
)


@pytest.fixture
def root(tmp_path):
    (tmp_path / "agent_context" / "done").mkdir(parents=True)
    return tmp_path


def make_monitor(root, pane_content="", **kw):
    m = AgentStateMonitor(
        root=root, agent_id="claude", task_id="task_abc12345",
        tmux_target="claude", poll_interval=0.05, stuck_sec=0.2, max_wait=1.0, **kw
    )
    m._capture_pane = lambda: pane_content
    return m


def test_done_signal_wins(root):
    m = make_monitor(root)
    m.capture_baseline()
    done_file = root / "agent_context" / "done" / "task_abc12345.json"
    done_file.write_text(json.dumps({"message": "all good"}), encoding="utf-8")
    state, meta = m.poll_once()
    assert state == DONE
    assert meta["message"] == "all good"


def test_active_when_pane_changes(root):
    content = ["line1"]

    def pane():
        return "\n".join(content)

    m = make_monitor(root)
    m._capture_pane = pane
    m.capture_baseline()

    content.append("line2")
    state, _ = m.poll_once()
    assert state == ACTIVE


def test_stuck_after_threshold(root):
    m = make_monitor(root, pane_content="unchanged")
    m.capture_baseline()
    # Push last_change_ts into the past
    m._last_change_ts = time.time() - 1.0
    state, meta = m.poll_once()
    assert state == STUCK
    assert meta["agent"] == "claude"


def test_rate_limited_detected_in_delta(root):
    baseline = "old content"
    m = make_monitor(root, pane_content=baseline)
    m.capture_baseline()
    # New content with rate limit keyword — baseline line not repeated
    m._capture_pane = lambda: baseline + "\nquota exceeded, please try again"
    state, meta = m.poll_once()
    assert state == RATE_LIMITED
    assert "quota exceeded" in meta["keyword"]


def test_agy_rate_limited_detected_in_delta(root):
    baseline = "old content"
    m = AgentStateMonitor(
        root=root, agent_id="agy", task_id="task_abc12345",
        tmux_target="agy", poll_interval=0.05, stuck_sec=0.2, max_wait=1.0,
    )
    m._capture_pane = lambda: baseline
    m.capture_baseline()
    m._capture_pane = lambda: baseline + "\nusage limit reached, try again at 11:28 AM"
    state, meta = m.poll_once()
    assert state == RATE_LIMITED
    assert meta["agent"] == "agy"
    quota_state = json.loads((root / "agent_context" / "agents" / "quota_monitor_state.json").read_text(encoding="utf-8"))
    assert quota_state["agy"]["has_limit"] is True


def test_rate_limit_not_triggered_by_baseline(root):
    """If rate-limit keyword was already in pane at baseline, it must NOT trigger."""
    baseline = "system: quota exceeded (this is old text)"
    m = make_monitor(root, pane_content=baseline)
    m.capture_baseline()
    # Pane unchanged
    state, _ = m.poll_once()
    # Should not be RATE_LIMITED since it was in baseline
    assert state != RATE_LIMITED


def test_rate_limit_discussion_not_triggered_in_delta(root):
    baseline = "working"
    m = make_monitor(root, pane_content=baseline)
    m.capture_baseline()
    m._capture_pane = lambda: baseline + "\nrollout emits only weekly rate-limit window"

    state, _ = m.poll_once()

    assert state == ACTIVE
    assert not (root / "agent_context" / "agents" / "quota_monitor_state.json").exists()


def test_delegate_detected_in_delta(root):
    baseline = "working..."
    m = make_monitor(root, pane_content=baseline)
    m.capture_baseline()
    m._capture_pane = lambda: baseline + "\n[DELEGATE to codex]"
    state, meta = m.poll_once()
    assert state == DELEGATE
    assert meta["target"] == "codex"


def test_watch_returns_stuck_on_max_wait(root):
    m = AgentStateMonitor(
        root=root, agent_id="claude", task_id="task_abc12345",
        tmux_target="claude", poll_interval=0.05, stuck_sec=999.0, max_wait=0.1,
    )
    m._capture_pane = lambda: "static"
    m.capture_baseline()
    state, meta = m.watch()
    assert state == STUCK
    assert "max_wait" in meta.get("reason", "")


def test_watch_returns_done_fast(root):
    done_file = root / "agent_context" / "done" / "task_abc12345.json"
    done_file.write_text(json.dumps({"message": "success"}), encoding="utf-8")
    m = make_monitor(root)
    m.capture_baseline()
    state, meta = m.watch()
    assert state == DONE
    assert meta["message"] == "success"


def test_pane_unavailable_returns_active(root):
    m = make_monitor(root)
    m._capture_pane = lambda: None
    m.capture_baseline()
    state, meta = m.poll_once()
    assert state == ACTIVE
    assert meta.get("pane") == "unavailable"
