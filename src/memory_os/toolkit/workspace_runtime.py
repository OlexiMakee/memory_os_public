"""Workspace runtime backends.

tmux and Zellij are the rich Unix UI runtimes. File runtime is the portable
baseline for Windows/headless operation: it materializes the workspace plan
and relies on file-backed AgentComm delivery instead of panes.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class WorkspacePaneSpec:
    key: str
    label: str
    command: List[str]
    kind: str = "agent"


@dataclass
class WorkspaceSpec:
    root: Path
    session_name: str
    panes: List[WorkspacePaneSpec]
    venv: bool = False


@dataclass(frozen=True)
class WorkspaceMenuResult:
    handled: bool
    message: str = ""


class WorkspaceRuntime(Protocol):
    name: str

    def is_available(self) -> bool:
        ...

    def launch(self, spec: WorkspaceSpec, *, attach: bool = True) -> None:
        ...

    def attach(self, session_name: str) -> None:
        ...

    def status(self, spec: WorkspaceSpec) -> dict:
        ...

    def stop(self, spec: WorkspaceSpec, *, force: bool = False) -> dict:
        ...

    def stop_all(self) -> dict:
        ...


def _write_file_runtime_state(spec: WorkspaceSpec, runtime: str) -> Path:
    runtime_dir = spec.root / "agent_context" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    state_path = runtime_dir / f"{spec.session_name}.json"
    payload = {
        "runtime": runtime,
        "session_name": spec.session_name,
        "root": str(spec.root),
        "panes": [
            {
                "key": pane.key,
                "label": pane.label,
                "command": pane.command,
                "kind": pane.kind,
            }
            for pane in spec.panes
        ],
    }
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return state_path


class FileWorkspaceRuntime:
    name = "file"

    def is_available(self) -> bool:
        return True

    def launch(self, spec: WorkspaceSpec, *, attach: bool = True) -> None:
        _write_file_runtime_state(spec, self.name)

    def attach(self, session_name: str) -> None:
        return None

    def status(self, spec: WorkspaceSpec) -> dict:
        state_path = spec.root / "agent_context" / "runtime" / f"{spec.session_name}.json"
        return {
            "runtime": self.name,
            "session": spec.session_name,
            "state_file": str(state_path),
            "available": state_path.exists(),
        }

    def stop(self, spec: WorkspaceSpec, *, force: bool = False) -> dict:
        state_path = spec.root / "agent_context" / "runtime" / f"{spec.session_name}.json"
        state_path.unlink(missing_ok=True)
        return {
            "runtime": self.name,
            "session": spec.session_name,
            "ok": True,
            "detail": f"removed {state_path}",
        }

    def stop_all(self) -> dict:
        return {"runtime": self.name, "ok": True, "detail": "no runtime sessions"}


class TmuxWorkspaceRuntime:
    name = "tmux"

    def is_available(self) -> bool:
        return shutil.which("tmux") is not None

    def _tmux(self, *args: str) -> None:
        subprocess.run(["tmux", *args], check=False)

    def _init_pane(self, target: str, root: Path, cmd: List[str], label: str, venv: bool) -> None:
        from memory_os.toolkit.project_secrets import unset_shell_exports

        parts = []
        term = os.environ.get("TERM", "xterm-256color")
        if term == "dumb":
            term = "xterm-256color"
        parts.append(f"export TERM={shlex.quote(term)}")

        for var in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY"):
            val = os.environ.get(var)
            if val:
                parts.append(f"export {var}={shlex.quote(val)}")

        parts.append(unset_shell_exports())
        parts.append(f"cd {shlex.quote(str(root))}")
        if venv:
            parts.append("source .venv/bin/activate")
        if cmd:
            parts.append(shlex.join(cmd))
        self._tmux("send-keys", "-t", target, " && ".join(parts), "Enter")
        self._tmux("set-option", "-p", "-t", target, "@agent_label", label)

    def attach(self, session_name: str) -> None:
        if os.environ.get("TMUX"):
            subprocess.run(["tmux", "switch-client", "-t", session_name])
            raise SystemExit(0)
        os.execvp("tmux", ["tmux", "attach-session", "-t", session_name])

    def launch(self, spec: WorkspaceSpec, *, attach: bool = True) -> None:
        if not self.is_available():
            raise RuntimeError("tmux not found in PATH")

        _write_file_runtime_state(spec, self.name)
        result = subprocess.run(["tmux", "has-session", "-t", spec.session_name], capture_output=True)
        if result.returncode == 0:
            if not attach:
                return
            self.attach(spec.session_name)

        subprocess.run(
            ["tmux", "new-session", "-d", "-s", spec.session_name, "-n", "agents"],
            check=True,
        )

        if not spec.panes:
            return

        self._init_pane(
            f"{spec.session_name}:agents.0",
            spec.root,
            spec.panes[0].command,
            spec.panes[0].label,
            spec.venv,
        )

        for idx, pane in enumerate(spec.panes[1:], start=1):
            split = "-v" if pane.kind in ("telegram", "manager") else "-h"
            self._tmux("split-window", split, "-t", f"{spec.session_name}:agents.{idx - 1}")
            self._init_pane(
                f"{spec.session_name}:agents.{idx}",
                spec.root,
                pane.command,
                pane.label,
                spec.venv,
            )

        self._tmux("set-option", "-t", spec.session_name, "pane-border-status", "top")
        self._tmux(
            "set-option",
            "-t",
            spec.session_name,
            "pane-border-format",
            "#[fg=white,bg=blue,bold] #{@agent_label} #[default]",
        )
        self._tmux("set-option", "-t", spec.session_name, "allow-rename", "off")
        self._tmux("bind-key", "Tab", "select-pane", "-t", ":.+")
        self._tmux("bind-key", "-n", "F2", "select-pane", "-t", ":.+")

        self._tmux("new-window", "-t", spec.session_name, "-n", "feed")
        self._init_pane(
            f"{spec.session_name}:feed",
            spec.root,
            [sys.executable, "-m", "memory_os", "feed"],
            "live-feed",
            spec.venv,
        )

        self._tmux("select-window", "-t", f"{spec.session_name}:agents")
        self._tmux("select-pane", "-t", f"{spec.session_name}:agents.0")

        if not attach:
            return
        self.attach(spec.session_name)

    def status(self, spec: WorkspaceSpec) -> dict:
        if not self.is_available():
            return {"runtime": self.name, "available": False}
        result = subprocess.run(
            ["tmux", "ls", "-F", "#{session_name}\t#{session_windows}\t#{session_attached}"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if parts and parts[0] == spec.session_name:
                return {
                    "runtime": self.name,
                    "session": parts[0],
                    "windows": int(parts[1]) if len(parts) > 1 else 0,
                    "attached": parts[2] == "1" if len(parts) > 2 else False,
                    "available": True,
                }
        return {"runtime": self.name, "session": spec.session_name, "available": False}

    def stop(self, spec: WorkspaceSpec, *, force: bool = False) -> dict:
        status = self.status(spec)
        if not status.get("available"):
            return {
                "runtime": self.name,
                "session": spec.session_name,
                "ok": True,
                "detail": f"{spec.session_name} not running",
            }
        result = subprocess.run(
            ["tmux", "kill-session", "-t", spec.session_name],
            capture_output=True,
            text=True,
        )
        detail = (result.stdout + result.stderr).strip() or f"{spec.session_name} stopped"
        return {
            "runtime": self.name,
            "session": spec.session_name,
            "ok": result.returncode == 0,
            "detail": detail,
        }

    def stop_all(self) -> dict:
        result = subprocess.run(["tmux", "kill-server"])
        return {"runtime": self.name, "ok": result.returncode == 0, "detail": "all sessions stopped"}


def _zellij_env() -> dict:
    env = dict(os.environ)
    uid = getattr(os, "getuid", lambda: 1000)()
    env["ZELLIJ_SOCKET_DIR"] = f"/tmp/zellij-{uid}"
    if env.get("TERM") == "dumb" or not env.get("TERM"):
        env["TERM"] = "xterm-256color"
    return env


class ZellijWorkspaceRuntime:
    name = "zellij"

    def is_available(self) -> bool:
        return shutil.which("zellij") is not None

    def exited_sessions(self) -> List[str]:
        if not self.is_available():
            return []
        res = subprocess.run(["zellij", "list-sessions", "--no-formatting"], capture_output=True, text=True, env=_zellij_env())
        sessions: List[str] = []
        for line in res.stdout.splitlines():
            clean = line.strip()
            if not clean or "(EXITED" not in clean:
                continue
            parts = clean.split(maxsplit=1)
            if parts:
                sessions.append(parts[0])
        return sessions

    def clean_exited_sessions(self, *, apply: bool = False) -> dict:
        sessions = self.exited_sessions()
        deleted: List[str] = []
        if apply:
            for session in sessions:
                subprocess.run(["zellij", "delete-session", session, "--force"], check=False, env=_zellij_env())
                deleted.append(session)
        return {
            "runtime": self.name,
            "apply": apply,
            "exited_sessions": sessions,
            "deleted": deleted,
        }

    def attach(self, session_name: str) -> None:
        os.execvpe("zellij", ["zellij", "attach", session_name], _zellij_env())

    def launch(self, spec: WorkspaceSpec, *, attach: bool = True) -> None:
        if not self.is_available():
            raise RuntimeError("zellij not found in PATH")
        
        # Ensure zellij configuration exists and disables startup modals
        config_dir = Path.home() / ".config" / "zellij"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "config.kdl"
        if not config_file.exists():
            config_file.write_text("show_release_notes false\nshow_startup_tips false\n", encoding="utf-8")
            
        _write_file_runtime_state(spec, self.name)

        # Reuse active sessions, but delete exited ones to avoid resurrecting suspended panes.
        res = subprocess.run(["zellij", "list-sessions", "--no-formatting"], capture_output=True, text=True, env=_zellij_env())
        session_lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        matched_line = next((line for line in session_lines if line.split(maxsplit=1)[0] == spec.session_name), "")
        if matched_line:
            if "(EXITED" in matched_line:
                subprocess.run(["zellij", "delete-session", spec.session_name, "--force"], check=False, env=_zellij_env())
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    refresh = subprocess.run(["zellij", "list-sessions", "--no-formatting"], capture_output=True, text=True, env=_zellij_env())
                    if not any(
                        line.strip().split(maxsplit=1)[0] == spec.session_name
                        for line in refresh.stdout.splitlines()
                        if line.strip()
                    ):
                        break
                    time.sleep(0.1)
            elif attach:
                self.attach(spec.session_name)
                return
            else:
                return

        # Generate KDL layout
        layout_dir = spec.root / "agent_context" / "runtime"
        layout_dir.mkdir(parents=True, exist_ok=True)
        layout_path = layout_dir / f"{spec.session_name}.kdl"
        user_layout_path = layout_dir / f"{spec.session_name}_user.kdl"

        if user_layout_path.exists():
            kdl_content = user_layout_path.read_text(encoding="utf-8")
            kdl_content = kdl_content.replace("start_suspended true", "start_suspended false")
        else:
            kdl_content = self._generate_kdl_layout(spec)

        layout_path.write_text(kdl_content, encoding="utf-8")

        if not attach:
            # Launch daemonized
            subprocess.Popen(
                ["zellij", "--new-session-with-layout", str(layout_path), "--session", spec.session_name],
                start_new_session=True,
                env=_zellij_env(),
            )
            return

        os.execvpe("zellij", ["zellij", "--new-session-with-layout", str(layout_path), "--session", spec.session_name], _zellij_env())

    def _generate_kdl_layout(self, spec: WorkspaceSpec) -> str:
        agent_items = [
            self._pane_kdl(pane, spec)
            for pane in spec.panes
            if pane.kind not in ("telegram", "manager")
        ]
        management_items = [
            self._pane_kdl(pane, spec)
            for pane in spec.panes
            if pane.kind in ("telegram", "manager")
        ]

        blocks = []
        if agent_items:
            blocks.append(f"""            pane name="Agents" split_direction="Vertical" {{
{chr(10).join(agent_items)}
            }}""")
        if management_items:
            blocks.append(f"""            pane name="Management" split_direction="Horizontal" size="40%" {{
{chr(10).join(management_items)}
            }}""")

        inner_content = "\n".join(blocks) if blocks else "            pane name=\"Console\""

        return f"""layout {{
    default_tab_template name="orchestrator_workspace" {{
        pane size=1 borderless=true {{
            plugin location="zellij:compact-bar"
        }}
        children
        pane size=1 borderless=true {{
            plugin location="zellij:status-bar"
        }}
    }}

    tab name="Memory OS Workspace" focus=true {{
        pane split_direction="vertical" {{
{inner_content}
        }}
    }}
}}
"""

    def _pane_kdl(self, pane: WorkspacePaneSpec, spec: WorkspaceSpec) -> str:
        from memory_os.toolkit.project_secrets import unset_shell_exports

        parts = []
        for var in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY"):
            val = os.environ.get(var)
            if val:
                parts.append(f"export {var}={shlex.quote(val)}")

        parts.append(unset_shell_exports())
        parts.append(f"cd {shlex.quote(str(spec.root))}")
        if spec.venv:
            parts.append("source .venv/bin/activate")
        if pane.command:
            parts.append(shlex.join(pane.command))
        cmd_str = " && ".join(parts)
        return f"""                pane name="{self._kdl_string(pane.key)}" command="bash" {{
                    start_suspended false
                    args "-lc" "{self._kdl_string(cmd_str)}"
                }}"""

    @staticmethod
    def _kdl_string(value: str) -> str:
        return (
            str(value)
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )

    def status(self, spec: WorkspaceSpec) -> dict:
        state_path = spec.root / "agent_context" / "runtime" / f"{spec.session_name}.json"
        base = {
            "runtime": self.name,
            "session": spec.session_name,
            "state_file": str(state_path),
            "available": False,
            "state": "missing",
        }
        if not self.is_available():
            return base

        res = subprocess.run(
            ["zellij", "list-sessions", "--no-formatting"],
            capture_output=True,
            text=True,
            env=_zellij_env(),
        )
        for line in res.stdout.splitlines():
            clean = line.strip()
            if not clean:
                continue
            parts = clean.split(maxsplit=1)
            if not parts or parts[0] != spec.session_name:
                continue
            if "(EXITED" in clean:
                return {**base, "available": False, "state": "exited", "detail": clean}
            return {**base, "available": True, "state": "running", "detail": clean}

        return {
            **base,
            "available": False,
            "state": "stale_state_file" if state_path.exists() else "missing",
        }

    def stop(self, spec: WorkspaceSpec, *, force: bool = False) -> dict:
        status = self.status(spec)
        if not status.get("available") and status.get("state") != "exited":
            return {
                "runtime": self.name,
                "session": spec.session_name,
                "ok": True,
                "detail": f"{spec.session_name} not running",
            }
        result = subprocess.run(
            ["zellij", "delete-session", spec.session_name, "--force"],
            capture_output=True,
            text=True,
            env=_zellij_env(),
        )
        detail = (result.stdout + result.stderr).strip() or f"{spec.session_name} stopped"
        return {
            "runtime": self.name,
            "session": spec.session_name,
            "ok": result.returncode == 0,
            "detail": detail,
        }

    def stop_all(self) -> dict:
        result = subprocess.run(["zellij", "kill-all-sessions", "--yes"], env=_zellij_env())
        return {"runtime": self.name, "ok": result.returncode == 0, "detail": "all sessions stopped"}


def select_workspace_runtime(name: str = "auto") -> WorkspaceRuntime:
    selected = (name or "auto").strip().lower()
    if selected == "file":
        return FileWorkspaceRuntime()
    if selected == "tmux":
        return TmuxWorkspaceRuntime()
    if selected == "zellij":
        return ZellijWorkspaceRuntime()
    
    # Auto fallback
    zellij = ZellijWorkspaceRuntime()
    if zellij.is_available():
        return zellij
    tmux = TmuxWorkspaceRuntime()
    if tmux.is_available():
        return tmux
    return FileWorkspaceRuntime()


def handle_workspace_menu_action(target: object) -> Optional[WorkspaceMenuResult]:
    if not isinstance(target, str):
        return None
    action, separator, value = target.partition(":")
    if separator and action in {"ATTACH", "ATTACH_TMUX", "ATTACH_ZELLIJ"}:
        runtime_name = "zellij" if action == "ATTACH_ZELLIJ" else "tmux"
        select_workspace_runtime(runtime_name).attach(value)
        return WorkspaceMenuResult(handled=True)
    if target in {"KILL_ALL_SESSIONS", "KILL_ALL_TMUX_SESSIONS"}:
        select_workspace_runtime("tmux").stop_all()
        return WorkspaceMenuResult(
            handled=True,
            message="All running tmux sessions have been killed.",
        )
    if target == "KILL_ALL_ZELLIJ_SESSIONS":
        select_workspace_runtime("zellij").stop_all()
        return WorkspaceMenuResult(
            handled=True,
            message="All running zellij sessions have been killed.",
        )
    return None


def workspace_runtime_diagnostics(spec: WorkspaceSpec) -> Dict[str, Any]:
    runtimes: Dict[str, Dict[str, Any]] = {}
    for runtime in (TmuxWorkspaceRuntime(), ZellijWorkspaceRuntime()):
        runtimes[runtime.name] = runtime.status(spec)

    zellij = ZellijWorkspaceRuntime()
    exited_zellij_sessions = zellij.exited_sessions()
    return {
        "session": spec.session_name,
        "runtimes": runtimes,
        "zellij_exited_sessions": exited_zellij_sessions,
    }
