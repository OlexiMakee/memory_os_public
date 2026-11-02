"""Interactive TUI Project Picker for Memory OS.

Scans ~/dev/* and registered workspaces to present an interactive curses/plain selection menu
when memory_os is launched with zero arguments in interactive terminals.
"""

import os
import sys
import shutil
from pathlib import Path
from typing import List, Optional, Tuple, Any


def scan_projects(base_dir: Optional[Path] = None, limit: int = 50) -> List[Tuple[str, Path]]:
    """Scan base_dir (default ~/dev) for available project directories."""
    if base_dir is None:
        base_dir = Path.home() / "dev"
    
    projects: List[Tuple[str, Path]] = []
    if not base_dir.exists() or not base_dir.is_dir():
        return projects

    try:
        entries = sorted(base_dir.iterdir(), key=lambda p: p.name.lower())
        for entry in entries:
            if len(projects) >= limit:
                break
            if entry.is_dir() and not entry.name.startswith(".") and not entry.name.startswith("_"):
                projects.append((entry.name, entry.resolve()))
    except Exception as _e:
        import sys as _sys
        print(f'Ignored exception: {_e}', file=_sys.stderr)
    return projects


def _plain_picker(options: List[Tuple[str, Optional[Path]]]) -> Optional[Path]:
    """Fallback plain text menu for non-curses terminals."""
    print("\n🧠 Memory OS — Select Workspace Environment:\n")
    for idx, (label, path) in enumerate(options, start=1):
        path_str = f" ({path})" if path else ""
        print(f"  [{idx}] {label}{path_str}")
    print("  [q] Quit\n")

    try:
        choice = input("Select option number [1]: ").strip()
        if choice.lower() == "q":
            return None
        if not choice:
            return options[0][1]
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx][1]
    except (KeyboardInterrupt, EOFError):
        return None
    return options[0][1]


def run_curses_menu(options: List[Tuple[str, Optional[Path]]]) -> Optional[Path]:
    """Curses TUI navigation menu with arrow keys, vim keys (j/k), Enter, and q."""
    try:
        import curses
    except ImportError:
        return _plain_picker(options)

    def _menu(stdscr):
        try:
            curses.curs_set(0)
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)
        stdscr.keypad(True)
        current_idx = 0

        while True:
            stdscr.clear()
            h, w = stdscr.getmaxyx()
            
            # Header
            title = "🧠 Memory OS Workspace Selector"
            stdscr.addstr(0, max(0, (w - len(title)) // 2), title, curses.A_BOLD)
            stdscr.addstr(1, 0, "─" * (w - 1))

            # Options
            max_visible = max(1, h - 5)
            start_idx = max(0, min(current_idx - max_visible // 2, len(options) - max_visible))
            end_idx = min(len(options), start_idx + max_visible)

            for line_idx, opt_idx in enumerate(range(start_idx, end_idx), start=2):
                label, path = options[opt_idx]
                path_str = f" → {path}" if path else ""
                text = f"{'▸ ' if opt_idx == current_idx else '  '}{label}{path_str}"
                text = text[: w - 2]
                
                if opt_idx == current_idx:
                    stdscr.addstr(line_idx, 2, text, curses.A_REVERSE | curses.A_BOLD)
                else:
                    stdscr.addstr(line_idx, 2, text)

            # Footer
            footer = "[↑/↓ or j/k: Navigate | Enter: Select | q: Quit]"
            stdscr.addstr(h - 1, max(0, (w - len(footer)) // 2), footer, curses.A_DIM)
            stdscr.refresh()

            key = stdscr.getch()
            if key in (curses.KEY_UP, ord('k')):
                current_idx = (current_idx - 1) % len(options)
            elif key in (curses.KEY_DOWN, ord('j')):
                current_idx = (current_idx + 1) % len(options)
            elif key in (curses.KEY_ENTER, 10, 13):
                return options[current_idx][1]
            elif key in (ord('q'), ord('Q'), 27):  # 27 = ESC
                return None

    try:
        return curses.wrapper(_menu)
    except Exception:
        return _plain_picker(options)


import subprocess


def get_active_tmux_sessions() -> List[str]:
    """Return list of running tmux session names."""
    if not shutil.which("tmux"):
        return []
    try:
        res = subprocess.run(["tmux", "list-sessions", "-F", "#{session_name}"], capture_output=True, text=True)
        if res.returncode != 0:
            return []
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def get_active_zellij_sessions() -> List[str]:
    """Return list of running zellij session names."""
    if not shutil.which("zellij"):
        return []
    try:
        res = subprocess.run(["zellij", "list-sessions", "--no-formatting"], capture_output=True, text=True)
        if res.returncode != 0:
            return []
        sessions = []
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            if "(EXITED" in line:
                continue
            parts = line.split()
            if parts:
                sessions.append(parts[0])
        return sessions
    except Exception:
        return []


def select_workspace(base_dir: Optional[Path] = None):
    """Main entrypoint for selecting or creating a workspace."""
    dev_projects = scan_projects(base_dir=base_dir, limit=50)
    active_tmux = get_active_tmux_sessions()
    active_zellij = get_active_zellij_sessions()
    
    options: List[Tuple[str, Any]] = []

    if active_tmux:
        for sess in active_tmux:
            options.append((f"🟢 Attach to running tmux session: {sess}", f"ATTACH_TMUX:{sess}"))
        options.append(("💀 Kill all running tmux sessions", "KILL_ALL_TMUX_SESSIONS"))

    if active_zellij:
        for sess in active_zellij:
            options.append((f"🟢 Attach to running zellij session: {sess}", f"ATTACH_ZELLIJ:{sess}"))
        options.append(("💀 Kill all running zellij sessions", "KILL_ALL_ZELLIJ_SESSIONS"))

    options.append(("🌍 Global Memory OS Core", Path.home() / "dev" / "memory_os"))

    for name, path in dev_projects:
        if name.lower() not in ("memory_os", "memory-os"):
            options.append((f"📁 {name}", path))

    options.append(("➕ Create New Project in ~/dev/...", "CREATE_NEW"))

    # Safety checks for non-interactive / CI / dumb terminals
    term = os.environ.get("TERM", "").lower()
    is_interactive = sys.stdin.isatty() and sys.stdout.isatty() and term != "dumb"

    if not is_interactive:
        return Path.cwd()

    selected = run_curses_menu(options)
    if selected == "CREATE_NEW":
        try:
            print("\n➕ Create New Project in ~/dev/\n")
            name = input("Enter new project folder name: ").strip()
            if name:
                new_dir = (base_dir or (Path.home() / "dev")) / name
                new_dir.mkdir(parents=True, exist_ok=True)
                print(f"Created workspace directory: {new_dir}")
                from memory_os.toolkit.project_secrets import ensure_project_telegram_token
                ensure_project_telegram_token(new_dir, interactive=True)
                return new_dir
        except (KeyboardInterrupt, EOFError):
            return None
        return Path.cwd()

    return selected
