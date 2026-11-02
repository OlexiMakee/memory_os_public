import argparse
import os
import subprocess
from pathlib import Path

import pytest

from memory_os.cli_groups.system_cmds import cmd_integrate
from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.git_hooks import install_git_hooks


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    return tmp_path


def test_install_git_hooks_fails_without_git_dir(tmp_path: Path) -> None:
    success, actions = install_git_hooks(tmp_path)
    assert not success
    assert any("Git repository not found" in action for action in actions)


def test_install_git_hooks_installs_pre_and_post_commit_hooks(git_repo: Path) -> None:
    success, actions = install_git_hooks(git_repo)
    assert success
    assert len(actions) == 2

    pre_commit = git_repo / ".git" / "hooks" / "pre-commit"
    post_commit = git_repo / ".git" / "hooks" / "post-commit"

    assert pre_commit.exists()
    assert os.access(pre_commit, os.X_OK)
    pre_content = pre_commit.read_text(encoding="utf-8")
    assert "source .venv/bin/activate" in pre_content
    assert "memory_os release-check --target private" in pre_content
    assert "exit 1" in pre_content

    assert post_commit.exists()
    assert os.access(post_commit, os.X_OK)
    post_content = post_commit.read_text(encoding="utf-8")
    assert "source .venv/bin/activate" in post_content
    assert 'memory_os memory write --type fact --summary "Git commit: $(git log -1 --pretty=format:\'%h - %s\')"' in post_content


def test_cmd_integrate_with_git_hooks(git_repo: Path) -> None:
    config = MemoryOSConfig(config_path=str(git_repo / "memory_os.config.json"))
    args = argparse.Namespace(root=str(git_repo), install_git_hooks=True)
    code = cmd_integrate(args, config)
    assert code == 0

    assert (git_repo / ".git" / "hooks" / "pre-commit").exists()
    assert (git_repo / ".git" / "hooks" / "post-commit").exists()


def test_cmd_integrate_with_git_hooks_fails_in_non_git_dir(tmp_path: Path) -> None:
    config = MemoryOSConfig(config_path=str(tmp_path / "memory_os.config.json"))
    args = argparse.Namespace(root=str(tmp_path), install_git_hooks=True)
    code = cmd_integrate(args, config)
    assert code == 1
