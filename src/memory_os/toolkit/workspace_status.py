"""Read-only status inspection for Memory OS workspaces."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def instances(root: Optional[Path] = None) -> dict:
    """Snapshot the active workspace runtime and core daemon process."""
    if root is None:
        root = Path(__file__).resolve().parents[3]

    result: dict = {"workspace": None, "daemon": None}

    from memory_os.core.config import MemoryOSConfig
    from memory_os.toolkit.workspace_runtime import WorkspaceSpec, workspace_runtime_diagnostics

    cfg = MemoryOSConfig(str(root / "memory_os.config.json"))
    diagnostics = workspace_runtime_diagnostics(
        WorkspaceSpec(root=root, session_name=cfg.tmux_session_name, panes=[])
    )
    running = [
        status
        for status in diagnostics.get("runtimes", {}).values()
        if status.get("available")
    ]
    if running:
        status = running[0]
        result["workspace"] = {
            "runtime": status.get("runtime", "unknown"),
            "session": status.get("session", cfg.tmux_session_name),
            "windows": status.get("windows", 1),
            "attached": bool(status.get("attached", False)),
        }

    pid_file = root / "data" / "daemon.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            result["daemon"] = {"pid": pid, "alive": True, "stale": False}
        except (ProcessLookupError, PermissionError, ValueError):
            result["daemon"] = {"pid": None, "alive": False, "stale": True}

    return result
