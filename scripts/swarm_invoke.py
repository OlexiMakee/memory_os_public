#!/usr/bin/env python3
import sys
import argparse
import subprocess
import json
import re
import shlex
import threading
from datetime import datetime, timedelta
from pathlib import Path

def update_backlog_status(task_id: str, new_status: str, msg: str = ""):
    try:
        import sys
        from pathlib import Path
        scripts_dir = Path(__file__).resolve().parent
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import swarm_sync
        swarm_sync.cmd_update(task_id, new_status, msg)
    except Exception as e:
        print(f"[SwarmInvoke] Error updating backlog: {e}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="Invoke Swarm Worker safely.")
    parser.add_argument("--target", required=True, choices=["claude", "codex", "test"], help="Target agent CLI")
    parser.add_argument("--task_id", required=True, help="Task ID from swarm_backlog.json")
    parser.add_argument("--cmd_args", default="", help="Arguments to pass to the agent")
    args = parser.parse_args()

    # Determine command using shlex to parse arguments correctly
    parsed_args = shlex.split(args.cmd_args)
    if args.target == "claude":
        cmd = ["claude"] + parsed_args
    elif args.target == "codex":
        cmd = ["codex"] + parsed_args
    elif args.target == "test":
        cmd = ["echo", "Error: Rate limit exceeded. Quota exhausted."]
    else:
        print("Unknown target")
        sys.exit(1)

    print(f"[SwarmInvoke] Starting {args.target} for task {args.task_id}...")
    update_backlog_status(args.task_id, "running", "Process spawned")

    def forward_stdin(proc):
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                proc.stdin.write(line)
                proc.stdin.flush()
            except Exception:
                break

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True
        )

        # Start background thread to forward stdin to the subprocess
        threading.Thread(target=forward_stdin, args=(process,), daemon=True).start()

        limit_hit = False
        limit_regex = re.compile(r"(rate\s*limit|quota\s*exhausted|limit\s*exceeded)", re.IGNORECASE)

        for line in process.stdout:
            print(f"[{args.target}] {line}", end="", flush=True)
            if limit_regex.search(line):
                limit_hit = True
                process.terminate()
                break

        process.wait()

        if limit_hit:
            resume_time = datetime.now() + timedelta(hours=2)
            msg = f"Limit exhausted. Paused. Resume estimated at {resume_time.isoformat()}"
            print(f"\n[SwarmInvoke] {msg}")
            update_backlog_status(args.task_id, "pending_limit", msg)
            sys.exit(429)
        elif process.returncode == 0:
            print(f"\n[SwarmInvoke] Task completed successfully.")
            update_backlog_status(args.task_id, "completed", "Success")
            sys.exit(0)
        else:
            print(f"\n[SwarmInvoke] Task failed with exit code {process.returncode}.")
            update_backlog_status(args.task_id, "failed", f"Exit code {process.returncode}")
            sys.exit(process.returncode)

    except FileNotFoundError:
        msg = f"Command for target '{args.target}' not found on PATH."
        print(f"[SwarmInvoke] {msg}")
        update_backlog_status(args.task_id, "failed", msg)
        sys.exit(127)

if __name__ == "__main__":
    main()
