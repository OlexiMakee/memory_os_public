import subprocess
from pathlib import Path

import pytest

from memory_os.toolkit.git_commit_safe import GitCommitSafeError, safe_commit


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), check=True)
    (tmp_path / "a.txt").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=str(tmp_path), check=True)
    return tmp_path


def test_safe_commit_stages_and_commits_given_files(git_repo: Path) -> None:
    (git_repo / "a.txt").write_text("changed\n", encoding="utf-8")
    safe_commit(git_repo, ["a.txt"], "update a")

    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"], cwd=str(git_repo), capture_output=True, text=True, check=True
    )
    assert log.stdout.strip() == "update a"

    status = subprocess.run(
        ["git", "status", "--short"], cwd=str(git_repo), capture_output=True, text=True, check=True
    )
    assert status.stdout.strip() == ""


def test_safe_commit_rejects_unexpected_staged_file(git_repo: Path) -> None:
    (git_repo / "a.txt").write_text("changed\n", encoding="utf-8")
    (git_repo / "b.txt").write_text("other agent's wip\n", encoding="utf-8")
    subprocess.run(["git", "add", "b.txt"], cwd=str(git_repo), check=True)

    with pytest.raises(GitCommitSafeError, match="another process staged"):
        safe_commit(git_repo, ["a.txt"], "update a")

    # nothing should have been committed
    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"], cwd=str(git_repo), capture_output=True, text=True, check=True
    )
    assert log.stdout.strip() == "initial"


def test_safe_commit_requires_files(git_repo: Path) -> None:
    with pytest.raises(GitCommitSafeError, match="no files given"):
        safe_commit(git_repo, [], "empty")
