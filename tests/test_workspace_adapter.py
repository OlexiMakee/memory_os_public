from subprocess import CompletedProcess


def test_zellij_adapter_deletes_exited_session_before_launch(monkeypatch, tmp_path):
    from memory_os.toolkit.workspace_adapter import ZellijAdapter

    calls = []
    popen_calls = []
    list_calls = {"count": 0}

    monkeypatch.setattr("memory_os.toolkit.workspace_adapter.shutil.which", lambda binary: "/usr/bin/zellij")
    monkeypatch.setattr("memory_os.toolkit.workspace_adapter.Path", lambda value: tmp_path)

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd == ["zellij", "list-sessions", "--no-formatting"]:
            list_calls["count"] += 1
            stdout = "memory_os_workspace [Created 3m ago] (EXITED - attach to resurrect)\n" if list_calls["count"] == 1 else ""
            return CompletedProcess(cmd, 0, stdout=stdout, stderr="")
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            popen_calls.append(cmd)

    monkeypatch.setattr("memory_os.toolkit.workspace_adapter.subprocess.run", fake_run)
    monkeypatch.setattr("memory_os.toolkit.workspace_adapter.subprocess.Popen", FakePopen)

    assert ZellijAdapter().initialize_session("memory_os_workspace", "layout {}") is True
    assert ["zellij", "delete-session", "memory_os_workspace", "--force"] in calls
    assert popen_calls == [["zellij", "--new-session-with-layout", str(tmp_path / "zellij_memory_os_workspace.kdl"), "--session", "memory_os_workspace"]]


def test_zellij_adapter_actions_target_sessions_and_panes(monkeypatch):
    from memory_os.toolkit.workspace_adapter import ZellijAdapter

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return CompletedProcess(cmd, 0, stdout="dummy output", stderr="")

    monkeypatch.setattr("memory_os.toolkit.workspace_adapter.subprocess.run", fake_run)

    adapter = ZellijAdapter()
    
    # Test inject_input — uses --pane-id directly, no focus step
    adapter.inject_input("test_sess", "pane_123", "hello\nworld")
    assert ["zellij", "--session", "test_sess", "action", "paste", "--pane-id", "pane_123", "hello\nworld"] in calls

    # Test capture_pane_buffer — uses --pane-id on dump-screen
    calls.clear()
    res = adapter.capture_pane_buffer("test_sess", "pane_123", full_history=True)
    assert ["zellij", "--session", "test_sess", "action", "dump-screen", "--pane-id", "pane_123", "--full"] in calls
    assert res == "dummy output"

    # Test terminate_pane — uses --pane-id on close-pane
    calls.clear()
    ok = adapter.terminate_pane("test_sess", "pane_123")
    assert ["zellij", "--session", "test_sess", "action", "close-pane", "--pane-id", "pane_123"] in calls
    assert ok is True


def test_tmux_adapter_inject_keys(monkeypatch):
    from memory_os.toolkit.workspace_adapter import TmuxAdapter

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("memory_os.toolkit.workspace_adapter.subprocess.run", fake_run)
    monkeypatch.setattr("time.sleep", lambda s: None)

    adapter = TmuxAdapter()
    adapter.inject_keys("test_sess", "pane_123", ["up", "a"])
    assert ["tmux", "send-keys", "-t", "pane_123", "Up"] in calls
    assert ["tmux", "send-keys", "-t", "pane_123", "-l", "a"] in calls


def test_zellij_adapter_inject_keys(monkeypatch):
    from memory_os.toolkit.workspace_adapter import ZellijAdapter

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("memory_os.toolkit.workspace_adapter.subprocess.run", fake_run)
    monkeypatch.setattr("time.sleep", lambda s: None)

    adapter = ZellijAdapter()
    adapter.inject_keys("test_sess", "pane_123", ["up", "a"])
    assert ["zellij", "--session", "test_sess", "action", "send-keys", "--pane-id", "pane_123", "up"] in calls
    assert ["zellij", "--session", "test_sess", "action", "write-chars", "--pane-id", "pane_123", "a"] in calls

