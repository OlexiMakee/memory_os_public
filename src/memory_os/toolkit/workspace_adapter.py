"""Unified Workspace Multiplexer Adapter for tmux and Zellij."""

import abc
import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class PaneGeometry:
    width: int
    height: int
    x: Optional[int] = None
    y: Optional[int] = None

    def model_dump(self) -> Dict[str, Any]:
        return asdict(self)

    def dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PaneState:
    pane_id: str
    title: str
    is_active: bool
    is_focused: bool
    geometry: PaneGeometry
    command: Optional[str] = None
    cwd: Optional[str] = None

    def model_dump(self) -> Dict[str, Any]:
        return asdict(self)

    def dict(self) -> Dict[str, Any]:
        return asdict(self)


class MultiplexerAdapter(abc.ABC):
    """Abstract system interface for terminal multiplexer interaction."""

    @abc.abstractmethod
    def initialize_session(self, session_name: str, layout_content: Optional[str] = None) -> bool:
        """Create a new isolated multiplexer session."""
        pass

    @abc.abstractmethod
    def get_workspace_state(self, session_name: str) -> List[PaneState]:
        """Return the complete structured state of all panes in the session."""
        pass

    @abc.abstractmethod
    def spawn_worker_pane(self, session_name: str, command: List[str], alias: str) -> str:
        """Spawn a new pane with a command and log name."""
        pass

    @abc.abstractmethod
    def inject_input(self, session_name: str, pane_id: str, data: str, use_bracketed_paste: bool = True) -> None:
        """Reliably inject keys, text, or ctrl sequences into a pane."""
        pass

    @abc.abstractmethod
    def inject_keys(self, session_name: str, pane_id: str, keys: List[str]) -> None:
        """Inject a sequence of keys (including special keys) into a pane."""
        pass


    @abc.abstractmethod
    def capture_pane_buffer(self, session_name: str, pane_id: str, full_history: bool = False) -> str:
        """Read stdout from pane without ANSI codes."""
        pass

    @abc.abstractmethod
    def terminate_pane(self, session_name: str, pane_id: str) -> bool:
        """Force close target pane by ID."""
        pass


class TmuxAdapter(MultiplexerAdapter):
    """tmux implementation of MultiplexerAdapter."""

    def initialize_session(self, session_name: str, layout_content: Optional[str] = None) -> bool:
        if shutil.which("tmux") is None:
            return False
        res = subprocess.run(["tmux", "has-session", "-t", session_name], capture_output=True)
        if res.returncode == 0:
            return True
        subprocess.run(["tmux", "new-session", "-d", "-s", session_name], check=True)
        return True

    def get_workspace_state(self, session_name: str) -> List[PaneState]:
        if shutil.which("tmux") is None:
            return []
        # Format string to capture pane details
        fmt = "#{pane_id}\t#{pane_title}\t#{pane_active}\t#{pane_width}\t#{pane_height}\t#{pane_current_command}\t#{pane_current_path}"
        res = subprocess.run(["tmux", "list-panes", "-t", session_name, "-F", fmt], capture_output=True, text=True)
        if res.returncode != 0:
            return []
        
        states = []
        for line in res.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            states.append(PaneState(
                pane_id=parts[0],
                title=parts[1],
                is_active=(parts[2] == "1"),
                is_focused=(parts[2] == "1"),
                geometry=PaneGeometry(width=int(parts[3]), height=int(parts[4])),
                command=parts[5],
                cwd=parts[6]
            ))
        return states

    def spawn_worker_pane(self, session_name: str, command: List[str], alias: str) -> str:
        # Split vertical or horizontal as default
        cmd = ["tmux", "split-window", "-d", "-t", f"{session_name}:0.0", "-P", "-F", "#{pane_id}"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        pane_id = res.stdout.strip()
        if not pane_id:
            raise RuntimeError("Failed to split window in tmux")
        # Apply label
        subprocess.run(["tmux", "set-option", "-p", "-t", pane_id, "@agent_label", alias])
        if command:
            import shlex
            subprocess.run(["tmux", "send-keys", "-t", pane_id, shlex.join(command), "Enter"])
        return pane_id

    def inject_input(self, session_name: str, pane_id: str, data: str, use_bracketed_paste: bool = True) -> None:
        # Avoid premature execution by loading buffer for multiline text
        if "\n" in data and use_bracketed_paste:
            # Load to tmux buffer first
            subprocess.run(["tmux", "load-buffer", "-b", "temp_buf", "-"], input=data.encode("utf-8"), check=True)
            subprocess.run(["tmux", "paste-buffer", "-p", "-d", "-b", "temp_buf", "-t", pane_id], check=True)
        else:
            subprocess.run(["tmux", "send-keys", "-t", pane_id, "-l", data], check=True)

    def inject_keys(self, session_name: str, pane_id: str, keys: List[str]) -> None:
        special_keys = {
            "up": "Up",
            "down": "Down",
            "left": "Left",
            "right": "Right",
            "enter": "Enter",
            "escape": "Escape",
            "esc": "Escape",
            "tab": "Tab",
            "backspace": "BSpace",
            "space": "Space",
            "pageup": "PPage",
            "pagedown": "NPage",
        }
        for key in keys:
            key_lower = key.lower()
            if key_lower in special_keys:
                subprocess.run(["tmux", "send-keys", "-t", pane_id, special_keys[key_lower]], check=True)
            else:
                subprocess.run(["tmux", "send-keys", "-t", pane_id, "-l", key], check=True)
            time.sleep(0.05)


    def capture_pane_buffer(self, session_name: str, pane_id: str, full_history: bool = False) -> str:
        cmd = ["tmux", "capture-pane", "-t", pane_id, "-p"]
        if full_history:
            cmd.extend(["-S", "-1000"])
        res = subprocess.run(cmd, capture_output=True, text=True)
        # Strip ANSI codes using simple regex filter
        import re
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', res.stdout)

    def terminate_pane(self, session_name: str, pane_id: str) -> bool:
        res = subprocess.run(["tmux", "kill-pane", "-t", pane_id], capture_output=True)
        return res.returncode == 0


class ZellijAdapter(MultiplexerAdapter):
    """Zellij implementation of MultiplexerAdapter."""

    def initialize_session(self, session_name: str, layout_content: Optional[str] = None) -> bool:
        if shutil.which("zellij") is None:
            return False
        from memory_os.toolkit.workspace_runtime import _zellij_env
        res = subprocess.run(["zellij", "list-sessions", "--no-formatting"], capture_output=True, text=True, env=_zellij_env())
        session_lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        matched_line = next((line for line in session_lines if line.split(maxsplit=1)[0] == session_name), "")
        if matched_line:
            if "(EXITED" not in matched_line:
                return True
            subprocess.run(["zellij", "delete-session", session_name, "--force"], check=False, env=_zellij_env())
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                refresh = subprocess.run(["zellij", "list-sessions", "--no-formatting"], capture_output=True, text=True, env=_zellij_env())
                if not any(
                    line.strip().split(maxsplit=1)[0] == session_name
                    for line in refresh.stdout.splitlines()
                    if line.strip()
                ):
                    break
                time.sleep(0.1)
        
        # If KDL layout is provided, save to tmp and run session with layout
        if layout_content:
            layout_path = Path("/tmp") / f"zellij_{session_name}.kdl"
            layout_path.write_text(layout_content, encoding="utf-8")
            # Start zellij daemonized
            subprocess.Popen(["zellij", "--new-session-with-layout", str(layout_path), "--session", session_name], start_new_session=True, env=_zellij_env())
            return True
        else:
            subprocess.Popen(["zellij", "--session", session_name], start_new_session=True, env=_zellij_env())
            return True

    def get_workspace_state(self, session_name: str) -> List[PaneState]:
        if shutil.which("zellij") is None:
            return []
        
        from memory_os.toolkit.workspace_runtime import _zellij_env
        try:
            res = subprocess.run(["zellij", "--session", session_name, "action", "list-panes", "--json"], capture_output=True, text=True, timeout=5.0, env=_zellij_env())
            if res.returncode == 0:
                data = json.loads(res.stdout)
                states = []
                for item in data:
                    if item.get("is_plugin"):
                        continue
                    states.append(PaneState(
                        pane_id=str(item.get("id", "")),
                        title=item.get("title") or item.get("name", "pane"),
                        is_active=item.get("is_active", False) and not item.get("exited", False),
                        is_focused=item.get("is_focused", False),
                        geometry=PaneGeometry(width=item.get("pane_columns", 80), height=item.get("pane_rows", 24)),
                        command=item.get("pane_command") or item.get("terminal_command"),
                        cwd=item.get("pane_cwd") or item.get("cwd"),
                    ))
                return states
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)
        return []

    def spawn_worker_pane(self, session_name: str, command: List[str], alias: str) -> str:
        from memory_os.toolkit.workspace_runtime import _zellij_env
        import shlex
        env_vars = []
        for key in ["API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "PYTHONPATH", "PATH"]:
            if key in os.environ:
                env_vars.append(f"{key}={shlex.quote(os.environ[key])}")
        
        full_command = command
        if env_vars:
            full_command = ["env"] + env_vars + command

        cmd = ["zellij", "--session", session_name, "action", "new-pane", "--name", alias]
        if full_command:
            cmd.extend(["--", *full_command])
            
        res = subprocess.run(cmd, capture_output=True, text=True, env=_zellij_env())
        pane_id = res.stdout.strip() or alias
        return pane_id

    def inject_input(self, session_name: str, pane_id: str, data: str, use_bracketed_paste: bool = True) -> None:
        from memory_os.toolkit.workspace_runtime import _zellij_env
        env = _zellij_env()
        if "\n" in data and use_bracketed_paste:
            subprocess.run(["zellij", "--session", session_name, "action", "paste", "--pane-id", pane_id, data], check=True, env=env)
        else:
            subprocess.run(["zellij", "--session", session_name, "action", "write-chars", "--pane-id", pane_id, data], check=True, env=env)

    def inject_keys(self, session_name: str, pane_id: str, keys: List[str]) -> None:
        from memory_os.toolkit.workspace_runtime import _zellij_env
        env = _zellij_env()
        special_keys = {
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right",
            "enter": "Enter",
            "escape": "Esc",
            "esc": "Esc",
            "tab": "tab",
            "backspace": "backspace",
            "space": "space",
            "pageup": "page-up",
            "pagedown": "page-down",
        }
        for key in keys:
            key_lower = key.lower()
            if key_lower in special_keys:
                subprocess.run(
                    ["zellij", "--session", session_name, "action", "send-keys", "--pane-id", pane_id, special_keys[key_lower]],
                    check=False, env=env,
                )
            else:
                subprocess.run(
                    ["zellij", "--session", session_name, "action", "write-chars", "--pane-id", pane_id, key],
                    check=False, env=env,
                )
            time.sleep(0.05)


    def capture_pane_buffer(self, session_name: str, pane_id: str, full_history: bool = False) -> str:
        from memory_os.toolkit.workspace_runtime import _zellij_env
        env = _zellij_env()
        args = ["zellij", "--session", session_name, "action", "dump-screen", "--pane-id", pane_id]
        if full_history:
            args.append("--full")
        res = subprocess.run(args, capture_output=True, text=True, env=env)
        return res.stdout

    def terminate_pane(self, session_name: str, pane_id: str) -> bool:
        from memory_os.toolkit.workspace_runtime import _zellij_env
        env = _zellij_env()
        res = subprocess.run(["zellij", "--session", session_name, "action", "close-pane", "--pane-id", pane_id], capture_output=True, env=env)
        return res.returncode == 0
