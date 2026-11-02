import os
import sys
from pathlib import Path
from memory_os.toolkit.project_picker import scan_projects, select_workspace, _plain_picker


def test_scan_projects(tmp_path):
    dev_dir = tmp_path / "dev"
    dev_dir.mkdir()
    (dev_dir / "project_a").mkdir()
    (dev_dir / "project_b").mkdir()
    (dev_dir / ".hidden_project").mkdir()
    (dev_dir / "_archived_project").mkdir()

    projects = scan_projects(base_dir=dev_dir)
    names = [name for name, _ in projects]
    
    assert "project_a" in names
    assert "project_b" in names
    assert ".hidden_project" not in names
    assert "_archived_project" not in names


def test_scan_projects_limit(tmp_path):
    dev_dir = tmp_path / "dev"
    dev_dir.mkdir()
    for i in range(10):
        (dev_dir / f"proj_{i:02d}").mkdir()

    projects = scan_projects(base_dir=dev_dir, limit=5)
    assert len(projects) == 5


def test_select_workspace_non_interactive(monkeypatch, tmp_path):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    selected = select_workspace(base_dir=tmp_path)
    assert selected == Path.cwd()


def test_plain_picker_fallback(monkeypatch, tmp_path):
    options = [
        ("Global", tmp_path / "global"),
        ("Project A", tmp_path / "proj_a"),
    ]
    # Simulate user entering "2"
    monkeypatch.setattr("builtins.input", lambda prompt: "2")
    selected = _plain_picker(options)
    assert selected == tmp_path / "proj_a"


def test_get_active_tmux_sessions():
    from memory_os.toolkit.project_picker import get_active_tmux_sessions
    sessions = get_active_tmux_sessions()
    assert isinstance(sessions, list)


def test_get_active_zellij_sessions_ignores_exited_sessions(monkeypatch):
    from subprocess import CompletedProcess
    from memory_os.toolkit.project_picker import get_active_zellij_sessions

    monkeypatch.setattr("memory_os.toolkit.project_picker.shutil.which", lambda binary: "/usr/bin/zellij")

    def fake_run(cmd, **kwargs):
        assert cmd == ["zellij", "list-sessions", "--no-formatting"]
        return CompletedProcess(
            cmd,
            0,
            stdout=(
                "lucky-donkey [Created 52m ago] (EXITED - attach to resurrect)\n"
                "memory_os_workspace [Created 3m ago] (current)\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("memory_os.toolkit.project_picker.subprocess.run", fake_run)

    assert get_active_zellij_sessions() == ["memory_os_workspace"]
