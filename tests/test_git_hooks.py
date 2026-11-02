import argparse
import os
import subprocess
import sys
from pathlib import Path

import pytest

from memory_os.cli_groups.system_cmds import cmd_integrate
from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.git_hooks import VENV_CANDIDATES, detect_repo_role, install_git_hooks


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
    # Runtime venv resolution instead of hardcoded .venv activation.
    assert "VIRTUAL_ENV" in pre_content
    for venv in VENV_CANDIDATES:
        assert venv in pre_content
    assert "exit 1" in pre_content

    assert post_commit.exists()
    assert os.access(post_commit, os.X_OK)
    post_content = post_commit.read_text(encoding="utf-8")
    assert '"$MEMORY_OS_BIN" memory write --type fact --summary "Git commit: $(git log -1 --pretty=format:\'%h - %s\')"' in post_content


def test_consumer_repo_gets_validate_and_security_gate_not_release_check(git_repo: Path) -> None:
    assert detect_repo_role(git_repo) == "consumer"
    install_git_hooks(git_repo)
    pre_content = (git_repo / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    assert "release-check" not in pre_content
    assert '"$MEMORY_OS_BIN" validate || exit 1' in pre_content
    assert '"$MEMORY_OS_BIN" security scan || exit 1' in pre_content


def test_consumer_role_for_foreign_pyproject(git_repo: Path) -> None:
    (git_repo / "pyproject.toml").write_text('[project]\nname = "job_app"\n', encoding="utf-8")
    assert detect_repo_role(git_repo) == "consumer"


def test_package_repo_gets_release_check_gate(git_repo: Path) -> None:
    (git_repo / "pyproject.toml").write_text('[project]\nname = "memory_os"\n', encoding="utf-8")
    assert detect_repo_role(git_repo) == "package"
    install_git_hooks(git_repo)
    pre_content = (git_repo / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    assert '"$MEMORY_OS_BIN" release-check --target private || exit 1' in pre_content
    assert "security scan" not in pre_content


def _fake_cli(venv_dir: Path, log: Path, exit_code: int = 0) -> None:
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True)
    cli = bin_dir / "memory_os"
    cli.write_text(f'#!/bin/bash\necho "$0 $*" >> "{log}"\nexit {exit_code}\n', encoding="utf-8")
    cli.chmod(0o755)


def _hook_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["PATH"] = "/usr/bin:/bin"  # exclude any globally installed memory_os
    return env


@pytest.mark.skipif(sys.platform.startswith("win"), reason="bash hooks")
def test_pre_commit_hook_resolves_non_default_venv_at_runtime(git_repo: Path) -> None:
    log = git_repo / "calls.log"
    _fake_cli(git_repo / "venv_auto", log)
    install_git_hooks(git_repo)
    result = subprocess.run(
        [str(git_repo / ".git" / "hooks" / "pre-commit")],
        cwd=str(git_repo), env=_hook_env(), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert [c.split(" ", 1)[1] for c in calls] == ["validate", "security scan"]
    assert all("venv_auto/bin/memory_os" in c for c in calls)


@pytest.mark.skipif(sys.platform.startswith("win"), reason="bash hooks")
def test_pre_commit_hook_blocks_on_failing_gate(git_repo: Path) -> None:
    _fake_cli(git_repo / ".venv", git_repo / "calls.log", exit_code=1)
    install_git_hooks(git_repo)
    result = subprocess.run(
        [str(git_repo / ".git" / "hooks" / "pre-commit")],
        cwd=str(git_repo), env=_hook_env(), capture_output=True, text=True,
    )
    assert result.returncode == 1


@pytest.mark.skipif(sys.platform.startswith("win"), reason="bash hooks")
def test_hooks_without_cli_fail_pre_commit_and_skip_post_commit(git_repo: Path) -> None:
    install_git_hooks(git_repo)
    hooks = git_repo / ".git" / "hooks"
    pre = subprocess.run([str(hooks / "pre-commit")], cwd=str(git_repo), env=_hook_env(), capture_output=True, text=True)
    assert pre.returncode == 1
    assert "CLI not found" in pre.stderr
    post = subprocess.run([str(hooks / "post-commit")], cwd=str(git_repo), env=_hook_env(), capture_output=True, text=True)
    assert post.returncode == 0
    assert "snapshot skipped" in post.stderr


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
