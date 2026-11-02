"""Unit tests for the AgentQuotaMonitor."""

import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from memory_os.toolkit.quota_monitor import AgentQuotaMonitor
from memory_os.toolkit.quota_time_parser import parse_reset_timestamp


def test_parse_reset_timestamp_is_deterministic():
    now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    assert parse_reset_timestamp("resets in 4h 15m", now) == now.timestamp() + 15300
    assert parse_reset_timestamp("no quota reset here", now) is None

def test_parse_reset_time():
    monitor = AgentQuotaMonitor(Path("."))
    
    # Test Case 1: "try again at 11:28 AM"
    reset_val = monitor.parse_reset_time("■ You've hit your usage limit. try again at 11:28 AM.")
    assert reset_val is not None
    
    # Test Case 2: "resets Jul 3, 1am (UTC)"
    reset_val = monitor.parse_reset_time("resets Jul 3, 1am (UTC)")
    assert reset_val is not None
    
    # Test Case 3: "resets in 4h 15m"
    now = time.time()
    reset_val = monitor.parse_reset_time("resets in 4h 15m")
    assert reset_val is not None
    assert reset_val > now
    
    # Test Case 4: "again in 1 hour and 15 minutes"
    reset_val = monitor.parse_reset_time("again in 1 hour and 15 minutes")
    assert reset_val is not None
    assert reset_val > now

    # Test Case 5: "again in 45m"
    reset_val = monitor.parse_reset_time("again in 45m")
    assert reset_val is not None
    assert reset_val > now

    # Test Case 6: full date+time — codex weekly limit banner
    from datetime import datetime, timezone
    reset_val = monitor.parse_reset_time(
        "You've hit your usage limit. Upgrade to Pro or try again at Jul 8th, 2026 3:24 PM."
    )
    assert reset_val == datetime(2026, 7, 8, 15, 24, tzinfo=timezone.utc).timestamp()


def test_parse_reset_time_does_not_roll_recent_past_date_to_next_year(monkeypatch, tmp_path):
    import memory_os.toolkit.quota_monitor as quota_monitor
    from datetime import datetime, timezone

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 13, 12, 0, tzinfo=tz or timezone.utc)

    monkeypatch.setattr(quota_monitor, "datetime", FrozenDateTime)
    monitor = AgentQuotaMonitor(tmp_path)

    reset_val = monitor.parse_reset_time("Current week · Resets Jul 10, 12:59am (UTC)")

    assert reset_val == FrozenDateTime(2026, 7, 10, 0, 59, tzinfo=timezone.utc).timestamp()

@patch("memory_os.toolkit.quota_monitor.AgentHealthProbe.check")
@patch("memory_os.toolkit.quota_monitor.AgentComm.send")
@patch("memory_os.toolkit.quota_monitor.TelegramAdapter.send_message")
def test_check_and_recover_flow(mock_send_telegram, mock_comm_send, mock_health_check, tmp_path):
    # Setup tmp config
    import json
    config_path = tmp_path / "memory_os.config.json"
    config_path.write_text(json.dumps({
        "version": "0.1",
        "memory_dir": "memory",
        "agent_panes": {"claude": 0}
    }), encoding="utf-8")
    
    # Mock registry
    with patch("memory_os.toolkit.quota_monitor.load_agent_registry") as mock_load_registry:
        mock_load_registry.return_value = {
            "agent": {
                "claude": {
                    "kind": "cli_agent",
                    "display_name": "Клод",
                    "command": ["claude"],
                }
            }
        }
        
        # Test Case 1: Active limit detection
        mock_health_check.return_value = {"status": "quota_exhausted"}
        with patch("memory_os.toolkit.multiplexer_manager.MultiplexerManager.capture_pane") as mock_capture:
            mock_capture.return_value = "resets in 5m"
            
            monitor = AgentQuotaMonitor(tmp_path)
            monitor.check_and_recover()
            
            # State file should track the limit
            assert monitor.state.get("claude", {}).get("has_limit") is True
            
        # Test Case 2: Recovery check (probe task execution)
        # If reset time arrived (or we force a check), it should send a task
        monitor.state["claude"]["reset_at"] = time.time() - 10
        monitor._save_state()
        
        with patch("subprocess.run") as mock_run:
            monitor.check_and_recover()
            assert "task_id" in monitor.state["claude"]
            mock_comm_send.assert_called_once()
            
        # Test Case 3: Recovery verification
        # When done file exists, it should mark OK and notify telegram
        task_id = monitor.state["claude"]["task_id"]
        done_dir = tmp_path / "agent_context" / "done"
        done_dir.mkdir(parents=True, exist_ok=True)
        (done_dir / f"{task_id}.json").write_text(json.dumps({"task_id": task_id}), encoding="utf-8")
        
        import os
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_CHAT_IDS": "12345"}):
            with patch("memory_os.toolkit.quota_monitor.AgentHealthProbe._load_cache") as mock_load_cache, \
                 patch("memory_os.toolkit.quota_monitor.AgentHealthProbe._save_cache") as mock_save_cache:
                mock_load_cache.return_value = {"claude": {"status": "quota_exhausted"}}
                
                monitor.check_and_recover()
                
                assert monitor.state.get("claude", {}).get("has_limit") is False
                mock_send_telegram.assert_called_once_with("12345", "✅ Ліміти Клод відновлено")


def _write_events(root, lines):
    events = root / "agent_context" / "task_events.jsonl"
    events.parent.mkdir(parents=True, exist_ok=True)
    events.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_last_agent_report_ts(tmp_path):
    import json
    (tmp_path / "memory_os.config.json").write_text(json.dumps({
        "version": "0.1", "memory_dir": "memory", "agent_panes": {"claude": 0}
    }), encoding="utf-8")
    _write_events(tmp_path, [
        json.dumps({"event": "comm.sent", "kind": "STATUS_REPORT", "sender": "codex",
                    "ts": "2026-07-05T10:00:00+00:00"}),
        json.dumps({"event": "comm.sent", "kind": "TASK_ASSIGN", "sender": "claude",
                    "ts": "2026-07-05T11:00:00+00:00"}),
        json.dumps({"event": "comm.failed", "kind": "STATUS_REPORT", "sender": "claude",
                    "ts": "2026-07-05T12:00:00+00:00"}),
        json.dumps({"event": "comm.sent", "kind": "STATUS_REPORT", "sender": "claude",
                    "ts": "2026-07-05T09:00:00+00:00"}),
    ])
    monitor = AgentQuotaMonitor(tmp_path)
    ts = monitor._last_agent_report_ts("claude")
    from datetime import datetime, timezone
    assert ts == datetime(2026, 7, 5, 9, 0, tzinfo=timezone.utc).timestamp()
    assert monitor._last_agent_report_ts("agy") is None


@patch("memory_os.toolkit.quota_monitor.AgentHealthProbe.check")
def test_authoritative_codex_refresh_survives_monitor_cycle(mock_health_check, tmp_path):
    import json
    (tmp_path / "memory_os.config.json").write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    state_file = tmp_path / "agent_context" / "agents" / "quota_monitor_state.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text(json.dumps({
        "codex": {"has_limit": True, "reset_at": time.time() + 600}
    }), encoding="utf-8")

    def refresh_health(*args, **kwargs):
        state_file.write_text(json.dumps({
            "codex": {
                "has_limit": False,
                "usage": {"week": {"used_percent": 8}},
                "usage_complete": True,
                "usage_source": "app_server",
                "usage_harvested_at": time.time(),
            }
        }), encoding="utf-8")
        return {"status": "quota_exhausted"}

    mock_health_check.side_effect = refresh_health
    with patch("memory_os.toolkit.quota_monitor.load_agent_registry") as mock_reg:
        mock_reg.return_value = {"agent": {"codex": {"kind": "cli_agent", "command": ["codex"]}}}
        monitor = AgentQuotaMonitor(tmp_path)
        monitor.check_and_recover()

    persisted = json.loads(state_file.read_text(encoding="utf-8"))["codex"]
    assert persisted["has_limit"] is False
    assert persisted["usage"] == {"week": {"used_percent": 8}}
    assert "reset_at" not in persisted


@patch("memory_os.toolkit.quota_monitor.AgentHealthProbe.check")
@patch("memory_os.toolkit.quota_monitor.TelegramAdapter.send_message")
def test_liveness_short_circuit_notifies_once(mock_send_telegram, mock_health_check, tmp_path):
    import json, os
    (tmp_path / "memory_os.config.json").write_text(json.dumps({
        "version": "0.1", "memory_dir": "memory", "agent_panes": {"claude": 0}
    }), encoding="utf-8")
    mock_health_check.return_value = {"status": "ok"}

    limit_seen = time.time() - 3600
    state_file = tmp_path / "agent_context" / "agents" / "quota_monitor_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({
        "claude": {"has_limit": True, "limit_seen_at": limit_seen}
    }), encoding="utf-8")

    from datetime import datetime, timezone
    report_ts = datetime.now(timezone.utc).isoformat()
    _write_events(tmp_path, [
        json.dumps({"event": "comm.sent", "kind": "STATUS_REPORT", "sender": "claude",
                    "ts": report_ts}),
    ])

    with patch("memory_os.toolkit.quota_monitor.load_agent_registry") as mock_reg, \
         patch.dict(os.environ, {"TELEGRAM_ALLOWED_CHAT_IDS": "12345"}):
        mock_reg.return_value = {
            "agent": {
                "claude": {
                    "kind": "cli_agent",
                    "display_name": "Claude Registry",
                    "command": ["claude"],
                }
            }
        }

        monitor = AgentQuotaMonitor(tmp_path)
        monitor.check_and_recover()
        assert monitor.state["claude"]["has_limit"] is False
        mock_send_telegram.assert_called_once_with("12345", "✅ Ліміти Claude Registry відновлено")

        # Harvester flips has_limit back on from a stale snapshot — no repeat notification
        monitor.state["claude"]["has_limit"] = True
        monitor._save_state()
        monitor.check_and_recover()
        assert monitor.state["claude"]["has_limit"] is False
        assert mock_send_telegram.call_count == 1


@patch("memory_os.toolkit.quota_monitor.AgentHealthProbe.check")
@patch("memory_os.toolkit.quota_monitor.AgentComm.send")
@patch("memory_os.toolkit.quota_monitor.TelegramAdapter.send_message")
def test_quota_ping_is_minimal(mock_send_telegram, mock_comm_send, mock_health_check, tmp_path):
    import json
    (tmp_path / "memory_os.config.json").write_text(json.dumps({
        "version": "0.1", "memory_dir": "memory", "agent_panes": {"claude": 0}
    }), encoding="utf-8")
    mock_health_check.return_value = {"status": "ok"}

    state_file = tmp_path / "agent_context" / "agents" / "quota_monitor_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({
        "claude": {"has_limit": True, "limit_seen_at": time.time() - 60,
                   "reset_at": time.time() - 10}
    }), encoding="utf-8")

    with patch("memory_os.toolkit.quota_monitor.load_agent_registry") as mock_reg:
        mock_reg.return_value = {"agent": {"claude": {"kind": "cli_agent", "command": ["claude"]}}}
        monitor = AgentQuotaMonitor(tmp_path)
        monitor.check_and_recover()

    mock_comm_send.assert_called_once()
    sent = mock_comm_send.call_args.kwargs
    task_id = monitor.state["claude"]["task_id"]
    assert "[QUOTA PING]" in sent["message"]
    assert f"--task-id {task_id}" in sent["message"]
    assert "NOTHING else" in sent["message"]
