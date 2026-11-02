"""Runtime control for Memory OS local processes."""

from __future__ import annotations

from memory_os.toolkit.agent_registry import KNOWN_AGENTS
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

from memory_os.core.config import MemoryOSConfig


@dataclass
class ControlStep:
    name: str
    ok: bool
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


class RuntimeControl:
    def __init__(self, root: Path, config: Optional[MemoryOSConfig] = None):
        self.root = root.resolve()
        self.config = config or MemoryOSConfig(str(self.root / "memory_os.config.json"))

    def shutdown_all(self, *, force: bool = False, workspace_only: bool = False) -> Dict[str, Any]:
        steps: List[ControlStep] = []
        if not workspace_only:
            steps.append(self._run_memory_os(["telegram-daemon-control", "stop"] + (["--force"] if force else []), "telegram-daemon stop"))
            steps.append(self._run_memory_os(["daemon", "stop"], "daemon stop"))
        steps.extend(self.stop_workspace(force=force))
        return self._result("shutdown", steps)

    def restart_all(
        self,
        *,
        force: bool = False,
        detach_workspace: bool = True,
        workspace_only: bool = False,
    ) -> Dict[str, Any]:
        steps: List[ControlStep] = []
        if workspace_only:
            steps.extend(self.stop_workspace(force=force))
            steps.append(self.start_workspace())
            return self._result("restart", steps)

        steps.append(self._run_memory_os(["telegram-daemon-control", "stop"] + (["--force"] if force else []), "telegram-daemon stop"))
        steps.append(self._run_memory_os(["daemon", "stop"], "daemon stop"))
        steps.append(self._run_memory_os(["daemon", "start"], "daemon start"))
        steps.append(self._run_memory_os(["telegram-daemon-control", "start"], "telegram-daemon start"))
        if detach_workspace:
            steps.append(self.schedule_workspace_restart(force=force))
        else:
            steps.extend(self.stop_workspace(force=force))
            steps.append(self.start_workspace())
        return self._result("restart", steps)

    def restart_pane(self, pane_name: str) -> ControlStep:
        from memory_os.toolkit.multiplexer_manager import MultiplexerManager
        from memory_os.toolkit.workspace import _cli_agent_ids, _resolve_agent_launch_cmd, _telegram_chat_cmd

        if pane_name == "telegram-chat":
            command = _telegram_chat_cmd()
        elif pane_name == "agent-manager":
            command = [sys.executable, "-m", "memory_os", "agent-manager"]
        else:
            agent_ids = _cli_agent_ids(self.root) or list(KNOWN_AGENTS)
            command = _resolve_agent_launch_cmd(pane_name, self.root) if pane_name in agent_ids else None
        if not command:
            return ControlStep(f"restart pane {pane_name}", False, f"unknown agent/pane: {pane_name}")

        manager = MultiplexerManager(self.root)
        target = manager.resolve_pane_target(pane_name)
        if manager.runtime == "zellij":
            try:
                from memory_os.toolkit.workspace_runtime import _zellij_env

                proc = subprocess.run(
                    ["zellij", "--session", manager.session_name, "action", "list-panes", "--json"],
                    capture_output=True,
                    text=True,
                    env=_zellij_env(),
                    timeout=5,
                )
                panes = json.loads(proc.stdout) if proc.returncode == 0 else []
                exited = any(
                    str(item.get("id")) == str(target) and item.get("exited") is True
                    for item in panes
                )
            except (json.JSONDecodeError, OSError, subprocess.TimeoutExpired, TypeError, ValueError):
                exited = False
            if exited:
                ok = manager.send_shortcut(target, "enter")
                detail = f"restarted exited pane {pane_name} ({target})"
                return ControlStep(f"restart pane {pane_name}", ok, detail if ok else f"failed: {detail}")

        for shortcut, delay in (("cancel", 0.3), ("escape", 0.2), ("cancel", 0.3), ("clear", 0.2)):
            if not manager.send_shortcut(target, shortcut):
                return ControlStep(
                    f"restart pane {pane_name}",
                    False,
                    f"failed to send {shortcut} to pane {target}",
                )
            time.sleep(delay)

        parts = []
        if (self.root / ".venv" / "bin" / "activate").exists():
            parts.append("source .venv/bin/activate")
        parts.append(shlex.join(command))
        try:
            manager.send_keys(target, " && ".join(parts), submit=True)
        except Exception as exc:
            return ControlStep(f"restart pane {pane_name}", False, str(exc))
        return ControlStep(f"restart pane {pane_name}", True, f"restarted pane {pane_name} ({target})")

    def schedule_workspace_restart(self, *, force: bool = False) -> ControlStep:
        cmd = [
            sys.executable,
            "-m",
            "memory_os",
            "--root",
            str(self.root),
            "agent-manager",
            "--restart-all",
            "--workspace-only",
            "--no-detach",
        ]
        if force:
            cmd.append("--force")
        try:
            subprocess.Popen(
                cmd,
                cwd=str(self.root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=(sys.platform != "win32"),
            )
            return ControlStep("workspace restart", True, "scheduled detached workspace restart")
        except Exception as exc:
            return ControlStep("workspace restart", False, str(exc))

    def start_workspace(self) -> ControlStep:
        try:
            from memory_os.toolkit.workspace import _cli_agent_ids, _resolve_agent_launch_cmd, _telegram_chat_cmd
            from memory_os.toolkit.workspace_runtime import (
                WorkspacePaneSpec,
                WorkspaceSpec,
                select_workspace_runtime,
            )

            project = self.root.name
            panes: List[WorkspacePaneSpec] = []
            for agent_id in (_cli_agent_ids(self.root) or ["claude"]):
                panes.append(
                    WorkspacePaneSpec(
                        key=agent_id,
                        label=f"{agent_id}:{project}",
                        command=_resolve_agent_launch_cmd(agent_id, self.root),
                        kind="cli_agent",
                    )
                )
            panes.append(
                WorkspacePaneSpec(
                    key="agent-manager",
                    label="agent-manager",
                    command=[sys.executable, "-m", "memory_os", "agent-manager"],
                    kind="manager",
                )
            )
            panes.append(WorkspacePaneSpec(key="telegram-chat", label="telegram-chat", command=_telegram_chat_cmd(), kind="telegram"))
            runtime = select_workspace_runtime(os.environ.get("MEMORY_OS_WORKSPACE_RUNTIME", "auto"))
            spec = WorkspaceSpec(
                root=self.root,
                session_name=self.config.tmux_session_name,
                panes=panes,
                venv=(self.root / ".venv" / "bin" / "activate").exists(),
            )
            runtime.launch(spec, attach=False)
            return ControlStep("workspace start", True, f"{runtime.name}:{self.config.tmux_session_name}")
        except Exception as exc:
            return ControlStep("workspace start", False, str(exc))

    def stop_workspace(self, *, force: bool = False) -> List[ControlStep]:
        from memory_os.toolkit.workspace_runtime import (
            TmuxWorkspaceRuntime,
            WorkspaceSpec,
            ZellijWorkspaceRuntime,
        )

        spec = WorkspaceSpec(root=self.root, session_name=self.config.tmux_session_name, panes=[])
        steps = []
        for runtime in (TmuxWorkspaceRuntime(), ZellijWorkspaceRuntime()):
            result = runtime.stop(spec, force=force)
            steps.append(
                ControlStep(
                    f"{runtime.name} workspace stop",
                    bool(result.get("ok")),
                    str(result.get("detail", "")),
                )
            )
        return steps

    def _run_memory_os(self, args: List[str], name: str) -> ControlStep:
        cmd = [sys.executable, "-m", "memory_os", "--root", str(self.root), *args]
        try:
            proc = subprocess.run(cmd, cwd=str(self.root), capture_output=True, text=True, timeout=15)
        except Exception as exc:
            return ControlStep(name, False, str(exc))
        output = " ".join(part.strip() for part in (proc.stdout, proc.stderr) if part.strip())
        lowered = output.lower()
        ok = proc.returncode == 0
        if not ok and any(marker in lowered for marker in ("not running", "already running", "stopped")):
            ok = True
        detail = output or f"exit={proc.returncode}"
        return ControlStep(name, ok, detail)

    @staticmethod
    def _result(action: str, steps: List[ControlStep]) -> Dict[str, Any]:
        return {
            "action": action,
            "ok": all(step.ok for step in steps),
            "steps": [step.to_dict() for step in steps],
            "ts": time.time(),
        }


def format_runtime_control_result(result: Dict[str, Any]) -> str:
    lines = [f"runtime {result['action']}: {'ok' if result.get('ok') else 'failed'}"]
    for step in result.get("steps", []):
        marker = "ok" if step.get("ok") else "fail"
        lines.append(f"- {marker}: {step.get('name')} - {step.get('detail', '')}")
    return "\n".join(lines)
