import argparse
import json
import sys
from datetime import timezone
from pathlib import Path

from memory_os import MemoryOSConfig

UTC = timezone.utc
def cmd_tmux(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.multiplexer_manager import MultiplexerManager

    root = Path(args.root).resolve() if getattr(args, "root", None) else Path.cwd()
    mgr = MultiplexerManager(root)
    action = getattr(args, "tmux_action", "")

    if action == "send":
        mgr.send_keys(
            target=args.target,
            message=args.message,
            submit=not getattr(args, "no_submit", False),
            unlock_buffers=not getattr(args, "no_unlock", False),
        )
        print(f"sent keys to {args.target}")
        return 0

    if action == "shortcut":
        ok = mgr.send_shortcut(args.target, args.name)
        if ok:
            print(f"shortcut {args.name} sent to {args.target}")
            return 0
        print(f"unknown shortcut: {args.name}", file=sys.stderr)
        return 1

    if action == "press":
        mgr.send_key_sequence(args.target, args.keys)
        print(f"pressed keys {args.keys} in {args.target}")
        return 0


    if action == "capture":
        text = mgr.capture_pane(args.target, lines=getattr(args, "lines", 50))
        print(text)
        return 0

    if action == "list":
        panes = mgr.list_panes(session=getattr(args, "session", None))
        if getattr(args, "json", False):
            print(json.dumps([p.to_dict() for p in panes], indent=2))
        else:
            for p in panes:
                active_mark = "*" if p.active else " "
                print(f"{active_mark} {p.target}\t[{p.width}x{p.height}]\tcmd: {p.current_command}")
        return 0

    return 1
