"""Universal Undo service for Memory OS."""

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.interfaces import IMemoryOSConfig
from memory_os.core.patch import RelationPatch, RelationPatchStore
from memory_os.core.repository import MemoryRepository
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.core.timecode import now_local_iso


class UndoService:
    """Reverts memory events, patch store changes, and workspace git changes."""

    def __init__(
        self,
        config: Optional[IMemoryOSConfig] = None,
        repository: Optional[MemoryRepository] = None,
    ):
        self.config = config or MemoryOSConfig()
        self.storage = FileSystemMemoryStorage()
        self.repository = repository or MemoryRepository(self.storage, self.config)
        self.patch_store = RelationPatchStore(self.repository)

    def undo(
        self,
        task_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        target_task_id = task_id or self._resolve_target_task_id()
        patches_to_rollback = self._resolve_patches_for_task(target_task_id)
        modified_files = self._resolve_modified_files_for_task(target_task_id)

        if not target_task_id and not patches_to_rollback and not modified_files:
            return {
                "ok": False,
                "task_id": task_id,
                "dry_run": dry_run,
                "error": "No revertible task, patch, or event found",
                "patches_rolled_back": [],
                "git_clean": self._is_git_workspace_clean(),
                "git_reverted": False,
                "reverted_files": [],
            }

        git_clean = self._is_git_workspace_clean()
        git_reverted = False
        reverted_files: List[str] = []

        if dry_run:
            rolled_back_ids = [p.id for p in patches_to_rollback]
            if git_clean and modified_files:
                reverted_files = modified_files
            return {
                "ok": True,
                "task_id": target_task_id,
                "dry_run": True,
                "patches_rolled_back": rolled_back_ids,
                "git_clean": git_clean,
                "git_reverted": False,
                "reverted_files": reverted_files,
                "details": f"Dry run: would undo task '{target_task_id or 'latest'}'",
            }

        rolled_back_ids = []
        for patch in patches_to_rollback:
            if self.patch_store.rollback(patch.id):
                rolled_back_ids.append(patch.id)

        if git_clean:
            git_reverted, reverted_files = self._revert_git_changes(target_task_id, modified_files)

        self._log_undo_event(target_task_id, rolled_back_ids, git_reverted, reverted_files)

        return {
            "ok": True,
            "task_id": target_task_id,
            "dry_run": False,
            "patches_rolled_back": rolled_back_ids,
            "git_clean": git_clean,
            "git_reverted": git_reverted,
            "reverted_files": reverted_files,
            "details": f"Successfully undid task '{target_task_id or 'latest'}'",
        }

    def _resolve_target_task_id(self) -> Optional[str]:
        events = self.repository.get_events()
        for event in reversed(events):
            t_id = event.get("task_id")
            if t_id:
                return str(t_id)

        capsules = self.repository.get_task_capsules()
        for capsule in reversed(capsules):
            t_id = getattr(capsule, "task", None) or getattr(capsule, "task_id", None)
            if t_id:
                return str(t_id)

        patches = self.repository.get_patches()
        for patch in reversed(patches):
            if patch.status == "applied":
                t_id = patch.payload.get("task_id")
                if t_id:
                    return str(t_id)

        return None

    def _resolve_patches_for_task(self, task_id: Optional[str]) -> List[RelationPatch]:
        patches = [p for p in self.repository.get_patches() if p.status == "applied"]
        if not patches:
            return []

        if task_id:
            matching = [
                p for p in patches
                if (
                    p.payload.get("task_id") == task_id
                    or task_id in p.reason
                    or task_id in p.id
                    or any(task_id in ev for ev in p.evidence)
                )
            ]
            if matching:
                return matching

        return [patches[-1]]

    def _resolve_modified_files_for_task(self, task_id: Optional[str]) -> List[str]:
        if task_id:
            capsules = self.repository.get_task_capsules()
            for capsule in reversed(capsules):
                c_id = getattr(capsule, "task", None) or getattr(capsule, "task_id", None)
                if c_id == task_id and getattr(capsule, "files_modified", None):
                    return list(capsule.files_modified)

        patches = self._resolve_patches_for_task(task_id)
        files = []
        for patch in patches:
            if patch.target and (patch.target.endswith(".py") or "/" in patch.target or "." in patch.target):
                files.append(patch.target)
        return files

    def _is_git_workspace_clean(self) -> bool:
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.config.root_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            return res.returncode == 0 and not res.stdout.strip()
        except (subprocess.SubprocessError, OSError):
            return False

    def _revert_git_changes(
        self,
        task_id: Optional[str],
        modified_files: List[str],
    ) -> tuple[bool, List[str]]:
        if modified_files:
            valid_files = [
                f for f in modified_files
                if (self.config.root_dir / f).exists() or Path(f).exists()
            ]
            if valid_files:
                try:
                    res = subprocess.run(
                        ["git", "checkout", "HEAD~1", "--"] + valid_files,
                        cwd=self.config.root_dir,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if res.returncode == 0:
                        return True, valid_files
                except (subprocess.SubprocessError, OSError):
                    pass

        try:
            res = subprocess.run(
                ["git", "revert", "HEAD", "--no-edit"],
                cwd=self.config.root_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                return True, modified_files
        except (subprocess.SubprocessError, OSError):
            pass

        return False, []

    def _log_undo_event(
        self,
        task_id: Optional[str],
        rolled_back_patches: List[str],
        git_reverted: bool,
        reverted_files: List[str],
    ) -> None:
        undo_event = {
            "event": "memory.undo",
            "task_id": task_id,
            "timestamp": now_local_iso(self.config),
            "patches_rolled_back": rolled_back_patches,
            "git_reverted": git_reverted,
            "reverted_files": reverted_files,
            "status": "accepted",
            "claim": f"Undid task {task_id or 'latest'}",
        }
        self.repository.emit_event(undo_event, sync=True)
