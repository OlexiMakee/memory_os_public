"""Unit tests for AgentHealthProbe."""

import json
import time
import pytest
from pathlib import Path
from memory_os.toolkit.agent_health import AgentHealthProbe


def test_agent_health_probe_basic(tmp_path: Path):
    registry_dir = tmp_path / "agent_context" / "agents"
    registry_dir.mkdir(parents=True, exist_ok=True)
    registry_file = registry_dir / "registry.toml"
    registry_file.write_text(
        """
[agent.shell]
kind = "shell"
command = ["bash"]

[agent.missing_cli]
kind = "cli_agent"
command = ["non_existent_binary_12345"]
""",
        encoding="utf-8",
    )

    probe = AgentHealthProbe(tmp_path)
    results = probe.check_all(force=True)

    assert "shell" in results
    assert results["shell"]["status"] == "ok"
    assert "missing_cli" in results
    assert results["missing_cli"]["status"] == "missing_binary"


def test_agent_health_probe_caching(tmp_path: Path):
    registry_dir = tmp_path / "agent_context" / "agents"
    registry_dir.mkdir(parents=True, exist_ok=True)
    registry_file = registry_dir / "registry.toml"
    registry_file.write_text(
        """
[agent.shell]
kind = "shell"
command = ["bash"]
""",
        encoding="utf-8",
    )

    probe = AgentHealthProbe(tmp_path)
    res1 = probe.check("shell", ttl=60, force=True)
    assert res1["status"] == "ok"

    cache_file = tmp_path / "agent_context" / "agents" / "health_cache.json"
    assert cache_file.exists()

    res2 = probe.check("shell", ttl=60, force=False)
    assert res2["ts"] == res1["ts"]


def test_codex_usage_snapshot_invalidates_stale_limit_health(tmp_path: Path, monkeypatch):
    registry_dir = tmp_path / "agent_context" / "agents"
    registry_dir.mkdir(parents=True)
    (registry_dir / "registry.toml").write_text(
        '[agent.codex]\nkind = "cli_agent"\ncommand = ["bash"]\n',
        encoding="utf-8",
    )
    (registry_dir / "health_cache.json").write_text(json.dumps({
        "codex": {
            "status": "quota_exhausted",
            "detail": "stale pane match",
            "ts": time.time() - 10,
        }
    }), encoding="utf-8")
    codex_home = tmp_path / "codex_home"
    rollout_dir = codex_home / "sessions" / "2026" / "07" / "13"
    rollout_dir.mkdir(parents=True)
    (rollout_dir / "rollout-test.jsonl").write_text(json.dumps({
        "timestamp": "2026-07-13T16:00:00Z",
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "rate_limits": {
                "primary": {
                    "used_percent": 3.0,
                    "window_minutes": 10080,
                    "resets_at": time.time() + 3600,
                },
                "secondary": None,
            },
        },
    }), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    class FakeMultiplexer:
        def __init__(self, root):
            pass

        def resolve_pane_target(self, agent_id):
            return agent_id

        def list_panes(self, session_name):
            return []

        def capture_pane(self, target, lines=100, full_history=True):
            return 'Search "rate_limits" in the rollout file'

    monkeypatch.setattr(
        "memory_os.toolkit.multiplexer_manager.MultiplexerManager",
        FakeMultiplexer,
    )

    result = AgentHealthProbe(tmp_path).check("codex", ttl=60)

    assert result["status"] == "ok"
    assert result["console_info"]["limit_event"] is None
    quota = json.loads((registry_dir / "quota_monitor_state.json").read_text(encoding="utf-8"))
    assert quota["codex"]["has_limit"] is False
