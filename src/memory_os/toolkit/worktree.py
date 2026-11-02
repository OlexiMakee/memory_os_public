"""Git Worktree isolation manager for Memory OS swarm agents."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AgentWorktreeManager:
    """Manages creation, patching, and removal of Git worktrees for isolated agent execution."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def _git(self, args: list[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd or self.root),
            capture_output=True,
            text=True,
            check=True,
        )

    def create_worktree(self, agent_id: str, task_id: str) -> Optional[Path]:
        """Create a new git worktree for the agent's task execution.

        Symlinks key uncommitted dependencies (.venv, .env, agent_context, data).
        Returns the path to the created worktree, or None if creation failed.
        """
        worktree_dir = self.root / ".agents" / f"{agent_id}_{task_id}"
        if worktree_dir.exists():
            logger.warning(f"[worktree] directory already exists, removing: {worktree_dir}")
            self.remove_worktree(worktree_dir)

        try:
            # Create worktree based on HEAD (detached)
            logger.info(f"[worktree] creating worktree at {worktree_dir}")
            self._git(["worktree", "add", "--detach", str(worktree_dir), "HEAD"])

            # Symlink dependencies
            deps = [".venv", ".env", "agent_context", "data", "memory_os.config.json"]
            for dep in deps:
                src = self.root / dep
                dst = worktree_dir / dep
                if src.exists() and not dst.exists():
                    try:
                        # On Windows we might need admin privilege for symlinks,
                        # but standard os.symlink works on Unix
                        os.symlink(os.path.relpath(src, dst.parent), dst)
                    except Exception as sym_exc:
                        logger.warning(f"[worktree] failed to symlink {dep}: {sym_exc}")
                        # Fallback to copy for small files like .env or config
                        if src.is_file() and dep in (".env", "memory_os.config.json"):
                            shutil.copy2(src, dst)

            return worktree_dir.resolve()
        except Exception as exc:
            logger.error(f"[worktree] failed to create worktree for {agent_id}/{task_id}: {exc}")
            if worktree_dir.exists():
                self.remove_worktree(worktree_dir)
            return None

    def get_baseline_commit(self) -> str:
        """Get the current HEAD commit hash of the root repository."""
        return self._git(["rev-parse", "HEAD"]).stdout.strip()

    def apply_changes_and_remove(self, worktree_path: Path, baseline_commit: str) -> bool:
        """Stage all changes in the worktree, generate a patch against baseline,

        apply the patch to the root repository, and remove the worktree.
        """
        success = False
        try:
            worktree_path = worktree_path.resolve()
            if not worktree_path.exists():
                logger.warning(f"[worktree] path {worktree_path} does not exist, skipping patch application")
                return False

            # 1. Stage all changes in worktree (including untracked files, respecting .gitignore)
            logger.info(f"[worktree] staging changes in {worktree_path}")
            subprocess.run(["git", "add", "-A"], cwd=str(worktree_path), check=False)

            # 2. Generate diff patch against baseline
            logger.info(f"[worktree] generating diff patch against {baseline_commit}")
            diff_proc = subprocess.run(
                ["git", "diff", baseline_commit, "--binary"],
                cwd=str(worktree_path),
                capture_output=True,
                text=True,
                check=False,
            )

            patch_content = diff_proc.stdout
            if patch_content.strip():
                # 3. Apply patch to root repository
                logger.info("[worktree] applying patch to root repository")
                apply_proc = subprocess.run(
                    ["git", "apply", "--whitespace=nowarn"],
                    input=patch_content,
                    cwd=str(self.root),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if apply_proc.returncode == 0:
                    logger.info("[worktree] patch applied successfully")
                    success = True
                else:
                    logger.error(f"[worktree] failed to apply patch:\nStdout: {apply_proc.stdout}\nStderr: {apply_proc.stderr}")
                    # Try fallback to git apply --reject if standard apply fails
                    logger.info("[worktree] trying fallback git apply --reject")
                    reject_proc = subprocess.run(
                        ["git", "apply", "--reject", "--whitespace=nowarn"],
                        input=patch_content,
                        cwd=str(self.root),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    success = (reject_proc.returncode == 0)
            else:
                logger.info("[worktree] no changes detected in worktree")
                success = True

        except Exception as exc:
            logger.error(f"[worktree] failed to apply changes from {worktree_path}: {exc}")
        finally:
            self.remove_worktree(worktree_path)

        return success

    def remove_worktree(self, worktree_path: Path) -> None:
        """Force remove the git worktree and clean up references."""
        try:
            worktree_path = worktree_path.resolve()
            if not worktree_path.exists():
                return
            logger.info(f"[worktree] removing worktree at {worktree_path}")
            # First prune stale worktree refs in git metadata
            self._git(["worktree", "prune"])
            # Remove worktree directory and registration
            subprocess.run(["git", "worktree", "remove", "--force", str(worktree_path)], check=False)
            # Ensure folder is fully deleted if git left anything
            if worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)
            self._git(["worktree", "prune"])
        except Exception as exc:
            logger.warning(f"[worktree] failed to clean up worktree {worktree_path}: {exc}")
