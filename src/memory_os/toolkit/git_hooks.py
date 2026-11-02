"""Git hooks and auto-snapshot integration toolkit."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

PRE_COMMIT_HOOK = """#!/bin/bash
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi
memory_os release-check --target private
if [ $? -ne 0 ]; then
    exit 1
fi
"""

POST_COMMIT_HOOK = """#!/bin/bash
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi
memory_os memory write --type fact --summary "Git commit: $(git log -1 --pretty=format:'%h - %s')"
"""


def install_git_hooks(root: Path) -> Tuple[bool, List[str]]:
    """Install pre-commit and post-commit Git hooks in root/.git/hooks.

    Returns (True, actions) if successful, or (False, actions) if root is not a git repository.
    """
    git_dir = root / ".git"
    if not git_dir.exists() or not git_dir.is_dir():
        return False, ["Git repository not found (no .git directory)."]

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    actions: List[str] = []

    pre_commit_path = hooks_dir / "pre-commit"
    pre_commit_path.write_text(PRE_COMMIT_HOOK, encoding="utf-8")
    pre_commit_path.chmod(0o755)
    actions.append(f"installed {pre_commit_path}")

    post_commit_path = hooks_dir / "post-commit"
    post_commit_path.write_text(POST_COMMIT_HOOK, encoding="utf-8")
    post_commit_path.chmod(0o755)
    actions.append(f"installed {post_commit_path}")

    return True, actions
