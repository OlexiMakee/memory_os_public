import os
import shutil
import subprocess
from pathlib import Path
import pytest
from memory_os.toolkit.worktree import AgentWorktreeManager


def test_worktree_creation_and_removal(tmp_path):
    # Initialize a dummy git repository in tmp_path
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), check=True)

    # Create baseline file and commit it
    readme = tmp_path / "README.md"
    readme.write_text("initial readme", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".venv/\n.env\nagent_context/\n.agents/\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md", ".gitignore"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(tmp_path), check=True)

    # Create mock dependencies to be symlinked
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".env").write_text("SECRET=123", encoding="utf-8")
    (tmp_path / "agent_context").mkdir()

    wt_manager = AgentWorktreeManager(tmp_path)
    baseline = wt_manager.get_baseline_commit()
    assert len(baseline) == 40  # sha-1 hash length

    # 1. Create worktree
    wt_path = wt_manager.create_worktree("codex", "task_123")
    assert wt_path is not None
    assert wt_path.exists()
    assert (wt_path / "README.md").exists()
    assert (wt_path / ".git").exists()

    # Verify symlinks
    assert (wt_path / ".venv").is_dir()
    assert (wt_path / ".env").read_text(encoding="utf-8") == "SECRET=123"
    assert (wt_path / "agent_context").is_dir()

    # 2. Modify files in the worktree
    (wt_path / "README.md").write_text("modified readme", encoding="utf-8")
    # Add a new file
    (wt_path / "new_file.py").write_text("print('hello')", encoding="utf-8")

    # 3. Apply changes and remove
    ok = wt_manager.apply_changes_and_remove(wt_path, baseline)
    assert ok is True

    # Verify worktree is removed
    assert not wt_path.exists()

    # Verify changes applied to root
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "modified readme"
    assert (tmp_path / "new_file.py").read_text(encoding="utf-8") == "print('hello')"


def test_worktree_cleanup_on_failure(tmp_path):
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), check=True)

    readme = tmp_path / "README.md"
    readme.write_text("initial readme", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(tmp_path), check=True)

    wt_manager = AgentWorktreeManager(tmp_path)
    wt_path = wt_manager.create_worktree("claude", "task_abc")
    assert wt_path.exists()

    # Remove worktree without applying patch
    wt_manager.remove_worktree(wt_path)
    assert not wt_path.exists()
