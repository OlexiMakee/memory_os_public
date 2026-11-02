import os
import json
import tomllib
from pathlib import Path
from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.agent_manager import AgentManagerTUI, get_agent_timer
from memory_os.toolkit.agent_limits import format_agent_limit_summary


def test_get_agent_timer():
    assert get_agent_timer(None) == "limit active"
    # Past reset time should be "reset pending"
    assert get_agent_timer("2020-01-01T00:00:00Z") == "reset pending"
    assert get_agent_timer(0) == "reset pending"
    # Future reset time check (cannot easily test exact time, but should not raise)
    assert "resets in" in get_agent_timer("2099-01-01T00:00:00Z") or get_agent_timer("2099-01-01T00:00:00Z") == "limit active"


def test_format_agent_limit_summary():
    spec = {"kind": "cli_agent", "cost_class": "limited"}
    state = {
        "windows": {
            "5h": {"used_percent": 17},
            "week": {"used_ratio": 0.42},
        }
    }
    assert format_agent_limit_summary(spec, {"status": "ok"}, state) == "5h:17% | Week:42%"
    assert format_agent_limit_summary(spec, {"status": "ok"}, {}) == "5h:?% | Week:?%"
    partial = {"usage": {"week": {"used_percent": 2}}, "usage_harvested_at": 1, "has_limit": False}
    assert format_agent_limit_summary(spec, {"status": "quota_exhausted"}, partial) == "5h:unknown | Week:2%"
    complete = dict(partial, usage_complete=True)
    assert format_agent_limit_summary(spec, {"status": "ok"}, complete) == "Week:2%"
    assert format_agent_limit_summary({"kind": "local_model", "cost_class": "cheap"}, {"status": "ok"}, {}) == "5h:n/a | Week:n/a"


def test_agent_manager_model_group_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no_codex"))
    (tmp_path / "agent_context" / "agents").mkdir(parents=True)
    (tmp_path / "memory_os.config.json").write_text(json.dumps({"tmux_session_name": "test_sess"}), encoding="utf-8")
    (tmp_path / "agent_context" / "agents" / "registry.toml").write_text(
        """
[agent.agy]
kind = "cli_agent"
command = ["agy"]
tmux_target = "test_sess:0.2"
""",
        encoding="utf-8",
    )
    (tmp_path / "agent_context" / "agents" / "health_cache.json").write_text(
        json.dumps({"agy": {"status": "quota_exhausted", "detail": "current model group exhausted"}}),
        encoding="utf-8",
    )
    (tmp_path / "agent_context" / "agents" / "quota_monitor_state.json").write_text(
        json.dumps({
            "agy": {
                "has_limit": True,
                "reset_at": "2099-01-01T00:00:00Z",
                "usage": {"week": {"used_percent": 100}, "5h": {"used_percent": 100, "status": "disabled", "available": False}},
                "model_groups": {
                    "gemini": {
                        "week": {"used_percent": 100},
                        "5h": {"used_percent": 100, "status": "disabled", "available": False},
                    },
                    "claude_gpt": {
                        "week": {"used_percent": 0, "available": True},
                        "5h": {"used_percent": 0, "available": True},
                    },
                },
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr("memory_os.toolkit.agent_console_scanner.AgentConsoleScanner.scan_once", lambda self: [])
    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.MultiplexerManager.list_panes", lambda self, session: [])

    agents = AgentManagerTUI(tmp_path).get_agents_status()

    assert agents[0]["limit_summary"] == "5h:0% | Week:0%"
    assert agents[0]["r_5h"] is None
    assert agents[0]["r_week"] is None
    assert "Gemini 5h:100% | Week:100%" in agents[0]["model_group_summary"]
    assert "Claude/GPT 5h:0% | Week:0%" in agents[0]["model_group_summary"]


def test_agent_manager_uses_available_model_group_when_preferred_is_exhausted(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no_codex"))
    (tmp_path / "agent_context" / "agents").mkdir(parents=True)
    (tmp_path / "memory_os.config.json").write_text(json.dumps({"tmux_session_name": "test_sess"}), encoding="utf-8")
    (tmp_path / "agent_context" / "agents" / "registry.toml").write_text(
        """
[agent.agy]
kind = "cli_agent"
command = ["agy"]
tmux_target = "test_sess:0.2"
""",
        encoding="utf-8",
    )
    (tmp_path / "agent_context" / "agents" / "health_cache.json").write_text(
        json.dumps({"agy": {"status": "ok", "detail": "Binary executable and responsive"}}),
        encoding="utf-8",
    )
    (tmp_path / "agent_context" / "agents" / "quota_monitor_state.json").write_text(
        json.dumps({
            "agy": {
                "has_limit": False,
                "usage": {
                    "week": {"used_percent": 0},
                },
                "active_model_group": "gemini",
                "model_groups": {
                    "gemini": {
                        "week": {"used_percent": 100, "resets_note": "Refreshes in 85h 56m"},
                        "5h": {"used_percent": 100, "status": "disabled", "available": False},
                    },
                    "claude_gpt": {
                        "week": {"used_percent": 10, "resets_note": "90% remaining · Refreshes in 167h 35m"},
                        "5h": {"used_percent": 30, "resets_note": "70% remaining · Refreshes in 4h 35m"},
                    },
                },
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr("memory_os.toolkit.agent_console_scanner.AgentConsoleScanner.scan_once", lambda self: [])
    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.MultiplexerManager.list_panes", lambda self, session: [])

    agents = AgentManagerTUI(tmp_path).get_agents_status()

    assert agents[0]["id"] == "agy"
    assert agents[0]["limit_summary"] == "5h:30% | Week:10%"
    assert agents[0]["r_5h"] in {"resets in 4h 34m", "resets in 4h 35m"}
    assert agents[0]["r_week"] in {"resets in 167h 34m", "resets in 167h 35m"}


def test_agent_manager_tui_status(tmp_path, monkeypatch):
    # Isolate from the real ~/.codex rollout harvest
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no_codex"))
    # Setup test workspace structure
    (tmp_path / "agent_context" / "agents").mkdir(parents=True)
    (tmp_path / "memory_os.config.json").write_text(json.dumps({"tmux_session_name": "test_sess"}), encoding="utf-8")
    
    registry_toml = """
[agent.claude]
kind = "cli_agent"
command = ["claude"]
tmux_target = "test_sess:0.0"

[agent.codex]
kind = "cli_agent"
command = ["codex"]
tmux_target = "test_sess:0.1"
"""
    (tmp_path / "agent_context" / "agents" / "registry.toml").write_text(registry_toml, encoding="utf-8")
    
    # Mock health cache
    health_cache = {
        "claude": {"status": "quota_exhausted", "detail": "Tmux pane rate limited", "ts": "2026-07-01T12:00:00Z"},
        "codex": {"status": "ok", "detail": "responsive", "ts": "2026-07-01T12:00:00Z"}
    }
    (tmp_path / "agent_context" / "agents" / "health_cache.json").write_text(json.dumps(health_cache), encoding="utf-8")

    # Mock quota state
    quota_state = {
        "claude": {"has_limit": True, "reset_at": "2026-07-01T20:00:00Z", "limits": {"5h": {"used_percent": 100}, "week": {"used_percent": 62}}},
        "codex": {"has_limit": False, "reset_at": "2099-01-01T00:00:00Z", "usage": {"5h": 23, "week": 41}}
    }
    (tmp_path / "agent_context" / "agents" / "quota_monitor_state.json").write_text(json.dumps(quota_state), encoding="utf-8")

    # Mock tmux resolution
    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.MultiplexerManager.resolve_pane_target", lambda self, agent_id: "%7" if agent_id == "claude" else "offline")

    tui = AgentManagerTUI(tmp_path)
    agents = tui.get_agents_status()

    # Sort by id
    agents = sorted(agents, key=lambda a: a["id"])
    assert len(agents) == 2
    assert agents[0]["id"] == "claude"
    assert agents[0]["is_active"] is True
    assert agents[0]["status"] == "quota_exhausted"
    assert agents[0]["limit_summary"] == "5h:100% | Week:62%"
    
    assert agents[1]["id"] == "codex"
    assert agents[1]["is_active"] is False
    assert agents[1]["status"] == "ok"
    assert agents[1]["limit_summary"] == "5h:23% | Week:41%"
    assert agents[1]["r_5h"] is None


def test_agent_manager_prefers_runtime_health_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no_codex"))
    (tmp_path / "agent_context" / "agents").mkdir(parents=True)
    (tmp_path / "memory_os.config.json").write_text(json.dumps({"tmux_session_name": "test_sess"}), encoding="utf-8")
    (tmp_path / "agent_context" / "agents" / "registry.toml").write_text(
        """
[agent.agy]
kind = "cli_agent"
command = ["agy"]
tmux_target = "test_sess:0.2"
""",
        encoding="utf-8",
    )
    (tmp_path / "agent_context" / "agents" / "health_cache.json").write_text(
        json.dumps({"agy": {"status": "ok", "detail": "responsive"}}),
        encoding="utf-8",
    )
    (tmp_path / "agent_context" / "agents" / "runtime_health.json").write_text(
        json.dumps({"agents": {"agy": {"is_active": True, "target_pane": "3"}}}),
        encoding="utf-8",
    )

    monkeypatch.setattr("memory_os.toolkit.agent_console_scanner.AgentConsoleScanner.scan_once", lambda self: [])
    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.MultiplexerManager.list_panes", lambda self, session: [])

    agents = AgentManagerTUI(tmp_path).get_agents_status()
    assert agents[0]["id"] == "agy"
    assert agents[0]["is_active"] is True
    assert agents[0]["target_pane"] == "3"


def test_agent_manager_runtime_controls_delegate_to_runtime_control(tmp_path, monkeypatch):
    (tmp_path / "memory_os.config.json").write_text(json.dumps({"tmux_session_name": "test_sess"}), encoding="utf-8")
    calls = []

    class FakeRuntimeControl:
        def __init__(self, root, config=None):
            self.root = root
            self.config = config

        def restart_all(self, **kwargs):
            calls.append(("restart", kwargs))
            return {"action": "restart", "ok": True, "steps": []}

        def shutdown_all(self, **kwargs):
            calls.append(("shutdown", kwargs))
            return {"action": "shutdown", "ok": True, "steps": []}

    monkeypatch.setattr("memory_os.toolkit.agent_manager.RuntimeControl", FakeRuntimeControl)

    tui = AgentManagerTUI(tmp_path)
    assert tui.restart_all(force=True, detach_workspace=False)["ok"] is True
    assert tui.shutdown_all(force=True)["ok"] is True
    assert calls == [
        ("restart", {"force": True, "detach_workspace": False, "workspace_only": False}),
        ("shutdown", {"force": True, "workspace_only": False}),
    ]


def test_agent_manager_resets_timer_for_non_limited(tmp_path, monkeypatch):
    # Setup test workspace structure
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no_codex"))
    (tmp_path / "agent_context" / "agents").mkdir(parents=True)
    (tmp_path / "memory_os.config.json").write_text(json.dumps({"tmux_session_name": "test_sess"}), encoding="utf-8")
    
    (tmp_path / "agent_context" / "agents" / "registry.toml").write_text("""
[agent.claude]
kind = "cli_agent"
command = ["claude"]
tmux_target = "test_sess:0.0"
""", encoding="utf-8")
    
    (tmp_path / "agent_context" / "agents" / "health_cache.json").write_text(json.dumps({
        "claude": {"status": "ok", "detail": "responsive"}
    }), encoding="utf-8")

    # In quota_monitor_state, has_limit is False, but resets_note is set in usage
    quota_state = {
        "claude": {
            "has_limit": False,
            "usage": {
                "week": {
                    "used_percent": 91,
                    "resets_note": "Current week · Resets in 22h 50m"
                }
            }
        }
    }
    (tmp_path / "agent_context" / "agents" / "quota_monitor_state.json").write_text(json.dumps(quota_state), encoding="utf-8")
    monkeypatch.setattr("memory_os.toolkit.agent_console_scanner.AgentConsoleScanner.scan_once", lambda self: [])
    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.MultiplexerManager.list_panes", lambda self, session: [])

    tui = AgentManagerTUI(tmp_path)
    agents = tui.get_agents_status()
    assert agents[0]["id"] == "claude"
    assert agents[0]["limit_str"] != ""
    assert "resets in" in agents[0]["limit_str"]


def test_agent_manager_launch_and_kill_tmux(tmp_path, monkeypatch):
    tui = AgentManagerTUI(tmp_path)
    tui.tmux.runtime = "tmux"
    tui.tmux.session_name = "test_sess"
    
    calls = []
    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return type("Result", (), {"stdout": "%4", "stderr": "", "returncode": 0})()
    monkeypatch.setattr("subprocess.run", fake_run)
    
    # Launch
    ok, msg = tui.launch_agent({"id": "lite"})
    assert ok is True
    assert "Launched in pane %4" in msg
    assert any("tmux" in c and "split-window" in c for c in calls)
    
    # Kill
    monkeypatch.setattr(tui.tmux, "resolve_pane_target", lambda agent_id: "%4")
    ok, msg = tui.kill_agent_pane({"id": "lite"})
    assert ok is True
    assert "Pane closed successfully" in msg
    assert any("tmux" in c and "kill-pane" in c for c in calls)


def test_agent_manager_launch_and_kill_zellij(tmp_path, monkeypatch):
    tui = AgentManagerTUI(tmp_path)
    tui.tmux.runtime = "zellij"
    tui.tmux.session_name = "test_sess"
    
    calls = []
    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return type("Result", (), {"stdout": "", "stderr": "", "returncode": 0})()
    monkeypatch.setattr("subprocess.run", fake_run)
    
    # Launch
    ok, msg = tui.launch_agent({"id": "lite"})
    assert ok is True
    assert "Launched in Zellij pane" in msg
    assert any("zellij" in c and "run" in c for c in calls)
    
    # Kill
    monkeypatch.setattr(tui.tmux, "resolve_pane_target", lambda agent_id: "terminal_4")
    ok, msg = tui.kill_agent_pane({"id": "lite"})
    assert ok is True
    assert "Zellij pane closed successfully" in msg
    assert any("zellij" in c and "focus-pane-id" in c for c in calls)
    assert any("zellij" in c and "close-pane" in c for c in calls)
