import json
import pytest
from pathlib import Path
from memory_os.toolkit.multiplexer_manager import MultiplexerManager, MultiplexerPaneInfo


def test_multiplexer_manager_initialization(tmp_path):
    mgr = MultiplexerManager(tmp_path)
    assert mgr.root == tmp_path
    assert isinstance(mgr.is_available(), bool)


def test_multiplexer_pane_info_to_dict():
    info = MultiplexerPaneInfo(
        session="memory_os_workspace",
        window_index=0,
        pane_index=1,
        target="memory_os_workspace:0.1",
        width=80,
        height=24,
        active=True,
        current_command="python3",
    )
    d = info.to_dict()
    assert d["session"] == "memory_os_workspace"
    assert d["target"] == "memory_os_workspace:0.1"
    assert d["active"] is True


def test_multiplexer_manager_shortcuts(tmp_path, monkeypatch):
    mgr = MultiplexerManager(tmp_path)
    calls = []

    def fake_run(self, args, check=True):
        calls.append(args)
        class Proc:
            returncode = 0
            stdout = "memory_os_workspace:0.0|80|24|1|bash\n"
        return Proc()

    monkeypatch.setattr(MultiplexerManager, "_run", fake_run)

    assert mgr.send_shortcut("memory_os_workspace:0.0", "clear") is True
    assert mgr.send_shortcut("memory_os_workspace:0.0", "unknown_shortcut") is False

    mgr.send_keys("memory_os_workspace:0.0", "echo hello", submit=True, unlock_buffers=True, delay_sec=0)
    assert any("send-keys" in c for c in calls)

    panes = mgr.list_panes()
    assert len(panes) == 1
    assert panes[0].target == "memory_os_workspace:0.0"


def test_multiplexer_manager_zellij_shortcuts_write_control_bytes(tmp_path, monkeypatch):
    mgr = MultiplexerManager(tmp_path)
    mgr.runtime = "zellij"
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return __import__("subprocess").CompletedProcess(cmd, 0)

    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.subprocess.run", fake_run)

    assert mgr.send_shortcut("1", "escape") is True
    assert calls == [[
        "zellij", "--session", "memory_os_workspace", "action", "write", "--pane-id", "1", "27"
    ]]


def test_multiplexer_manager_zellij_shortcut_reports_failure(tmp_path, monkeypatch):
    mgr = MultiplexerManager(tmp_path)
    mgr.runtime = "zellij"

    monkeypatch.setattr(
        "memory_os.toolkit.multiplexer_manager.subprocess.run",
        lambda cmd, **kwargs: __import__("subprocess").CompletedProcess(cmd, 1),
    )

    assert mgr.send_shortcut("1", "clear") is False


def test_zellij_session_status_uses_workspace_runtime(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "agent_context" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "memory_os_workspace.json").write_text(
        json.dumps({"runtime": "zellij"}),
        encoding="utf-8",
    )
    calls = []

    def fake_status(self, spec):
        calls.append(spec.session_name)
        return {"runtime": "zellij", "session": spec.session_name, "available": True, "state": "running"}

    monkeypatch.setattr(
        "memory_os.toolkit.workspace_runtime.ZellijWorkspaceRuntime.status",
        fake_status,
    )

    status = MultiplexerManager(tmp_path).get_session_status()

    assert calls == ["memory_os_workspace"]
    assert status["running"] is True


def test_multiplexer_manager_resolve_pane_target_zellij(tmp_path):
    mgr = MultiplexerManager(tmp_path)
    mgr.runtime = "zellij"
    
    # Test translate Tmux session format
    t1 = mgr.resolve_pane_target("memory_os_workspace:agents.1")
    assert t1 == "1"  # codex default
    
    t2 = mgr.resolve_pane_target("memory_os_workspace:0.0")
    assert t2 == "0"  # claude pane id
    
    t3 = mgr.resolve_pane_target("memory_os_workspace:agents.2")
    assert t3 == "2"  # agy default

    t4 = mgr.resolve_pane_target("memory_os_workspace:agents.3")
    assert t4 == "3"  # local default


def test_multiplexer_manager_zellij_list_panes_falls_back_to_runtime_processes(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "agent_context" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "memory_os_workspace.json").write_text(
        json.dumps(
            {
                "runtime": "zellij",
                "session_name": "memory_os_workspace",
                "panes": [
                    {"key": "claude", "command": ["claude", "--continue"], "kind": "cli_agent"},
                    {"key": "codex", "command": ["codex", "resume", "--last"], "kind": "cli_agent"},
                    {"key": "agy", "command": ["agy", "--continue"], "kind": "cli_agent"},
                    {
                        "key": "agent-manager",
                        "command": ["python3", "-m", "memory_os", "agent-manager"],
                        "kind": "manager",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    class EmptyAdapter:
        def get_workspace_state(self, _session):
            return []

    def fake_run(cmd, **_kwargs):
        assert cmd == ["ps", "-eo", "pid=,args="]
        stdout = "\n".join(
            [
                "101 claude --continue --append-system-prompt-file prompt.md",
                "102 codex resume --last -c system_prompt=...",
                "103 python3 -m memory_os agent-manager",
            ]
        )
        return __import__("subprocess").CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.subprocess.run", fake_run)
    monkeypatch.setattr(
        "memory_os.toolkit.workspace_runtime.ZellijWorkspaceRuntime.status",
        lambda self, spec: {"runtime": "zellij", "session": spec.session_name, "available": True},
    )

    mgr = MultiplexerManager(tmp_path)
    mgr.runtime = "zellij"
    mgr.adapter = EmptyAdapter()

    panes = mgr.list_panes("memory_os_workspace")

    by_command = {pane.current_command: pane for pane in panes}
    assert set(by_command) == {"claude", "codex", "agent-manager"}
    assert by_command["claude"].target == "0"
    assert by_command["codex"].target == "1"
    assert by_command["agent-manager"].target == "4"


def test_multiplexer_manager_zellij_uses_runtime_layout_when_process_table_is_sandboxed(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "agent_context" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "memory_os_workspace.json").write_text(
        json.dumps(
            {
                "runtime": "zellij",
                "session_name": "memory_os_workspace",
                "panes": [
                    {"key": "claude", "command": ["claude", "--continue"], "kind": "cli_agent"},
                    {"key": "codex", "command": ["codex", "resume", "--last"], "kind": "cli_agent"},
                    {"key": "agy", "command": ["agy", "--continue"], "kind": "cli_agent"},
                ],
            }
        ),
        encoding="utf-8",
    )

    class EmptyAdapter:
        def get_workspace_state(self, _session):
            return []

    def fake_run(cmd, **_kwargs):
        if cmd == ["ps", "-eo", "pid=,args="]:
            stdout = "1 bwrap --new-session --die-with-parent\n2 python3 -m memory_os agent-manager\n"
            return __import__("subprocess").CompletedProcess(cmd, 0, stdout=stdout, stderr="")
        if cmd == ["zellij", "list-sessions", "--no-formatting"]:
            stdout = "memory_os_workspace [Created 9h ago] (current)\n"
            return __import__("subprocess").CompletedProcess(cmd, 0, stdout=stdout, stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.subprocess.run", fake_run)
    monkeypatch.setattr(
        "memory_os.toolkit.workspace_runtime.ZellijWorkspaceRuntime.status",
        lambda self, spec: {"runtime": "zellij", "session": spec.session_name, "available": True},
    )
    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.shutil.which", lambda binary: f"/usr/bin/{binary}")

    mgr = MultiplexerManager(tmp_path)
    mgr.runtime = "zellij"
    mgr.adapter = EmptyAdapter()

    panes = mgr.list_panes("memory_os_workspace")

    assert {pane.current_command for pane in panes} == {"claude", "codex", "agy"}


def test_multiplexer_manager_send_key_sequence(tmp_path, monkeypatch):
    class DummyAdapter:
        def inject_keys(self, session, target, keys):
            calls.append((session, target, keys))

    mgr = MultiplexerManager(tmp_path)
    mgr.adapter = DummyAdapter()
    calls = []

    mgr.send_key_sequence("memory_os_workspace:0.0", ["up", "down"])
    assert calls == [("memory_os_workspace", "memory_os_workspace:0.0", ["up", "down"])]
