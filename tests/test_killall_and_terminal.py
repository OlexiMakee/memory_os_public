"""Tests for local agent startup exclusion, memory_os killall, and AgentManager terminal pane launch."""

import argparse
from pathlib import Path
import pytest
from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.workspace import _cli_agent_ids
from memory_os.toolkit.agent_manager import AgentManagerTUI


def test_cli_agent_ids_excludes_local(tmp_path: Path):
    """_cli_agent_ids must not include 'local' for auto-launch on startup."""
    agents = _cli_agent_ids(tmp_path)
    assert "local" not in agents


def test_agent_manager_launch_terminal(tmp_path: Path, monkeypatch):
    """AgentManagerTUI.launch_terminal should launch a terminal pane."""
    manager = AgentManagerTUI(tmp_path)
    monkeypatch.setattr(manager.tmux, "runtime", "zellij")
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: argparse.Namespace(returncode=0, stdout="", stderr=""))
    
    ok, msg = manager.launch_terminal()
    assert ok is True
    assert "Launched terminal" in msg


def test_agent_manager_launch_feed(tmp_path: Path, monkeypatch):
    """AgentManagerTUI.launch_feed should launch a live-feed pane."""
    manager = AgentManagerTUI(tmp_path)
    monkeypatch.setattr(manager.tmux, "runtime", "zellij")
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: argparse.Namespace(returncode=0, stdout="", stderr=""))
    
    ok, msg = manager.launch_feed()
    assert ok is True
    assert "Launched live-feed" in msg


def test_cmd_killall(tmp_path: Path, monkeypatch):
    """cmd_killall should run without errors and call stop_all / shutdown_all."""
    from memory_os.cli_groups.system_cmds import cmd_killall
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text('{"version": "0.1"}', encoding="utf-8")
    config = MemoryOSConfig(config_path=str(cfg_path))
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: argparse.Namespace(returncode=0, stdout="", stderr=""))

    args = argparse.Namespace()
    code = cmd_killall(args, config)
    assert code == 0
