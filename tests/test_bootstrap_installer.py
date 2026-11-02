import sys
from pathlib import Path
from memory_os.toolkit.bootstrap_installer import (
    check_system_tools,
    check_installed_agents,
    run_bootstrap,
)


def test_check_system_tools():
    tools = check_system_tools()
    assert isinstance(tools, dict)
    assert "git" in tools


def test_check_installed_agents():
    agents = check_installed_agents()
    assert isinstance(agents, dict)
    assert "claude" in agents
    assert "hermes" in agents


def test_run_bootstrap_non_interactive(monkeypatch, tmp_path):
    marker = tmp_path / ".memory_os" / ".bootstrapped"
    monkeypatch.setattr("memory_os.toolkit.bootstrap_installer.BOOTSTRAP_MARKER", marker)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    run_bootstrap(force=True, interactive=False)
    assert marker.exists()


def test_run_bootstrap_dry_run_and_json(monkeypatch, tmp_path):
    marker = tmp_path / ".memory_os" / ".bootstrapped"
    monkeypatch.setattr("memory_os.toolkit.bootstrap_installer.BOOTSTRAP_MARKER", marker)

    res = run_bootstrap(force=True, interactive=False, dry_run=True, json_output=True)
    assert isinstance(res, dict)
    assert "system_tools" in res
    assert not marker.exists()
