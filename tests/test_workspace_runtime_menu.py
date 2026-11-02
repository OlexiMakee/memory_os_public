from memory_os.toolkit import workspace_runtime


class FakeRuntime:
    def __init__(self):
        self.attached = []
        self.stop_all_calls = 0

    def attach(self, session_name):
        self.attached.append(session_name)

    def stop_all(self):
        self.stop_all_calls += 1
        return {"ok": True}


def test_workspace_menu_actions_use_runtime_boundary(monkeypatch):
    runtimes = {"tmux": FakeRuntime(), "zellij": FakeRuntime()}
    monkeypatch.setattr(
        workspace_runtime,
        "select_workspace_runtime",
        lambda name: runtimes[name],
    )

    attach = workspace_runtime.handle_workspace_menu_action("ATTACH_TMUX:memory_os_workspace")
    killed = workspace_runtime.handle_workspace_menu_action("KILL_ALL_ZELLIJ_SESSIONS")

    assert attach.handled is True
    assert runtimes["tmux"].attached == ["memory_os_workspace"]
    assert killed.message == "All running zellij sessions have been killed."
    assert runtimes["zellij"].stop_all_calls == 1


def test_workspace_menu_action_ignores_project_paths():
    assert workspace_runtime.handle_workspace_menu_action("/tmp/project") is None
