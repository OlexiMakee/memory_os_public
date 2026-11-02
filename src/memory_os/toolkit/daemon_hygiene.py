"""Background daemon hygiene snapshots for runtime truth and relay lag."""

from __future__ import annotations

import json
import shlex
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_os.toolkit.agent_registry import load_agent_registry
from memory_os.toolkit.multiplexer_manager import MultiplexerManager
from memory_os.toolkit.runtime_control import RuntimeControl
from memory_os.toolkit.task_kernel import TaskKernel


class DaemonHygiene:
    def __init__(self, root: Path, runtime_control: Optional[RuntimeControl] = None):
        self.root = root
        self.runtime_health_path = root / "agent_context" / "agents" / "runtime_health.json"
        self.relay_watch_path = root / "agent_context" / "agents" / "relay_watch.json"
        self.reconcile_state_path = root / "agent_context" / "agents" / "reconcile_state.json"
        self.runtime_control = runtime_control or RuntimeControl(root)

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    # Binaries that constitute a "live" agent process in a pane.
    # A pane whose current_command is not in this set is treated as a ghost.
    _AGENT_BINARIES: Dict[str, tuple[str, ...]] = {
        "claude": ("claude",),
        "codex": ("codex", "codex-code-mode-host"),
        "agy": ("agy",),
        "local": ("ollama",),
    }

    def _agent_pane_alive(self, agent_id: str, pane_command: str) -> bool:
        """Return True only when the pane is running the expected agent binary."""
        expected = self._AGENT_BINARIES.get(agent_id)
        if expected is None:
            return bool(pane_command) and pane_command not in ("bash", "sh", "zsh", "fish")
        try:
            executable = Path(shlex.split(pane_command)[0]).name
        except (ValueError, IndexError):
            return False
        return executable in expected

    def snapshot_runtime_health(self) -> Dict[str, Any]:
        mgr = MultiplexerManager(self.root)
        registry = load_agent_registry(self.root).get("agent", {})

        # --- session-level fault isolation -----------------------------------
        # If the multiplexer session is gone or unreachable, we must write an
        # explicit "all offline" snapshot so callers never read a stale cache.
        try:
            panes = mgr.list_panes(mgr.session_name)
            session_alive = bool(panes)
        except Exception as exc:
            payload = {
                "ts": time.time(),
                "runtime": getattr(mgr, "runtime", "unknown"),
                "session_name": getattr(mgr, "session_name", ""),
                "session_alive": False,
                "session_error": str(exc),
                "pane_count": 0,
                "agents": {
                    agent_id: {
                        "target_pane": "offline",
                        "is_active": False,
                        "is_working": False,
                        "is_ghost": False,
                        "pane_command": "",
                    }
                    for agent_id, spec in registry.items()
                    if spec.get("kind") == "cli_agent"
                },
            }
            self._write_json(self.runtime_health_path, payload)
            return payload
        # ---------------------------------------------------------------------

        # Build a lookup from target-string → pane for O(1) matching.
        pane_by_target: Dict[str, Any] = {str(p.target): p for p in panes}

        agents: Dict[str, Any] = {}
        for agent_id, spec in registry.items():
            if spec.get("kind") != "cli_agent":
                continue

            try:
                target = mgr.resolve_pane_target(agent_id)
            except Exception:
                target = agent_id

            pane = pane_by_target.get(str(target))

            # --- ghost detection ---------------------------------------------
            # A pane that exists in the multiplexer list but whose current
            # process is not the expected agent binary is a ghost: the slot is
            # occupied by a dead shell or an unrelated process.
            pane_command = pane.current_command if pane else ""
            pane_found = pane is not None
            pane_alive = pane_found and self._agent_pane_alive(agent_id, pane_command)
            is_ghost = pane_found and not pane_alive
            # -----------------------------------------------------------------

            is_working = False
            if pane_alive:
                try:
                    pane_text = mgr.capture_pane(target, lines=40)
                    from memory_os.toolkit.usage_probe import pane_is_idle
                    is_working = not pane_is_idle(pane_text)
                except Exception:
                    is_working = False

            agents[agent_id] = {
                "target_pane": target if pane_alive else "offline",
                "is_active": pane_alive,
                "is_working": is_working,
                "is_ghost": is_ghost,
                "pane_command": pane_command,
            }

        payload = {
            "ts": time.time(),
            "runtime": mgr.runtime,
            "session_name": mgr.session_name,
            "session_alive": session_alive,
            "pane_count": len(panes),
            "agents": agents,
        }
        self._write_json(self.runtime_health_path, payload)
        return payload

    def snapshot_relay_watch(self, done_lag_seconds: float = 300.0) -> Dict[str, Any]:
        done_dir = self.root / "agent_context" / "done"
        done_dir.mkdir(parents=True, exist_ok=True)
        kernel = TaskKernel(self.root)
        events = kernel.events()
        relayed_task_ids = {
            str(event.get("task_id", ""))
            for event in events
            if event.get("event") == "daemon.done_relay"
        }
        pending_done: List[Dict[str, Any]] = []
        now = time.time()
        for path in sorted(done_dir.glob("*.json")):
            task_id = path.stem
            if task_id in relayed_task_ids:
                continue
            age_seconds = max(0.0, now - path.stat().st_mtime)
            pending_done.append({
                "task_id": task_id,
                "path": str(path),
                "age_seconds": round(age_seconds, 1),
                "lagging": age_seconds >= done_lag_seconds,
            })
        stale_leases = kernel.stale_leases()
        payload = {
            "ts": now,
            "pending_done_count": len(pending_done),
            "lagging_done_count": sum(1 for item in pending_done if item["lagging"]),
            "pending_done": pending_done[:20],
            "stale_lease_count": len(stale_leases),
            "stale_leases": stale_leases[:20],
        }
        self._write_json(self.relay_watch_path, payload)
        return payload

    def check_telegram_daemon(self, stale_after_seconds: float = 120.0) -> Dict[str, Any]:
        """Restart the telegram-chat pane if it exited or its process is gone.

        Symmetric to telegram_polling._watch_core_daemon (which restarts the
        core daemon from the telegram side) — closes the mutual-watchdog loop
        so neither half of the swarm relay can silently die unnoticed.
        """
        mgr = MultiplexerManager(self.root)
        panes = mgr.list_panes(mgr.session_name)
        if not panes:
            # No live workspace session at all (daemon running standalone,
            # outside a tmux/zellij launch) — nothing to watch or restart.
            return {"checked": False, "reason": "no workspace session"}

        target = mgr.resolve_pane_target("telegram-chat")
        pane = next((p for p in panes if str(p.target) == str(target)), None)
        alive = bool(pane) and "telegram-daemon" in (pane.current_command or "")
        if alive:
            return {"checked": True, "alive": True}

        try:
            step = self.runtime_control.restart_pane("telegram-chat")
            result = {"checked": True, "alive": False, "restarted": step.ok}
            if not step.ok:
                result["error"] = step.detail
            return result
        except Exception as exc:
            return {"checked": True, "alive": False, "restarted": False, "error": str(exc)}

    def reconcile_agent_panes(
        self,
        runtime_health: Dict[str, Any],
        cooldown_seconds: float = 300.0,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "checked": bool(runtime_health.get("session_alive")),
            "ghost_agents": [],
            "restarted": [],
            "failed": [],
            "protected": [],
            "cooldown": [],
        }
        if not result["checked"]:
            result["reason"] = "no workspace session"
            return result

        agents = runtime_health.get("agents", {})
        if not isinstance(agents, dict):
            return result
        ghost_agents = [
            agent_id
            for agent_id, status in agents.items()
            if isinstance(status, dict) and status.get("is_ghost") is True
        ]
        result["ghost_agents"] = ghost_agents
        state = self._read_json(self.reconcile_state_path)
        now = time.time()
        changed = False

        for agent_id in ghost_agents:
            if agent_id == "claude":
                result["protected"].append(agent_id)
                continue
            entry = state.get(agent_id, {}) if isinstance(state.get(agent_id), dict) else {}
            last_attempt = float(entry.get("last_attempt", 0.0))
            if now - last_attempt < cooldown_seconds:
                result["cooldown"].append(agent_id)
                continue
            try:
                step = self.runtime_control.restart_pane(agent_id)
            except Exception as exc:
                step = None
                detail = str(exc)
            else:
                detail = step.detail
            ok = bool(step and step.ok)
            state[agent_id] = {
                "last_attempt": now,
                "ok": ok,
                "detail": detail,
            }
            changed = True
            if ok:
                result["restarted"].append(agent_id)
            else:
                result["failed"].append({"agent_id": agent_id, "detail": detail})

        if changed:
            self._write_json(self.reconcile_state_path, state)
        return result


    def snapshot_inbox_watchdog(self, lag_seconds: float = 300.0) -> Dict[str, Any]:
        inbox_dir = self.root / "agent_context" / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        now = time.time()
        pending = []
        for path in sorted(inbox_dir.glob("*.jsonl")):
            age_seconds = max(0.0, now - path.stat().st_mtime)
            pending.append({
                "file": path.name,
                "age_seconds": round(age_seconds, 1),
                "lagging": age_seconds >= lag_seconds
            })
        
        payload = {
            "ts": now,
            "pending_count": len(pending),
            "lagging_count": sum(1 for item in pending if item["lagging"]),
            "pending": pending[:20]
        }
        self._write_json(self.root / "agent_context" / "agents" / "inbox_watch.json", payload)
        return payload

    def resource_guard_preflight(self, effort: str) -> bool:
        """Return False if system is too loaded to run a high effort task."""
        if effort.lower() != "high":
            return True
        try:
            import psutil
            import os
            # If load avg > number of CPUs, system is heavily loaded
            if hasattr(os, "getloadavg"):
                load1, load5, load15 = os.getloadavg()
                cpu_count = psutil.cpu_count() or 4
                if load1 > cpu_count * 1.5:
                    return False
            # Check memory
            mem = psutil.virtual_memory()
            if mem.percent > 90.0:
                return False
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)
        return True

    def run_once(self) -> Dict[str, Any]:
        runtime_health = self.snapshot_runtime_health()
        return {
            "runtime_health": runtime_health,
            "agent_reconciler": self.reconcile_agent_panes(runtime_health),
            "relay_watch": self.snapshot_relay_watch(),
            "telegram_daemon": self.check_telegram_daemon(),
            "inbox_watchdog": self.snapshot_inbox_watchdog(),
        }
