"""Mutex-guarded git add+commit for concurrent multi-agent working trees.

Multiple agent CLIs (claude/codex/agy) can run `git add` in the same working
tree at the same time. A plain check-then-commit sequence has a race window:
another process's `git add` can land between this process's staged-file check
and its `git commit`, silently sweeping unrelated WIP into the commit. This
module closes that window with a file lock held across add+verify+commit.
"""

from __future__ import annotations

import fcntl
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List


class GitCommitSafeError(RuntimeError):
    pass


@contextmanager
def _commit_lock(root: Path) -> Iterator[None]:
    lock_path = root / ".git" / "memory_os_commit.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _run_git(root: Path, args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
    )


def safe_commit(root: Path, files: List[str], message: str) -> str:
    """Stage exactly `files` and commit, holding a lock across the whole sequence.

    Raises GitCommitSafeError if another process's changes land in the index
    during the staging window, or if git itself fails.
    """
    if not files:
        raise GitCommitSafeError("no files given")

    with _commit_lock(root):
        add_result = _run_git(root, ["add", "--", *files])
        if add_result.returncode != 0:
            raise GitCommitSafeError(f"git add failed: {add_result.stderr.strip()}")

        staged = _run_git(root, ["diff", "--cached", "--name-only"])
        if staged.returncode != 0:
            raise GitCommitSafeError(f"git diff --cached failed: {staged.stderr.strip()}")

        staged_files = {line.strip() for line in staged.stdout.splitlines() if line.strip()}
        expected_files = {str(Path(f)) for f in files}
        # normalize both sides the same way git prints paths (relative, forward slashes)
        staged_norm = {p.replace("\\", "/") for p in staged_files}
        expected_norm = {str(Path(f)).replace("\\", "/") for f in files}
        unexpected = staged_norm - expected_norm
        if unexpected:
            raise GitCommitSafeError(
                "staged set does not match requested files, another process staged: "
                + ", ".join(sorted(unexpected))
            )

        commit_result = _run_git(root, ["commit", "-m", message])
        if commit_result.returncode != 0:
            raise GitCommitSafeError(f"git commit failed: {commit_result.stderr.strip()}")

        return commit_result.stdout.strip()
