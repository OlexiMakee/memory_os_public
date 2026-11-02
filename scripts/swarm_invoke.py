#!/usr/bin/env python3
"""Swarm worker invoker — delegates tasks to claude, agy, or codex non-interactively."""
import sys
import argparse
from memory_os.toolkit.agent_registry import KNOWN_AGENTS
import subprocess
import json
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path


def update_backlog_status(task_id: str, new_status: str, msg: str = ""):
    try:
        scripts_dir = Path(__file__).resolve().parent
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import swarm_sync
        swarm_sync.cmd_update(task_id, new_status, msg)
    except Exception as e:
        print(f"[SwarmInvoke] backlog update error: {e}", file=sys.stderr)


def build_command(target: str, prompt: str, model: str, workdir: str) -> list:
    """Build the correct non-interactive command for each agent CLI."""
    if target == "claude":
        cmd = ["claude", "-p", prompt, "--permission-mode", "bypassPermissions"]
        if model:
            cmd += ["--model", model]
        if workdir:
            cmd += ["--add-dir", workdir]
        return cmd

    if target == "agy":
        cmd = ["agy", "-p", prompt, "--print-timeout", "2m", "--dangerously-skip-permissions"]
        if model:
            cmd += ["--model", model]
        return cmd

    if target == "codex":
        # codex exec defaults to a read-only sandbox, which silently rejects
        # any file write (process still exits 0, masking the failure) —
        # workspace-write scopes write access to the repo dir only.
        cmd = ["codex", "exec", "--sandbox", "workspace-write", prompt]
        if model:
            cmd += ["-c", f'model="{model}"']
        return cmd

    if target == "test":
        return ["echo", "Error: Rate limit exceeded. Quota exhausted."]

    raise ValueError(f"Unknown target: {target}")


def main():
    parser = argparse.ArgumentParser(description="Invoke a swarm worker non-interactively.")
    parser.add_argument("--target", required=True, choices=list(KNOWN_AGENTS) + ["test"],
                        help="Agent CLI to invoke")
    parser.add_argument("--task_id", required=True, help="Task ID from swarm_backlog.json")
    parser.add_argument("--prompt", required=True, help="Task prompt to send to the agent")
    parser.add_argument("--model", default="", help="Model override (e.g. sonnet, opus, o3)")
    parser.add_argument("--workdir", default="", help="Working directory for the agent")
    args = parser.parse_args()

    try:
        cmd = build_command(args.target, args.prompt, args.model, args.workdir)
    except ValueError as e:
        print(f"[SwarmInvoke] {e}")
        sys.exit(1)

    workdir = Path(args.workdir).resolve() if args.workdir else Path.cwd()
    print(f"[SwarmInvoke] {args.target} | task={args.task_id} | cwd={workdir}")
    update_backlog_status(args.task_id, "running", "Process spawned")

    limit_regex = re.compile(r"(rate\s*limit|quota\s*exhausted|limit\s*exceeded|usage\s*limit)", re.IGNORECASE)
    # Real CLI rate-limit notices are short, terse lines that start with an
    # error marker. Matching the phrase anywhere in arbitrarily long worker
    # output false-positives when a task is *asked* to discuss/summarize
    # rate-limit text (e.g. an audit task literally describing this class
    # of bug) — require both a short line AND an error-shaped prefix.
    limit_line_prefix = re.compile(r"(?i)^\s*(error|\[error\]|fatal)\b")
    PROCESS_TIMEOUT_SECONDS = 3600

    def _is_real_limit_signal(line: str) -> bool:
        stripped = line.strip()
        if len(stripped) > 200 or not limit_regex.search(stripped):
            return False
        return bool(limit_line_prefix.match(stripped))

    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
        )

        # A worker that hangs with NO output at all (blocked I/O, infinite
        # loop, waiting on stdin) would never reach a check placed inside
        # the "for line in process.stdout" loop below, since that loop
        # blocks on each readline(). A background timer that kills the
        # process independently of whether any output ever arrives is the
        # only way to bound this.
        timed_out_flag = {"hit": False}

        def _on_timeout():
            timed_out_flag["hit"] = True
            try:
                process.kill()
            except Exception:
                pass

        timer = threading.Timer(PROCESS_TIMEOUT_SECONDS, _on_timeout)
        timer.start()

        limit_hit = False
        try:
            for line in process.stdout:
                print(f"[{args.target}] {line}", end="", flush=True)
                if _is_real_limit_signal(line):
                    limit_hit = True
                    process.terminate()
                    break
            process.wait()
        finally:
            timer.cancel()

        if timed_out_flag["hit"]:
            msg = f"Worker exceeded {PROCESS_TIMEOUT_SECONDS}s timeout and was killed"
            print(f"\n[SwarmInvoke] {msg}")
            update_backlog_status(args.task_id, "failed", msg)
            sys.exit(124)

        if limit_hit:
            resume_time = datetime.now() + timedelta(hours=2)
            msg = f"Rate limit hit. Resume estimated at {resume_time.isoformat()}"
            print(f"\n[SwarmInvoke] {msg}")
            update_backlog_status(args.task_id, "pending_limit", msg)
            sys.exit(429)
        elif process.returncode == 0:
            print(f"\n[SwarmInvoke] Task {args.task_id} completed.")
            update_backlog_status(args.task_id, "completed", "Success")
            sys.exit(0)
        else:
            msg = f"Exit code {process.returncode}"
            print(f"\n[SwarmInvoke] Task {args.task_id} failed: {msg}")
            update_backlog_status(args.task_id, "failed", msg)
            sys.exit(process.returncode)

    except FileNotFoundError:
        msg = f"'{args.target}' not found on PATH"
        print(f"[SwarmInvoke] {msg}")
        update_backlog_status(args.task_id, "failed", msg)
        sys.exit(127)


if __name__ == "__main__":
    main()
