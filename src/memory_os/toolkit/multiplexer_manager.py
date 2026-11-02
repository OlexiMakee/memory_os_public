"""Unified Multiplexer Automation and Control Toolkit for Memory OS.

Provides fast, reliable, and precise terminal session/pane manipulation,
shortcut execution, and guaranteed prompt submission for multi-agent swarms.
"""

from memory_os.toolkit.agent_registry import KNOWN_AGENTS
import os
import re
import shutil
import subprocess
import time
import abc
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Type


_WORKSPACE_STATE_TTL = 2.0
_WORKSPACE_STATE_CACHE: Dict[tuple, tuple] = {}


@dataclass
class MultiplexerPaneInfo:
    session: str
    window_index: int
    pane_index: int
    target: str
    width: int
    height: int
    active: bool
    current_command: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session": self.session,
            "window_index": self.window_index,
            "pane_index": self.pane_index,
            "target": self.target,
            "width": self.width,
            "height": self.height,
            "active": self.active,
            "current_command": self.current_command,
        }


class IMultiplexerBackend(abc.ABC):
    """Backend contract for multiplexer operations."""

    @abc.abstractmethod
    def list_panes(self, session: Optional[str] = None) -> List[MultiplexerPaneInfo]:
        raise NotImplementedError

    @abc.abstractmethod
    def capture_pane(self, target: str, lines: int = 50, full_history: bool = False) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    def send_keys(
        self,
        target: str,
        message: str,
        submit: bool = True,
        unlock_buffers: bool = True,
        delay_sec: float = 0.1,
    ) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def get_session_status(self, session: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError


class _BackendBase(IMultiplexerBackend):
    def __init__(self, manager: "MultiplexerManager"):
        self.manager = manager


class TmuxBackend(_BackendBase):
    def list_panes(self, session: Optional[str] = None) -> List[MultiplexerPaneInfo]:
        fmt = "#{session_name}:#{window_index}.#{pane_index}|#{pane_width}|#{pane_height}|#{pane_active}|#{pane_current_command}"
        cmd = ["list-panes", "-a", "-F", fmt] if not session else ["list-panes", "-t", session, "-F", fmt]
        proc = self.manager._run(cmd, check=False)
        if proc.returncode != 0 or not proc.stdout:
            return []

        panes: List[MultiplexerPaneInfo] = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = line.split("|")
            if len(parts) >= 5:
                target_id = parts[0]
                sess, win_pane = target_id.split(":", 1) if ":" in target_id else (target_id, "0.0")
                win_idx, pane_idx = win_pane.split(".", 1) if "." in win_pane else ("0", "0")
                panes.append(
                    MultiplexerPaneInfo(
                        session=sess,
                        window_index=int(win_idx),
                        pane_index=int(pane_idx),
                        target=target_id,
                        width=int(parts[1]) if parts[1].isdigit() else 80,
                        height=int(parts[2]) if parts[2].isdigit() else 24,
                        active=parts[3] == "1",
                        current_command=parts[4],
                    )
                )
        return panes

    def capture_pane(self, target: str, lines: int = 50, full_history: bool = False) -> str:
        resolved = self.manager.resolve_pane_target(target)
        args = ["capture-pane", "-pt", resolved]
        if full_history:
            args.extend(["-S", f"-{max(200, lines)}"])
        proc = self.manager._run(args, check=False)
        if proc.returncode != 0 or not proc.stdout:
            return ""
        output_lines = proc.stdout.splitlines()
        return "\n".join(output_lines[-lines:])

    def send_keys(
        self,
        target: str,
        message: str,
        submit: bool = True,
        unlock_buffers: bool = True,
        delay_sec: float = 0.1,
    ) -> None:
        resolved = self.manager.resolve_pane_target(target)
        base_target = ["-t", resolved]
        if unlock_buffers:
            self.manager._run(["send-keys", *base_target, "Escape"], check=False)
            self.manager._run(["send-keys", *base_target, "Enter"], check=False)
            if delay_sec > 0:
                time.sleep(delay_sec)

        if message:
            self.manager._run(["send-keys", *base_target, "-l", message], check=True)
            if delay_sec > 0:
                time.sleep(delay_sec)

        if submit:
            if delay_sec > 0:
                time.sleep(delay_sec)
            self.manager._run(["send-keys", *base_target, "Enter"], check=False)

    def get_session_status(self, session: Optional[str] = None) -> Dict[str, Any]:
        session_name = session or self.manager.session_name
        from memory_os.toolkit.workspace_runtime import TmuxWorkspaceRuntime

        return self.manager._workspace_runtime_status(TmuxWorkspaceRuntime(), session_name)


class ZellijBackend(_BackendBase):
    def list_panes(self, session: Optional[str] = None) -> List[MultiplexerPaneInfo]:
        session_name = session or self.manager.session_name
        states = self.manager.adapter.get_workspace_state(session_name)
        if not states:
            return self.manager._list_zellij_panes_from_runtime_state(session_name)
        return [
            MultiplexerPaneInfo(
                session=session_name,
                window_index=0,
                pane_index=idx,
                target=p.pane_id,
                width=p.geometry.width,
                height=p.geometry.height,
                active=p.is_active,
                current_command=p.command or "bash",
            )
            for idx, p in enumerate(states)
        ]

    def capture_pane(self, target: str, lines: int = 50, full_history: bool = False) -> str:
        resolved = self.manager.resolve_pane_target(target)
        buf = self.manager.adapter.capture_pane_buffer(self.manager.session_name, resolved, full_history=full_history)
        output_lines = buf.splitlines()
        return "\n".join(output_lines[-lines:])

    def send_keys(
        self,
        target: str,
        message: str,
        submit: bool = True,
        unlock_buffers: bool = True,
        delay_sec: float = 0.1,
    ) -> None:
        resolved = self.manager.resolve_pane_target(target)
        from memory_os.toolkit.workspace_runtime import _zellij_env

        env = _zellij_env()
        self.manager.adapter.inject_input(self.manager.session_name, resolved, message, use_bracketed_paste=True)
        if submit:
            if delay_sec > 0:
                time.sleep(delay_sec)
            subprocess.run(
                ["zellij", "--session", self.manager.session_name, "action", "send-keys", "--pane-id", resolved, "Enter"],
                check=False,
                env=env,
            )

    def get_session_status(self, session: Optional[str] = None) -> Dict[str, Any]:
        session_name = session or self.manager.session_name
        from memory_os.toolkit.workspace_runtime import ZellijWorkspaceRuntime

        return self.manager._workspace_runtime_status(ZellijWorkspaceRuntime(), session_name)


class MultiplexerManager:
    """High-level controller for terminal multiplexer automation, shortcut handling, and buffer dispatch."""

    # Zellij has no per-agent pane-index equivalent to tmux_target in
    # registry.toml, so this is the one place a default layout is guessed
    # when nothing else (live pane state, registry) resolves a target.
    # Previously duplicated as three independently-drifted dicts; keep this
    # the single source and verify against `memory_os tmux list` before
    # changing it, since the layout has been renumbered before.
    ZELLIJ_PANE_DEFAULTS: Dict[str, str] = {
        "claude": "0",
        "codex": "1",
        "agy": "2",
        "local": "3",
        "agent-manager": "4",
        "telegram-chat": "5",
        "live-feed": "6",
    }
    _ZELLIJ_INDEX_TO_AGENT: Dict[int, str] = {
        int(index): agent
        for agent, index in ZELLIJ_PANE_DEFAULTS.items()
        if agent in (*KNOWN_AGENTS, "local")
    }

    SHORTCUTS: Dict[str, List[str]] = {
        "cancel": ["C-c"],
        "clear": ["C-l"],
        "exit": ["C-d"],
        "detach": ["C-b", "d"],
        "toggle_auto": ["Btab"],  # Shift+Tab in tmux
        "escape": ["Escape"],
        "enter": ["Enter"],
        "page_up": ["PPage"],
        "page_down": ["NPage"],
        "next_window": ["n"],
        "previous_window": ["p"],
        "unlock": ["Escape", "Enter"],
    }



    def __init__(self, root: Optional[Path] = None, backend: Optional[IMultiplexerBackend] = None):
        self.root = root or Path.cwd()
        self.runtime = "tmux"
        self.session_name = "memory_os_workspace"
        
        # Load memory_os config for session name
        try:
            from memory_os.core.config import MemoryOSConfig
            config_file = self.root / "memory_os.config.json"
            if config_file.exists():
                cfg_obj = MemoryOSConfig(str(config_file))
                self.session_name = cfg_obj.tmux_session_name
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)

        state_path = self.root / "agent_context" / "runtime" / f"{self.session_name}.json"
        if state_path.exists():
            try:
                import json
                state = json.loads(state_path.read_text(encoding="utf-8"))
                self.runtime = state.get("runtime", "tmux")
            except Exception as _e:
                import sys as _sys
                print(f'Ignored exception: {_e}', file=_sys.stderr)

        from memory_os.toolkit.workspace_adapter import TmuxAdapter, ZellijAdapter
        if self.runtime == "zellij":
            self.adapter = ZellijAdapter()
        else:
            self.adapter = TmuxAdapter()
        self.backend = backend or self._select_backend()

    def _select_backend(self) -> IMultiplexerBackend:
        backend_cls: Type[IMultiplexerBackend] = ZellijBackend if self.runtime == "zellij" else TmuxBackend
        return backend_cls(self)

    @staticmethod
    def is_available() -> bool:
        return shutil.which("tmux") is not None or shutil.which("zellij") is not None

    def _run(self, args: List[str], check: bool = True) -> subprocess.CompletedProcess:
        if shutil.which("tmux") is None:
            raise FileNotFoundError("tmux binary is not installed or not found in PATH")
        return subprocess.run(["tmux", *args], capture_output=True, text=True, check=check)

    def _cached_workspace_state(self):
        # list-panes is a ~100ms subprocess; callers like comm status resolve
        # many targets in a row, so one snapshot per TTL window is enough
        key = (self.runtime, self.session_name)
        cached = _WORKSPACE_STATE_CACHE.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < _WORKSPACE_STATE_TTL:
            return cached[1]
        states = self.adapter.get_workspace_state(self.session_name)
        _WORKSPACE_STATE_CACHE[key] = (now, states)
        return states

    def get_session_status(self, session: Optional[str] = None) -> Dict[str, Any]:
        return self.backend.get_session_status(session)

    def _workspace_runtime_status(self, runtime: Any, session: str) -> Dict[str, Any]:
        from memory_os.toolkit.workspace_runtime import WorkspaceSpec

        status = runtime.status(WorkspaceSpec(root=self.root, session_name=session, panes=[]))
        return {**status, "running": bool(status.get("available"))}

    def resolve_pane_target(self, target: str) -> str:
        """Resolves target pane robustly using @agent_label/pane name, falling back to static targets."""
        if not target:
            return target

        if self.runtime == "zellij":
            # Map Tmux targets back to agent keys
            if ":" in target:
                parts = target.split(":")
                if len(parts) == 2:
                    suffix = parts[1]
                    if suffix.startswith("agents."):
                        try:
                            idx = int(suffix.split(".")[1])
                            if idx in self._ZELLIJ_INDEX_TO_AGENT:
                                target = self._ZELLIJ_INDEX_TO_AGENT[idx]
                        except Exception as _e:
                            import sys as _sys
                            print(f'Ignored exception: {_e}', file=_sys.stderr)
                    else:
                        try:
                            subparts = suffix.split(".")
                            idx = int(subparts[1]) if len(subparts) == 2 else int(subparts[0])
                            if idx in self._ZELLIJ_INDEX_TO_AGENT:
                                target = self._ZELLIJ_INDEX_TO_AGENT[idx]
                        except Exception as _e:
                            import sys as _sys
                            print(f'Ignored exception: {_e}', file=_sys.stderr)

            if target.isdigit():
                return target

            try:
                states = self._cached_workspace_state()
                for pane in states:
                    if pane.title == target or pane.pane_id == target:
                        return pane.pane_id
            except Exception as _e:
                import sys as _sys
                print(f'Ignored exception: {_e}', file=_sys.stderr)
            
            # Zellij-specific fallback mapping to prevent Tmux formats leaking
            if target in self.ZELLIJ_PANE_DEFAULTS:
                return self.ZELLIJ_PANE_DEFAULTS[target]
            return target

        if ":" in target or target.startswith("%") or target.isdigit():
            return target

        # tmux target resolution
        if shutil.which("tmux") is not None:
            try:
                proc = self._run(["list-panes", "-t", self.session_name, "-F", "#{pane_id} #{@agent_label}"], check=False)
                if proc.returncode == 0 and proc.stdout:
                    for line in proc.stdout.splitlines():
                        parts = line.strip().split(None, 1)
                        if len(parts) == 2:
                            pane_id, label = parts
                            if label.startswith(f"{target}:") or label == target:
                                return pane_id
            except Exception as _e:
                import sys as _sys
                print(f'Ignored exception: {_e}', file=_sys.stderr)

        # Fallback 1: registry.toml
        try:
            from memory_os.toolkit.agent_registry import load_agent_registry

            registry = load_agent_registry(self.root, fallback_to_main=True)
            agent_cfg = registry.get("agent", {}).get(target, {})
            for key in ("tmux_target", "tmux_session", "session"):
                val = agent_cfg.get(key)
                if val:
                    return str(val)
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)

        # Fallback 2: config.json mapping
        config_file = self.root / "memory_os.config.json"
        if config_file.exists():
            try:
                from memory_os.core.config import MemoryOSConfig
                cfg_obj = MemoryOSConfig(str(config_file))
                pane_idx = cfg_obj.agent_panes.get(target)
                if pane_idx is not None:
                    return f"{cfg_obj.tmux_session_name}:agents.{pane_idx}"
            except Exception as _e:
                import sys as _sys
                print(f'Ignored exception: {_e}', file=_sys.stderr)

        # Fallback 3: static defaults for testing / unconfigured workspaces
        defaults = {"claude": "0", "codex": "1"}
        if target in defaults:
            return defaults[target]

        return target

    def send_keys(
        self,
        target: str,
        message: str,
        submit: bool = True,
        unlock_buffers: bool = True,
        delay_sec: float = 0.1,
    ) -> None:
        """Send message text to a target reliably with backend delegation."""
        self.backend.send_keys(target, message, submit=submit, unlock_buffers=unlock_buffers, delay_sec=delay_sec)

    def send_shortcut(self, target: str, shortcut_name: str) -> bool:
        """Execute a predefined shortcut on target pane."""
        resolved = self.resolve_pane_target(target)
        if self.runtime == "zellij":
            from memory_os.toolkit.workspace_runtime import _zellij_env
            control_bytes = {"cancel": 3, "clear": 12, "escape": 27, "enter": 13}
            byte = control_bytes.get(shortcut_name.lower())
            if byte is None:
                return False
            proc = subprocess.run(
                ["zellij", "--session", self.session_name, "action", "write", "--pane-id", resolved, str(byte)],
                check=False, env=_zellij_env(),
            )
            return proc.returncode == 0

        keys = self.SHORTCUTS.get(shortcut_name.lower())
        if not keys:
            return False
        for key in keys:
            self._run(["send-keys", "-t", resolved, key], check=False)
        return True

    def send_key_sequence(self, target: str, keys: List[str], delay_sec: float = 0.05) -> None:
        """Sends a list of keys (standard characters or special keys like 'up', 'down', 'enter') to the target pane."""
        resolved = self.resolve_pane_target(target)
        self.adapter.inject_keys(self.session_name, resolved, keys)


    def capture_pane(self, target: str, lines: int = 50, full_history: bool = False) -> str:
        """Capture tail lines from target pane."""
        return self.backend.capture_pane(target, lines=lines, full_history=full_history)

    @classmethod
    def _zellij_default_target(cls, agent_key: str, pane_index: int) -> str:
        return cls.ZELLIJ_PANE_DEFAULTS.get(agent_key, str(pane_index))

    @staticmethod
    def _process_matches_command(command: List[Any], process_line: str) -> bool:
        if not command:
            return False
        tokens = [Path(str(command[0])).name]
        tokens.extend(str(arg) for arg in command[1:4])
        tokens = [token for token in tokens if token]
        return bool(tokens) and all(token in process_line for token in tokens)

    @staticmethod
    def _process_table_is_sandboxed(process_lines: List[str]) -> bool:
        return any("codex-linux-sandbox" in line or "bwrap --new-session" in line for line in process_lines)

    def _runtime_pane_info(self, session: str, pane: Dict[str, Any], idx: int) -> MultiplexerPaneInfo:
        command = pane.get("command") or []
        key = str(pane.get("key") or (Path(str(command[0])).name if command else idx))
        return MultiplexerPaneInfo(
            session=session,
            window_index=0,
            pane_index=idx,
            target=self._zellij_default_target(key, idx),
            width=80,
            height=24,
            active=True,
            current_command=key,
        )

    def _list_zellij_panes_from_runtime_state(self, session: str) -> List[MultiplexerPaneInfo]:
        state_path = self.root / "agent_context" / "runtime" / f"{session}.json"
        if not state_path.exists():
            return []
        try:
            import json
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if state.get("runtime") != "zellij":
            return []

        proc = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return []
        process_lines = proc.stdout.splitlines()

        is_sandboxed = self._process_table_is_sandboxed(process_lines)
        is_running = bool(self.get_session_status(session).get("running"))

        # Fix for orphaned processes: if we are unsandboxed and the zellij session
        # is definitively dead, do not return any panes.
        if not is_sandboxed and not is_running:
            return []

        if is_sandboxed and is_running:
            return [self._runtime_pane_info(session, pane, idx) for idx, pane in enumerate(state.get("panes", []))]

        panes: List[MultiplexerPaneInfo] = []
        pane_specs = state.get("panes", [])
        for idx, pane in enumerate(pane_specs):
            command = pane.get("command") or []
            if not any(self._process_matches_command(command, line) for line in process_lines):
                continue
            panes.append(self._runtime_pane_info(session, pane, idx))
        return panes

    def list_panes(self, session: Optional[str] = None) -> List[MultiplexerPaneInfo]:
        """List all available panes across sessions or for a specific session."""
        return self.backend.list_panes(session)
