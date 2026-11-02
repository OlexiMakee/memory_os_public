"""Interactive TUI Agent Quota & Launch Manager for Memory OS.

Allows checking agent limits, countdown timers, probing status, closing panes, and launching agent panes.
"""

import os
import json
import shlex
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any

from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.agent_registry import load_agent_registry
from memory_os.toolkit.multiplexer_manager import MultiplexerManager
from memory_os.toolkit.agent_health import AgentHealthProbe
from memory_os.toolkit.agent_limits import (
    agent_limit_active,
    format_agent_limit_summary,
    format_model_group_limit_summary,
    format_reset_timer,
    resolve_active_usage_state,
)
from memory_os.toolkit.runtime_control import RuntimeControl, format_runtime_control_result


def get_agent_timer(reset_at_str: Optional[Any]) -> str:
    return format_reset_timer(reset_at_str)


class AgentManagerTUI:
    def __init__(self, root: Path):
        self.root = root
        self.config = MemoryOSConfig(str(root / "memory_os.config.json"))
        self.tmux = MultiplexerManager(root)
        self.probe = AgentHealthProbe(root)

    def _runtime_health_cache(self) -> Dict[str, Any]:
        path = self.root / "agent_context" / "agents" / "runtime_health.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def get_agents_status(self) -> List[Dict[str, Any]]:
        try:
            from memory_os.toolkit.agent_console_scanner import AgentConsoleScanner
            AgentConsoleScanner(self.root, multiplexer=self.tmux).scan_once()
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)

        # Ensure latest cached health is available
        health_data = self.probe._load_cache()
        
        agents_reg = load_agent_registry(self.root).get("agent", {})

        # Load active quota monitor states (refreshes codex usage from rollout files, TTL-throttled)
        from memory_os.toolkit.quota_harvester import refresh_quota_state
        try:
            quota_state = refresh_quota_state(self.root)
        except Exception:
            quota_state = {}
        runtime_health = self._runtime_health_cache().get("agents", {})

        results = []
        for agent_id, spec in agents_reg.items():
            # Only manage CLI agents
            if spec.get("kind") != "cli_agent":
                continue

            health = health_data.get(agent_id, {})
            status = health.get("status", "unknown")
            detail = health.get("detail", "")
            
            cached_runtime = runtime_health.get(agent_id, {}) if isinstance(runtime_health.get(agent_id), dict) else {}
            target_pane = str(cached_runtime.get("target_pane", ""))
            is_active = bool(cached_runtime.get("is_active"))
            is_working = bool(cached_runtime.get("is_working"))
            if not target_pane:
                target_pane = self.tmux.resolve_pane_target(agent_id)
            if not is_active and target_pane.startswith("%"):
                is_active = True
            if not is_active:
                try:
                    panes = self.tmux.list_panes(self.tmux.session_name)
                    is_active = any(
                        str(p.target) == str(target_pane) or p.current_command == agent_id
                        for p in panes
                    )
                except Exception:
                    is_active = False

            # Resolve limit/timer (show resets timer whenever there is a future reset_at or usage resets_note)
            state = quota_state.get(agent_id, {})
            resolved_usage_state, active_group = resolve_active_usage_state(agent_id, state)
            effective_state = dict(state)
            if resolved_usage_state:
                effective_state["usage"] = resolved_usage_state
            if active_group:
                effective_state["active_model_group"] = active_group
                effective_state.pop("reset_at", None)
            if (
                status in ("quota_exhausted", "rate_limited")
                and effective_state.get("has_limit") is False
                and effective_state.get("usage_harvested_at")
            ):
                status = "ok"
                detail = "Quota available in latest usage snapshot"
                health = dict(health, status=status, detail=detail)
            limit_active = agent_limit_active(health=health, state=effective_state)
            
            from memory_os.toolkit.agent_limits import coerce_reset_datetime, format_reset_timer
            def get_window_reset_timer(w_data: dict) -> Optional[str]:
                if not isinstance(w_data, dict):
                    return None
                r_at = w_data.get("resets_at")
                if r_at:
                    from datetime import datetime, timezone
                    reset_dt = coerce_reset_datetime(r_at)
                    if reset_dt:
                        if reset_dt.tzinfo is None:
                            reset_dt = reset_dt.replace(tzinfo=timezone.utc)
                        if reset_dt > datetime.now(timezone.utc):
                            return format_reset_timer(r_at)
                r_note = w_data.get("resets_note")
                if r_note:
                    from memory_os.toolkit.quota_monitor import AgentQuotaMonitor
                    parsed_ts = AgentQuotaMonitor(self.root).parse_reset_time(r_note)
                    if parsed_ts:
                        from datetime import datetime, timezone
                        reset_dt = coerce_reset_datetime(parsed_ts)
                        if reset_dt:
                            if reset_dt.tzinfo is None:
                                reset_dt = reset_dt.replace(tzinfo=timezone.utc)
                            if reset_dt > datetime.now(timezone.utc):
                                return format_reset_timer(parsed_ts)
                return None

            usage_5h = effective_state.get("usage", {}).get("5h")
            r_5h = get_window_reset_timer(usage_5h)
            five_hour_disabled = (
                isinstance(usage_5h, dict)
                and (usage_5h.get("available") is False or usage_5h.get("status") == "disabled")
            )
            if not r_5h and not five_hour_disabled and limit_active and effective_state.get("reset_at"):
                from datetime import datetime, timezone
                reset_dt = coerce_reset_datetime(effective_state.get("reset_at"))
                if reset_dt:
                    if reset_dt.tzinfo is None:
                        reset_dt = reset_dt.replace(tzinfo=timezone.utc)
                    if reset_dt > datetime.now(timezone.utc):
                        r_5h = format_reset_timer(effective_state.get("reset_at"))

            r_week = get_window_reset_timer(effective_state.get("usage", {}).get("week"))
            
            limit_str = r_5h or r_week or ""
            limit_summary = format_agent_limit_summary(spec=spec, health=health, state=effective_state)
            model_group_summary = format_model_group_limit_summary(state)

            results.append({
                "id": agent_id,
                "name": agent_id,
                "command": spec.get("command", [agent_id]),
                "status": status,
                "detail": detail,
                "is_active": is_active,
                "is_working": is_working,
                "target_pane": target_pane if is_active else "offline",
                "limit_str": limit_str,
                "limit_active": limit_active,
                "limit_summary": limit_summary,
                "model_group_summary": model_group_summary,
                "r_5h": r_5h,
                "r_week": r_week,
            })
        return results

    def print_status(self) -> None:
        print("\nMemory OS - Agent Manager\n")
        agents = self.get_agents_status()

        print(f"{'Agent':<12}  {'Process':<13}  {'Limits':<28}")
        print("-" * 57)
        for agent in agents:
            if agent["is_active"]:
                state_lbl = "working" if agent.get("is_working") else "idle"
                proc_text = f"RUNNING ({agent['target_pane']}:{state_lbl})"
            else:
                proc_text = "STOPPED"
            print(f"{agent['id']:<12}  {proc_text:<20}  {agent['limit_summary']:<28}")
            
            r_5h = agent.get("r_5h")
            r_week = agent.get("r_week")

            resets = []
            if r_5h:
                clean_5h = r_5h.replace("resets in ", "")
                resets.append(f"5h resets in {clean_5h}")
            if r_week:
                clean_week = r_week.replace("resets in ", "")
                resets.append(f"week resets in {clean_week}")

            if resets:
                line2 = "  " + "  •  ".join(resets)
            else:
                line2 = f"  Detail: {agent.get('detail', 'Available')}"
            print(f"\033[2m{line2}\033[0m\n")
            if agent.get("model_group_summary"):
                print(f"\033[2m  Models: {agent['model_group_summary']}\033[0m\n")

    def launch_agent(self, agent: Dict[str, Any]) -> Tuple[bool, str]:
        agent_id = agent["id"]
        label = f"{agent_id}:{self.root.name}"
        
        # Resolve command with prompts if possible
        from memory_os.toolkit.workspace import _resolve_agent_launch_cmd
        command = _resolve_agent_launch_cmd(agent_id, self.root)

        if self.tmux.runtime == "zellij":
            from memory_os.toolkit.workspace_runtime import _zellij_env
            env = _zellij_env()
            venv_path = self.root / ".venv" / "bin" / "activate"
            if venv_path.exists():
                full_cmd = ["zellij", "--session", self.tmux.session_name, "run", "--name", label, "--cwd", str(self.root), "--", "bash", "-c", f"source .venv/bin/activate && {shlex.join(command)}"]
            else:
                full_cmd = ["zellij", "--session", self.tmux.session_name, "run", "--name", label, "--cwd", str(self.root), "--"] + command
                
            res = subprocess.run(full_cmd, capture_output=True, text=True, env=env)
            if res.returncode != 0:
                return False, f"Failed to launch Zellij pane: {res.stderr.strip()}"
            return True, "Launched in Zellij pane"

        # Split window from current manager pane
        manager_pane = os.environ.get("TMUX_PANE", "%0")
        cmd = ["tmux", "split-window", "-h", "-P", "-F", "#{pane_id}", "-t", manager_pane]
        res = subprocess.run(cmd, capture_output=True, text=True)
        pane_id = res.stdout.strip()
        if not pane_id:
            return False, "Failed to split tmux window"

        # Apply label
        subprocess.run(["tmux", "set-option", "-p", "-t", pane_id, "@agent_label", label])

        # Run command
        term = os.environ.get("TERM", "xterm-256color")
        if term == "dumb":
            term = "xterm-256color"
        parts = [f"export TERM={shlex.quote(term)}", f"cd {shlex.quote(str(self.root))}"]
        if (self.root / ".venv" / "bin" / "activate").exists():
            parts.append("source .venv/bin/activate")
        parts.append(shlex.join(command))
        
        subprocess.run(["tmux", "send-keys", "-t", pane_id, " && ".join(parts), "Enter"])
        return True, f"Launched in pane {pane_id}"

    def kill_agent_pane(self, agent: Dict[str, Any]) -> Tuple[bool, str]:
        agent_id = agent["id"]
        target_pane = self.tmux.resolve_pane_target(agent_id)
        
        if self.tmux.runtime == "zellij":
            if not target_pane:
                return False, "Agent pane not active"
            from memory_os.toolkit.workspace_runtime import _zellij_env
            env = _zellij_env()
            subprocess.run(["zellij", "--session", self.tmux.session_name, "action", "focus-pane-id", target_pane], env=env, check=False)
            res = subprocess.run(["zellij", "--session", self.tmux.session_name, "action", "close-pane"], env=env, capture_output=True, text=True)
            if res.returncode != 0:
                return False, f"Failed to close Zellij pane: {res.stderr.strip()}"
            return True, "Zellij pane closed successfully"

        if not target_pane.startswith("%"):
            return False, "Agent pane not active"
        
        res = subprocess.run(["tmux", "kill-pane", "-t", target_pane], capture_output=True, text=True)
        if res.returncode != 0:
            return False, f"Failed to kill pane: {res.stderr.strip()}"
        return True, "Pane closed successfully"

    def launch_terminal(self) -> Tuple[bool, str]:
        """Launch a simple bash terminal pane in Zellij or tmux."""
        label = f"terminal:{self.root.name}"
        if self.tmux.runtime == "zellij":
            from memory_os.toolkit.workspace_runtime import _zellij_env
            env = _zellij_env()
            full_cmd = ["zellij", "--session", self.tmux.session_name, "run", "--name", label, "--cwd", str(self.root), "--", "bash"]
            res = subprocess.run(full_cmd, capture_output=True, text=True, env=env)
            if res.returncode != 0:
                return False, f"Failed to launch Zellij terminal pane: {res.stderr.strip()}"
            return True, "Launched terminal in Zellij pane"

        manager_pane = os.environ.get("TMUX_PANE", "%0")
        cmd = ["tmux", "split-window", "-h", "-P", "-F", "#{pane_id}", "-t", manager_pane]
        res = subprocess.run(cmd, capture_output=True, text=True)
        pane_id = res.stdout.strip()
        if not pane_id:
            return False, "Failed to split tmux window"

        subprocess.run(["tmux", "set-option", "-p", "-t", pane_id, "@agent_label", label])
        parts = [f"cd {shlex.quote(str(self.root))}"]
        if (self.root / ".venv" / "bin" / "activate").exists():
            parts.append("source .venv/bin/activate")
        parts.append("bash")
        subprocess.run(["tmux", "send-keys", "-t", pane_id, " && ".join(parts), "Enter"])
        return True, f"Launched terminal in pane {pane_id}"

    def launch_feed(self) -> Tuple[bool, str]:
        """Launch the live-feed pane in Zellij or tmux."""
        label = f"live-feed:{self.root.name}"
        if self.tmux.runtime == "zellij":
            from memory_os.toolkit.workspace_runtime import _zellij_env
            env = _zellij_env()
            full_cmd = ["zellij", "--session", self.tmux.session_name, "run", "--name", label, "--cwd", str(self.root), "--", "bash", "-c", "source .venv/bin/activate && python3 -m memory_os feed"]
            res = subprocess.run(full_cmd, capture_output=True, text=True, env=env)
            if res.returncode != 0:
                return False, f"Failed to launch Zellij live-feed pane: {res.stderr.strip()}"
            return True, "Launched live-feed in Zellij pane"

        manager_pane = os.environ.get("TMUX_PANE", "%0")
        cmd = ["tmux", "split-window", "-h", "-P", "-F", "#{pane_id}", "-t", manager_pane]
        res = subprocess.run(cmd, capture_output=True, text=True)
        pane_id = res.stdout.strip()
        if not pane_id:
            return False, "Failed to split tmux window"

        subprocess.run(["tmux", "set-option", "-p", "-t", pane_id, "@agent_label", label])
        parts = [f"cd {shlex.quote(str(self.root))}"]
        if (self.root / ".venv" / "bin" / "activate").exists():
            parts.append("source .venv/bin/activate")
        parts.append("python3 -m memory_os feed")
        subprocess.run(["tmux", "send-keys", "-t", pane_id, " && ".join(parts), "Enter"])
        return True, f"Launched live-feed in pane {pane_id}"

    def restart_all(self, *, force: bool = False, detach_workspace: bool = True, workspace_only: bool = False) -> Dict[str, Any]:
        return RuntimeControl(self.root, config=self.config).restart_all(
            force=force,
            detach_workspace=detach_workspace,
            workspace_only=workspace_only,
        )

    def shutdown_all(self, *, force: bool = False, workspace_only: bool = False) -> Dict[str, Any]:
        return RuntimeControl(self.root, config=self.config).shutdown_all(
            force=force,
            workspace_only=workspace_only,
        )

    @staticmethod
    def format_control_result(result: Dict[str, Any]) -> str:
        return format_runtime_control_result(result)

    def run_curses(self) -> None:
        try:
            import curses
        except ImportError:
            self.run_plain()
            return

        def _menu(stdscr):
            try:
                curses.curs_set(0)
            except Exception as _e:
                import sys as _sys
                print(f'Ignored exception: {_e}', file=_sys.stderr)
            stdscr.keypad(True)
            # getch returns -1 every 5s so the table re-renders itself:
            # countdown timers tick and quota harvests refresh without keypresses
            stdscr.timeout(5000)
            current_idx = 0
            message = ""
            msg_type = "info" # info, success, error, working

            def safe_addstr(y: int, x: int, text: str, attr: int = 0) -> None:
                try:
                    h_max, w_max = stdscr.getmaxyx()
                    if 0 <= y < h_max and 0 <= x < w_max:
                        stdscr.addstr(y, x, text[:w_max - x - 1], attr)
                except Exception as _e:
                    import sys as _sys
                    print(f'Ignored exception: {_e}', file=_sys.stderr)

            while True:
                stdscr.clear()
                h, w = stdscr.getmaxyx()

                # Title
                title = "🧠 Memory OS — Agent Manager"
                safe_addstr(0, max(0, (w - len(title)) // 2), title, curses.A_BOLD)
                safe_addstr(1, 0, "─" * (w - 1))

                # Load status
                agents = self.get_agents_status()
                if not agents:
                    safe_addstr(3, 2, "No CLI agents configured.")
                    stdscr.refresh()
                    key = stdscr.getch()
                    if key in (ord('q'), ord('Q'), 27):
                        break
                    continue

                if current_idx >= len(agents):
                    current_idx = max(0, len(agents) - 1)

                if w < 54:
                    safe_addstr(3, 2, "Agents", curses.A_BOLD)
                    for idx, agent in enumerate(agents[: max(1, h - 7)]):
                        y_pos = 5 + idx
                        proc = "run" if agent["is_active"] else "stop"
                        quota = agent["limit_summary"]
                        row_text = f"{agent['id'][:10]:<10} {proc:<4} {quota:<5}"
                        attr = curses.A_REVERSE | curses.A_BOLD if idx == current_idx else 0
                        safe_addstr(y_pos, 2, row_text, attr)

                    if message:
                        safe_addstr(h - 3, 2, message[: max(1, w - 4)], curses.A_BOLD)
                    footer = "[Enter/x/r/R/S/q]"
                    safe_addstr(h - 1, max(0, (w - len(footer)) // 2), footer, curses.A_DIM)
                    stdscr.refresh()

                    key = stdscr.getch()
                    if key in (curses.KEY_UP, ord('k')):
                        current_idx = (current_idx - 1) % len(agents)
                        message = ""
                    elif key in (curses.KEY_DOWN, ord('j')):
                        current_idx = (current_idx + 1) % len(agents)
                        message = ""
                    elif key in (curses.KEY_ENTER, 10, 13):
                        agent = agents[current_idx]
                        if agent["is_active"]:
                            message = f"{agent['id']} already running"
                            msg_type = "info"
                            continue
                        ok, msg = self.launch_agent(agent)
                        message = msg if not ok else f"launched {agent['id']}"
                        msg_type = "success" if ok else "error"
                    elif key in (ord('x'), ord('X')):
                        ok, msg = self.kill_agent_pane(agents[current_idx])
                        message = msg
                        msg_type = "success" if ok else "error"
                    elif key == ord('r'):
                        agent = agents[current_idx]
                        self.probe.check(agent["id"], force=True)
                        message = f"refreshed {agent['id']}"
                        msg_type = "success"
                    elif key == ord('R'):
                        result = self.restart_all(force=True, detach_workspace=True)
                        message = "restart scheduled" if result.get("ok") else "restart failed"
                        msg_type = "success" if result.get("ok") else "error"
                    elif key == ord('S'):
                        result = self.shutdown_all(force=True)
                        message = "shutdown requested" if result.get("ok") else "shutdown failed"
                        msg_type = "success" if result.get("ok") else "error"
                    elif key in (ord('q'), ord('Q'), 27):
                        break
                    continue

                # Draw Table Headers (Gridless)
                col_agent = "Agent"
                col_proc = "Process Status"
                col_quota = "Quota / Limits"
                header_row = f"  {col_agent:<12}  {col_proc:<15}  {col_quota}"
                safe_addstr(3, 2, header_row, curses.A_BOLD | curses.A_UNDERLINE)

                row_height = 3 if any(agent.get("model_group_summary") for agent in agents) else 2

                # Draw agent rows
                for idx, agent in enumerate(agents):
                    y_pos = 5 + (idx * row_height)
                    if y_pos + row_height >= h - 3:
                        break
                    
                    # Resolve process status text
                    if agent["is_active"]:
                        proc_text = f"🟢 RUNNING ({agent['target_pane']})"
                    else:
                        proc_text = "🔴 STOPPED"

                    # Resolve quota status text
                    quota_summary = agent["limit_summary"]
                    if agent.get("limit_active") or agent["status"] in ("quota_exhausted", "rate_limited"):
                        quota_text = f"🔴 {quota_summary}"
                    else:
                        quota_text = f"🟢 {quota_summary}"

                    line1 = f"  {agent['id']:<12}  {proc_text:<15}  {quota_text}"

                    r_5h = agent.get("r_5h")
                    r_week = agent.get("r_week")

                    resets = []
                    if r_5h:
                        clean_5h = r_5h.replace("resets in ", "")
                        resets.append(f"5h resets in {clean_5h}")
                    if r_week:
                        clean_week = r_week.replace("resets in ", "")
                        resets.append(f"week resets in {clean_week}")

                    if resets:
                        line2 = "      " + "  •  ".join(resets)
                    else:
                        line2 = f"      Detail: {agent.get('detail', 'Available')}"
                    line3 = ""
                    if agent.get("model_group_summary"):
                        line3 = f"      Models: {agent['model_group_summary']}"

                    line1_padded = f" {line1:<{w-6}} "
                    line2_padded = f" {line2:<{w-6}} "
                    line3_padded = f" {line3:<{w-6}} "

                    # Highlight selected row block
                    if idx == current_idx:
                        safe_addstr(y_pos, 2, line1_padded, curses.A_REVERSE | curses.A_BOLD)
                        safe_addstr(y_pos + 1, 2, line2_padded, curses.A_REVERSE)
                        if line3:
                            safe_addstr(y_pos + 2, 2, line3_padded, curses.A_REVERSE)
                    else:
                        safe_addstr(y_pos, 2, line1_padded)
                        safe_addstr(y_pos + 1, 2, line2_padded, curses.A_DIM)
                        if line3:
                            safe_addstr(y_pos + 2, 2, line3_padded, curses.A_DIM)

                # Message display
                if message:
                    safe_addstr(h - 3, 2, "─" * (w - 5))
                    attr = curses.A_BOLD
                    if msg_type == "success":
                        attr |= curses.A_UNDERLINE
                    elif msg_type == "error":
                        attr |= curses.A_BLINK
                    safe_addstr(h - 2, 2, f"Result: {message[:w-12]}", attr)

                # Footer
                footer = "[Enter: Launch/Probe | x: Close Pane | f: Live Feed | t: Terminal | r: Refresh | R: Restart | S: Shutdown | q: Quit]"
                safe_addstr(h - 1, max(0, (w - len(footer)) // 2), footer, curses.A_DIM)
                stdscr.refresh()

                key = stdscr.getch()
                if key in (curses.KEY_UP, ord('k')):
                    current_idx = (current_idx - 1) % len(agents)
                    message = ""
                elif key in (curses.KEY_DOWN, ord('j')):
                    current_idx = (current_idx + 1) % len(agents)
                    message = ""
                elif key in (ord('f'), ord('F')):
                    ok, msg = self.launch_feed()
                    message = msg
                    msg_type = "success" if ok else "error"
                elif key in (ord('t'), ord('T')):
                    ok, msg = self.launch_terminal()
                    message = msg
                    msg_type = "success" if ok else "error"
                elif key in (curses.KEY_ENTER, 10, 13):
                    agent = agents[current_idx]
                    if agent["is_active"]:
                        message = f"Agent '{agent['id']}' is already running!"
                        msg_type = "info"
                        continue

                    message = f"Probing '{agent['id']}' health..."
                    msg_type = "working"
                    safe_addstr(h - 2, 2, f"Result: {message}", curses.A_BOLD)
                    stdscr.refresh()

                    # Perform real force probe
                    health = self.probe.check(agent["id"], force=True)
                    
                    if health.get("status") in ("quota_exhausted", "rate_limited"):
                        # Offer force launch
                        safe_addstr(h - 2, 2, "Warning: rate-limit active. Launch anyway? (y/n) ", curses.A_BOLD)
                        stdscr.refresh()
                        curses.curs_set(1)
                        stdscr.keypad(False)
                        curses.echo()
                        ans = stdscr.getstr().decode("utf-8").strip().lower()
                        curses.noecho()
                        stdscr.keypad(True)
                        curses.curs_set(0)
                        
                        if ans != 'y':
                            message = "Launch cancelled."
                            msg_type = "info"
                            continue

                    # Launch
                    ok, msg = self.launch_agent(agent)
                    if ok:
                        message = f"Successfully launched '{agent['id']}'!"
                        msg_type = "success"
                        # Refresh probe status cache immediately
                        self.probe.check(agent["id"], force=True)
                    else:
                        message = f"Launch failed: {msg}"
                        msg_type = "error"
                elif key in (ord('x'), ord('X')):
                    agent = agents[current_idx]
                    if not agent["is_active"]:
                        message = f"Agent '{agent['id']}' is not running!"
                        msg_type = "info"
                        continue
                    
                    # Confirm close
                    safe_addstr(h - 2, 2, f"Confirm closing '{agent['id']}' pane? (y/n) ", curses.A_BOLD)
                    stdscr.refresh()
                    curses.curs_set(1)
                    stdscr.keypad(False)
                    curses.echo()
                    ans = stdscr.getstr().decode("utf-8").strip().lower()
                    curses.noecho()
                    stdscr.keypad(True)
                    curses.curs_set(0)
                    
                    if ans != 'y':
                        message = "Cancelled."
                        msg_type = "info"
                        continue

                    ok, msg = self.kill_agent_pane(agent)
                    if ok:
                        message = f"Closed '{agent['id']}' pane."
                        msg_type = "success"
                    else:
                        message = f"Close failed: {msg}"
                        msg_type = "error"
                elif key == ord('r'):
                    agent = agents[current_idx]
                    message = f"Forcing refresh for '{agent['id']}' limits..."
                    msg_type = "working"
                    safe_addstr(h - 2, 2, f"Result: {message}", curses.A_BOLD)
                    stdscr.refresh()
                    self.probe.check(agent["id"], force=True)
                    try:
                        from memory_os.toolkit.usage_probe import probe_pane_usage
                        usage = probe_pane_usage(self.root, agent["id"])
                    except Exception:
                        usage = None
                    message = f"Refreshed '{agent['id']}' status." + (" Usage harvested." if usage else "")
                    msg_type = "success"
                elif key == ord('R'):
                    safe_addstr(h - 2, 2, "Confirm full Memory OS restart? (y/n) ", curses.A_BOLD)
                    stdscr.refresh()
                    curses.curs_set(1)
                    stdscr.keypad(False)
                    curses.echo()
                    ans = stdscr.getstr().decode("utf-8").strip().lower()
                    curses.noecho()
                    stdscr.keypad(True)
                    curses.curs_set(0)
                    if ans != 'y':
                        message = "Restart cancelled."
                        msg_type = "info"
                        continue
                    result = self.restart_all(force=True, detach_workspace=True)
                    message = "Restart scheduled." if result.get("ok") else "Restart failed."
                    msg_type = "success" if result.get("ok") else "error"
                elif key == ord('S'):
                    safe_addstr(h - 2, 2, "Confirm full Memory OS shutdown? (y/n) ", curses.A_BOLD)
                    stdscr.refresh()
                    curses.curs_set(1)
                    stdscr.keypad(False)
                    curses.echo()
                    ans = stdscr.getstr().decode("utf-8").strip().lower()
                    curses.noecho()
                    stdscr.keypad(True)
                    curses.curs_set(0)
                    if ans != 'y':
                        message = "Shutdown cancelled."
                        msg_type = "info"
                        continue
                    result = self.shutdown_all(force=True)
                    message = "Shutdown requested." if result.get("ok") else "Shutdown failed."
                    msg_type = "success" if result.get("ok") else "error"
                elif key in (ord('q'), ord('Q'), 27):
                    break

        curses.wrapper(_menu)

    def run_plain(self, interactive: bool = True) -> None:
        print("\n🧠 Memory OS — Agent Manager\n")
        agents = self.get_agents_status()
        print(f"{'Agent':<12} | {'Process':<11} | {'Limits':<28}")
        print("-" * 60)
        for idx, agent in enumerate(agents, start=1):
            if agent["is_active"]:
                state_lbl = "working" if agent.get("is_working") else "idle"
                proc_text = f"RUNNING ({agent['target_pane']}:{state_lbl})"
            else:
                proc_text = "STOPPED"
            suffix = f" | {agent['limit_str']}" if agent["limit_str"] else ""
            quota_text = f"{agent['limit_summary']}{suffix}"
            print(f"[{idx}] {agent['id']:<8} | {proc_text:<22} | {quota_text:<28}")
        if not interactive:
            return
        print("  [t] Launch new terminal pane")
        print("  [f] Launch live-feed pane")
        print("  [restart] Restart all Memory OS processes")
        print("  [shutdown] Shutdown all Memory OS processes")
        print("  [q] Quit\n")

        try:
            choice = input("Select option (number to launch/probe, x + number to close, t: terminal, f: feed): ").strip().lower()
            if choice == 'q' or not choice:
                return
            if choice == 't':
                ok, msg = self.launch_terminal()
                print(msg)
                return
            if choice == 'f':
                ok, msg = self.launch_feed()
                print(msg)
                return
            if choice == "restart":
                print(self.format_control_result(self.restart_all(force=True, detach_workspace=True)))
                return
            if choice == "shutdown":
                print(self.format_control_result(self.shutdown_all(force=True)))
                return
            if choice.startswith('x'):
                idx = int(choice[1:]) - 1
                if 0 <= idx < len(agents):
                    ok, msg = self.kill_agent_pane(agents[idx])
                    print(msg)
            elif choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(agents):
                    agent = agents[idx]
                    if agent["is_active"]:
                        print("Already active!")
                        return
                    ok, msg = self.launch_agent(agent)
                    print(msg)
        except Exception as e:
            print(f"Error: {e}")


def main():
    root = Path(__file__).resolve().parents[3]
    tui = AgentManagerTUI(root)
    tui.run_curses()


if __name__ == "__main__":
    main()
