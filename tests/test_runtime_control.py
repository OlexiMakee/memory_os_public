import json
import subprocess

from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.runtime_control import RuntimeControl


def _write_config(root):
    (root / "memory_os.config.json").write_text(
        json.dumps({"tmux_session_name": "memory_os_workspace"}),
        encoding="utf-8",
    )


def test_shutdown_all_stops_daemons_and_workspace_sessions(tmp_path, monkeypatch):
    _write_config(tmp_path)
    session = MemoryOSConfig(str(tmp_path / "memory_os.config.json")).tmux_session_name
    calls = []

    monkeypatch.setattr("memory_os.toolkit.workspace_runtime.shutil.which", lambda binary: f"/usr/bin/{binary}")

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["tmux", "ls"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{session}\t1\t0\n", stderr="")
        if cmd == ["zellij", "list-sessions", "--no-formatting"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{session} [Created 1m ago]\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("memory_os.toolkit.runtime_control.subprocess.run", fake_run)
    monkeypatch.setattr("memory_os.toolkit.workspace_runtime.subprocess.run", fake_run)

    result = RuntimeControl(tmp_path).shutdown_all(force=True)

    assert result["ok"] is True
    assert any(cmd[-3:] == ["telegram-daemon-control", "stop", "--force"] for cmd in calls)
    assert any(cmd[-2:] == ["daemon", "stop"] for cmd in calls)
    assert ["tmux", "kill-session", "-t", session] in calls
    assert ["zellij", "delete-session", session, "--force"] in calls


def test_restart_all_schedules_workspace_restart_by_default(tmp_path, monkeypatch):
    _write_config(tmp_path)
    run_calls = []
    popen_calls = []

    def fake_run(cmd, **kwargs):
        run_calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            popen_calls.append(cmd)

    monkeypatch.setattr("memory_os.toolkit.runtime_control.subprocess.run", fake_run)
    monkeypatch.setattr("memory_os.toolkit.runtime_control.subprocess.Popen", FakePopen)

    result = RuntimeControl(tmp_path).restart_all(force=True)

    assert result["ok"] is True
    assert any(cmd[-2:] == ["daemon", "start"] for cmd in run_calls)
    assert any(cmd[-2:] == ["telegram-daemon-control", "start"] for cmd in run_calls)
    assert popen_calls
    assert "--workspace-only" in popen_calls[0]
    assert "--no-detach" in popen_calls[0]


def test_restart_pane_uses_runtime_agnostic_manager(tmp_path, monkeypatch):
    _write_config(tmp_path)
    shortcuts = []
    messages = []

    class FakeManager:
        runtime = "tmux"
        session_name = "memory_os_workspace"

        def __init__(self, root):
            self.root = root

        def resolve_pane_target(self, name):
            return "%5"

        def send_shortcut(self, target, shortcut):
            shortcuts.append((target, shortcut))
            return True

        def send_keys(self, target, message, **kwargs):
            messages.append((target, message))

    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.MultiplexerManager", FakeManager)
    monkeypatch.setattr("memory_os.toolkit.runtime_control.time.sleep", lambda _: None)

    result = RuntimeControl(tmp_path).restart_pane("agent-manager")

    assert result.ok is True
    assert shortcuts == [
        ("%5", "cancel"),
        ("%5", "escape"),
        ("%5", "cancel"),
        ("%5", "clear"),
    ]
    assert messages and messages[0][0] == "%5"
    assert "agent-manager" in messages[0][1]
