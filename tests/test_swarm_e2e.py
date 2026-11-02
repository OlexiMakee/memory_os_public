import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.agent_comm import AgentComm
from memory_os.toolkit.workspace import send_task, watch_task, _relay_result_to_claude


@pytest.fixture
def root(tmp_path):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "agent_context" / "done").mkdir()
    return tmp_path


def test_swarm_e2e_send_task_and_done_relay(root, monkeypatch):
    config = MemoryOSConfig(config_path=str(root / "memory_os.config.json"))

    sent_keys = []

    def fake_send_text(self, target, message, submit=True, unlock_buffers=True):
        from memory_os.toolkit.agent_transport import TransportResult

        sent_keys.append({"target": target, "message": message})
        return TransportResult(ok=True, backend="tmux", target=target)

    monkeypatch.setenv("MEMORY_OS_AGENT_TRANSPORT", "tmux")
    monkeypatch.setattr("memory_os.toolkit.agent_transport.MultiplexerAgentTransport.send_text", fake_send_text)

    # 1. Send task to codex via workspace.send_task through AgentComm transport
    ok = send_task("codex", "task-e2e-001", "Implement test feature", session="memory_os_workspace", root=root)
    assert ok is True
    assert len(sent_keys) == 1
    assert sent_keys[0]["target"] == "memory_os_workspace:agents.1"
    assert "[SWARM MESSAGE" in sent_keys[0]["message"]
    assert "[TASK task-e2e-001]" in sent_keys[0]["message"]

    # 2. Codex completes task and sends STATUS_REPORT via AgentComm
    comm = AgentComm(root, config=config)
    comm_result = comm.send(
        recipient="claude",
        message="Task completed cleanly and verified",
        kind="STATUS_REPORT",
        sender="codex",
        task_id="task-e2e-001",
    )
    assert comm_result.ok is True

    done_file = root / "agent_context" / "done" / "task-e2e-001.json"
    assert done_file.exists()
    done_data = json.loads(done_file.read_text(encoding="utf-8"))
    assert done_data["sender"] == "codex"

    # 3. Watch task processes done signal and relays to claude
    result = watch_task("task-e2e-001", root=root, timeout=1, poll_interval=0.1)
    assert result["sender"] == "codex"
    assert any("[SWARM RESULT task=task-e2e-001]" in k["message"] for k in sent_keys)


def test_send_task_prefers_registry_tmux_target(root, monkeypatch):
    (root / "agent_context" / "agents").mkdir(parents=True)
    (root / "agent_context" / "agents" / "registry.toml").write_text(
        """
[agent.agy]
kind = "cli_agent"
tmux_target = "memory_os_workspace:0.2"
""",
        encoding="utf-8",
    )
    sent = []

    def fake_send_text(self, target, message, submit=True, unlock_buffers=True):
        from memory_os.toolkit.agent_transport import TransportResult

        sent.append(target)
        return TransportResult(ok=True, backend="tmux", target=target)

    monkeypatch.setenv("MEMORY_OS_AGENT_TRANSPORT", "tmux")
    monkeypatch.setattr("memory_os.toolkit.agent_transport.MultiplexerAgentTransport.send_text", fake_send_text)

    assert send_task("agy", "task-registry-target", "check target", session="memory_os_workspace", root=root) is True
    assert sent == ["memory_os_workspace:0.2"]


def test_resolve_agent_launch_cmd_project_isolation(tmp_path):
    from memory_os.toolkit.workspace import _resolve_agent_launch_cmd
    main_repo = tmp_path / "memory_os"
    other_repo = tmp_path / "News Research Automation"
    main_repo.mkdir()
    other_repo.mkdir()

    assert _resolve_agent_launch_cmd("claude", main_repo) == ["claude", "--continue"]
    assert _resolve_agent_launch_cmd("claude", other_repo) == ["claude"]
    assert _resolve_agent_launch_cmd("codex", other_repo) == ["codex"]


def test_resolve_agent_launch_cmd_uses_registry_launch_flags(tmp_path):
    from memory_os.toolkit.workspace import _resolve_agent_launch_cmd
    root = tmp_path / "memory_os"
    registry_dir = root / "agent_context" / "agents"
    registry_dir.mkdir(parents=True)
    (registry_dir / "registry.toml").write_text(
        """
[agent.claude]
kind = "cli_agent"
launch_flags = ["--dangerously-skip-permissions"]

[agent.codex]
kind = "cli_agent"
launch_flags = ["--sandbox", "danger-full-access", "--ask-for-approval", "never"]

[agent.agy]
kind = "cli_agent"
launch_flags = ["--dangerously-skip-permissions"]
""",
        encoding="utf-8",
    )

    assert _resolve_agent_launch_cmd("claude", root) == [
        "claude",
        "--continue",
        "--dangerously-skip-permissions",
    ]
    assert _resolve_agent_launch_cmd("codex", root) == [
        "codex",
        "resume",
        "--last",
        "--sandbox",
        "danger-full-access",
        "--ask-for-approval",
        "never",
    ]
    assert _resolve_agent_launch_cmd("agy", root) == [
        "agy",
        "--continue",
        "--dangerously-skip-permissions",
    ]


def test_cli_agent_ids_fallback_registry(tmp_path):
    from memory_os.toolkit.workspace import _cli_agent_ids
    empty_project = tmp_path / "custom_project"
    empty_project.mkdir()
    agents = _cli_agent_ids(empty_project)
    assert "claude" in agents
    assert "codex" in agents


def test_tmux_session_name_is_project_unique_for_same_basename(tmp_path):
    left = tmp_path / "left" / "same repo"
    right = tmp_path / "right" / "same repo"
    left.mkdir(parents=True)
    right.mkdir(parents=True)
    (left / "memory_os.config.json").write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (right / "memory_os.config.json").write_text(json.dumps({"version": "0.1"}), encoding="utf-8")

    left_cfg = MemoryOSConfig(config_path=str(left / "memory_os.config.json"))
    right_cfg = MemoryOSConfig(config_path=str(right / "memory_os.config.json"))

    assert left_cfg.workspace_id != right_cfg.workspace_id
    assert left_cfg.tmux_session_name != right_cfg.tmux_session_name
    assert left_cfg.tmux_session_name.startswith("memory_os_same_repo_")
    assert " " not in left_cfg.tmux_session_name


def test_agent_panes_include_telegram_chat_without_shifting_agents(root):
    config = MemoryOSConfig(config_path=str(root / "memory_os.config.json"))

    assert config.agent_panes["claude"] == 0
    assert config.agent_panes["codex"] == 1
    assert config.agent_panes["agy"] == 2
    assert config.agent_panes["telegram-chat"] == 3


def test_launch_workspace_adds_telegram_chat_pane(root, monkeypatch):
    from memory_os.toolkit import workspace
    from memory_os.toolkit import workspace_runtime

    calls = []
    init_calls = []
    monkeypatch.setattr("memory_os.toolkit.project_secrets.ensure_project_telegram_token", lambda *args, **kwargs: True)
    monkeypatch.setenv("MEMORY_OS_WORKSPACE_RUNTIME", "tmux")
    monkeypatch.setattr(workspace_runtime.TmuxWorkspaceRuntime, "is_available", lambda self: True)
    monkeypatch.setattr(workspace_runtime.subprocess, "run", lambda *args, **kwargs: type("Result", (), {"returncode": 1})())
    monkeypatch.setattr(workspace_runtime.os, "execvp", lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit(0)))
    monkeypatch.setattr(workspace_runtime.TmuxWorkspaceRuntime, "_tmux", lambda self, *args: calls.append(args))
    monkeypatch.setattr(workspace_runtime.TmuxWorkspaceRuntime, "_init_pane", lambda self, target, root, cmd, label, venv: init_calls.append({
        "target": target,
        "cmd": cmd,
        "label": label,
    }))

    with pytest.raises(SystemExit):
        workspace.launch_workspace(root)

    labels = [call["label"] for call in init_calls]
    assert labels[:3] == ["claude:{}".format(root.name), "codex:{}".format(root.name), "agy:{}".format(root.name)]
    assert all("local-model" not in label for label in labels)
    assert "telegram-chat" in labels
    telegram = next(call for call in init_calls if call["label"] == "telegram-chat")
    num_cli = sum(1 for label in labels if ":" in label)
    assert telegram["target"] == "memory_os_{}_{}:agents.{}".format(root.name, MemoryOSConfig(str(root / "memory_os.config.json")).workspace_id[:8], num_cli + 1)
    assert telegram["cmd"][-4:] == ["telegram-daemon", "--swarm-control", "--swarm-watch-timeout", "0"]
    assert ("split-window", "-v", "-t", telegram["target"].rsplit(".", 1)[0] + ".{}".format(num_cli)) in calls


def test_launch_workspace_file_runtime_without_tmux(root, monkeypatch):
    from memory_os.toolkit import workspace

    monkeypatch.setenv("MEMORY_OS_WORKSPACE_RUNTIME", "file")
    monkeypatch.setattr("memory_os.toolkit.project_secrets.ensure_project_telegram_token", lambda *args, **kwargs: True)

    workspace.launch_workspace(root)

    cfg = MemoryOSConfig(str(root / "memory_os.config.json"))
    state_file = root / "agent_context" / "runtime" / f"{cfg.tmux_session_name}.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["runtime"] == "file"
    labels = [pane["label"] for pane in state["panes"]]
    assert all("local-model" not in label for label in labels)
    assert "telegram-chat" in labels


def test_zellij_workspace_layout_includes_agents_telegram_manager_and_feed(root):
    from memory_os.toolkit.workspace_runtime import (
        WorkspacePaneSpec,
        WorkspaceSpec,
        ZellijWorkspaceRuntime,
    )

    spec = WorkspaceSpec(
        root=root,
        session_name="memory_os_workspace",
        panes=[
            WorkspacePaneSpec("claude", "claude:test", ["claude"], "cli_agent"),
            WorkspacePaneSpec("codex", "codex:test", ["codex"], "cli_agent"),
            WorkspacePaneSpec("agy", "agy:test", ["agy"], "cli_agent"),
            WorkspacePaneSpec(
                "telegram-chat",
                "telegram-chat",
                ["python", "-m", "memory_os", "telegram-daemon", "--swarm-control"],
                "telegram",
            ),
            WorkspacePaneSpec(
                "agent-manager",
                "agent-manager",
                ["python", "-m", "memory_os", "agent-manager"],
                "manager",
            ),
        ],
        venv=False,
    )

    layout = ZellijWorkspaceRuntime()._generate_kdl_layout(spec)

    assert 'pane name="Agents" split_direction="Vertical"' in layout
    assert 'pane name="Management" split_direction="Horizontal" size="40%"' in layout
    for pane_name in ("claude", "codex", "agy", "telegram-chat", "agent-manager"):
        assert f'pane name="{pane_name}" command="bash"' in layout
        assert "start_suspended false" in layout
    assert "telegram-daemon" in layout
    assert "agent-manager" in layout


def test_zellij_runtime_lists_sessions_without_formatting(root, monkeypatch):
    from memory_os.toolkit.workspace_runtime import (
        WorkspacePaneSpec,
        WorkspaceSpec,
        ZellijWorkspaceRuntime,
    )

    calls = []
    spec = WorkspaceSpec(
        root=root,
        session_name="memory_os_workspace",
        panes=[WorkspacePaneSpec("codex", "codex:test", ["codex"], "cli_agent")],
        venv=False,
    )

    monkeypatch.setattr(ZellijWorkspaceRuntime, "is_available", lambda self: True)
    monkeypatch.setattr("memory_os.toolkit.workspace_runtime.os.execvp", lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit(0)))
    monkeypatch.setattr("memory_os.toolkit.workspace_runtime.os.execvpe", lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit(0)))

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return type("Result", (), {
            "returncode": 0,
            "stdout": "lucky-donkey [Created 52m ago] (EXITED - attach to resurrect)\n",
            "stderr": "",
        })()

    monkeypatch.setattr("memory_os.toolkit.workspace_runtime.subprocess.run", fake_run)

    with pytest.raises(SystemExit):
        ZellijWorkspaceRuntime().launch(spec, attach=True)

    assert ["zellij", "list-sessions", "--no-formatting"] in calls


def test_zellij_runtime_status_marks_exited_session_unavailable(root, monkeypatch):
    from memory_os.toolkit.workspace_runtime import WorkspaceSpec, ZellijWorkspaceRuntime

    spec = WorkspaceSpec(root=root, session_name="memory_os_workspace", panes=[], venv=False)
    state_dir = root / "agent_context" / "runtime"
    state_dir.mkdir(parents=True)
    (state_dir / "memory_os_workspace.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(ZellijWorkspaceRuntime, "is_available", lambda self: True)

    def fake_run(cmd, **kwargs):
        assert cmd == ["zellij", "list-sessions", "--no-formatting"]
        return type("Result", (), {
            "stdout": "memory_os_workspace [Created 3m ago] (EXITED - attach to resurrect)\n",
            "stderr": "",
            "returncode": 0,
        })()

    monkeypatch.setattr("memory_os.toolkit.workspace_runtime.subprocess.run", fake_run)

    status = ZellijWorkspaceRuntime().status(spec)

    assert status["available"] is False
    assert status["state"] == "exited"


def test_zellij_runtime_clean_exited_sessions_is_dry_run_by_default(root, monkeypatch):
    from memory_os.toolkit.workspace_runtime import ZellijWorkspaceRuntime

    calls = []
    monkeypatch.setattr(ZellijWorkspaceRuntime, "is_available", lambda self: True)

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return type("Result", (), {
            "stdout": (
                "lucky-donkey [Created 52m ago] (EXITED - attach to resurrect)\n"
                "memory_os_workspace [Created 3m ago] (current)\n"
            ),
            "stderr": "",
            "returncode": 0,
        })()

    monkeypatch.setattr("memory_os.toolkit.workspace_runtime.subprocess.run", fake_run)

    result = ZellijWorkspaceRuntime().clean_exited_sessions()

    assert result["apply"] is False
    assert result["exited_sessions"] == ["lucky-donkey"]
    assert result["deleted"] == []
    assert ["zellij", "delete-session", "lucky-donkey", "--force"] not in calls


def test_workspace_status_cli_reports_runtime_without_launch(root, monkeypatch, capsys):
    import argparse
    from memory_os.cli import cmd_workspace
    from memory_os.core.config import MemoryOSConfig

    class FakeRuntime:
        name = "zellij"

        def status(self, spec):
            return {
                "runtime": "zellij",
                "session": spec.session_name,
                "available": False,
                "state": "exited",
                "detail": "memory_os_workspace (EXITED - attach to resurrect)",
                "state_file": str(spec.root / "agent_context" / "runtime" / f"{spec.session_name}.json"),
            }

    monkeypatch.setattr("memory_os.toolkit.workspace_runtime.select_workspace_runtime", lambda runtime_name: FakeRuntime())

    args = argparse.Namespace(workspace_action="status", runtime="zellij", json=False)
    code = cmd_workspace(args, MemoryOSConfig(config_path=str(root / "memory_os.config.json")))
    out = capsys.readouterr().out

    assert code == 1
    assert "runtime: zellij" in out
    assert "state: exited" in out


def test_workspace_clean_exited_cli_dry_run(root, monkeypatch, capsys):
    import argparse
    from memory_os.cli import cmd_workspace
    from memory_os.core.config import MemoryOSConfig

    class FakeZellijRuntime:
        def clean_exited_sessions(self, *, apply=False):
            return {
                "runtime": "zellij",
                "apply": apply,
                "exited_sessions": ["lucky-donkey"],
                "deleted": ["lucky-donkey"] if apply else [],
            }

    monkeypatch.setattr("memory_os.toolkit.workspace_runtime.ZellijWorkspaceRuntime", lambda: FakeZellijRuntime())

    args = argparse.Namespace(workspace_action="clean-exited", runtime="zellij", apply=False, json=False)
    code = cmd_workspace(args, MemoryOSConfig(config_path=str(root / "memory_os.config.json")))
    out = capsys.readouterr().out

    assert code == 0
    assert "mode: dry-run" in out
    assert "lucky-donkey: pending" in out


def test_doctor_workspace_runtime_block_reports_exited_zellij(root, monkeypatch, capsys):
    from memory_os.cli import _print_workspace_runtime_doctor
    from memory_os.core.config import MemoryOSConfig

    def fake_diagnostics(spec):
        return {
            "session": spec.session_name,
            "runtimes": {
                "tmux": {"runtime": "tmux", "available": True},
                "zellij": {
                    "runtime": "zellij",
                    "available": False,
                    "state": "exited",
                    "detail": "memory_os_workspace [Created 3m ago] (EXITED - attach to resurrect)",
                },
            },
            "zellij_exited_sessions": ["memory_os_workspace", "lucky-donkey"],
        }

    monkeypatch.setattr("memory_os.toolkit.workspace_runtime.workspace_runtime_diagnostics", fake_diagnostics)

    _print_workspace_runtime_doctor(MemoryOSConfig(config_path=str(root / "memory_os.config.json")))
    out = capsys.readouterr().out

    assert "Workspace runtime tmux: available" in out
    assert "Workspace runtime zellij: exited" in out
    assert "Zellij exited sessions: memory_os_workspace, lucky-donkey" in out
    assert "memory_os workspace clean-exited --runtime zellij --apply" in out
