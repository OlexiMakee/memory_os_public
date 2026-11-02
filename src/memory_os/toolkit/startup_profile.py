"""Startup permission profile picker.

Shown once per `memory_os` launch (no-arg entrypoint), right after workspace
selection, so the operator explicitly confirms how much autonomy agent panes
get for this session. Full autonomy is the default/first option — the
project's standing choice — everything else is an opt-in downgrade.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Flags registry.toml uses to grant unattended access; stripped in "supervised"
# profile so each agent CLI falls back to its own interactive approval prompts.
_UNATTENDED_FLAGS = {
    "--dangerously-skip-permissions",
    "--sandbox", "danger-full-access",
    "--ask-for-approval", "never",
}

# (label, profile_key) — order is menu order; index 0 is the pre-selected default.
STARTUP_PROFILES: List[Tuple[str, str]] = [
    ("🟢 Повна автономія — без запитів на підтвердження (рекомендовано)", "full_autonomy"),
    ("🟡 Супервізований режим — кожен агент питає підтвердження дій", "supervised"),
]

DEFAULT_PROFILE = STARTUP_PROFILES[0][1]


def apply_profile_to_flags(flags: List[str], profile: str) -> List[str]:
    """Filter a registry launch/dispatch flag list according to `profile`."""
    if profile != "supervised":
        return list(flags)
    return [f for f in flags if f not in _UNATTENDED_FLAGS]


def _plain_profile_picker() -> str:
    print("\n🔐 Memory OS — Startup Permission Profile:\n")
    for idx, (label, _key) in enumerate(STARTUP_PROFILES, start=1):
        print(f"  [{idx}] {label}")
    try:
        choice = input(f"Select option number [1]: ").strip()
        if not choice:
            return DEFAULT_PROFILE
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(STARTUP_PROFILES):
                return STARTUP_PROFILES[idx][1]
    except (KeyboardInterrupt, EOFError):
        return DEFAULT_PROFILE
    return DEFAULT_PROFILE


def _curses_profile_picker() -> str:
    try:
        import curses
    except ImportError:
        return _plain_profile_picker()

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
            title = "🔐 Memory OS — Startup Permission Profile"
            stdscr.addstr(0, max(0, (w - len(title)) // 2), title, curses.A_BOLD)
            stdscr.addstr(1, 0, "─" * (w - 1))
            for idx, (label, _key) in enumerate(STARTUP_PROFILES):
                text = f"{'▸ ' if idx == current_idx else '  '}{label}"[: w - 2]
                if idx == current_idx:
                    stdscr.addstr(2 + idx, 2, text, curses.A_REVERSE | curses.A_BOLD)
                else:
                    stdscr.addstr(2 + idx, 2, text)
            footer = "[↑/↓ or j/k: Navigate | Enter: Select | q: Default]"
            stdscr.addstr(h - 1, max(0, (w - len(footer)) // 2), footer, curses.A_DIM)
            stdscr.refresh()
            key = stdscr.getch()
            if key in (curses.KEY_UP, ord('k')):
                current_idx = (current_idx - 1) % len(STARTUP_PROFILES)
            elif key in (curses.KEY_DOWN, ord('j')):
                current_idx = (current_idx + 1) % len(STARTUP_PROFILES)
            elif key in (curses.KEY_ENTER, 10, 13):
                return STARTUP_PROFILES[current_idx][1]
            elif key in (ord('q'), ord('Q'), 27):
                return DEFAULT_PROFILE

    try:
        return curses.wrapper(_menu)
    except Exception:
        return _plain_profile_picker()


def select_startup_profile() -> str:
    """Prompt for a startup profile; non-interactive terminals get the default."""
    term = os.environ.get("TERM", "").lower()
    is_interactive = sys.stdin.isatty() and sys.stdout.isatty() and term != "dumb"
    if not is_interactive:
        return DEFAULT_PROFILE
    return _curses_profile_picker()


def record_startup_profile(root: Path, profile: str) -> None:
    """Persist the chosen profile so other tools (agent-manager, dispatcher) can read it."""
    import json
    runtime_dir = root / "agent_context" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_dir / "startup_profile.json"
    try:
        path.write_text(json.dumps({"profile": profile}, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as _e:
        import sys as _sys
        print(f'Ignored exception: {_e}', file=_sys.stderr)


def read_startup_profile(root: Path) -> str:
    """Read the last-recorded profile; defaults to full autonomy if absent/unreadable."""
    import json
    path = root / "agent_context" / "runtime" / "startup_profile.json"
    if not path.exists():
        return DEFAULT_PROFILE
    try:
        data: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        profile = data.get("profile", DEFAULT_PROFILE)
        return profile if profile in {p for _l, p in STARTUP_PROFILES} else DEFAULT_PROFILE
    except Exception:
        return DEFAULT_PROFILE
