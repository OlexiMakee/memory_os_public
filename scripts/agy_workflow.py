#!/usr/bin/env python3
"""
Dynamic workflow runner for agy CLI — delegates tasks to agy and captures results.

## Invocation rules (IMPORTANT)

### subprocess / Popen  ← preferred for code
    cmd = ["agy", "-p", prompt, "--print-timeout", "2m", "--dangerously-skip-permissions"]
    Flag order does not matter: each list element is a separate argv, never shell-parsed.

### shell / tmux send-keys  ← only for interactive/manual use
    CORRECT:   agy --dangerously-skip-permissions --print "task here"
    WRONG:     agy --print --dangerously-skip-permissions "task here"
                        ^^ flags after --print/-p are absorbed into the prompt text

    Also avoid mentioning CLI flag names inside the prompt text itself (e.g. "--print-timeout")
    — agy treats them as a question about that flag rather than executing the task.

    For prompts longer than ~200 chars in shell, write to a temp file and use:
        agy --dangerously-skip-permissions --print "$(cat /tmp/prompt.txt)"

## Usage examples

    # Run a single task and get output
    result = AgyWorkflow().run("Add expected_args to cases.jsonl in /path/to/project")
    print(result.output)

    # Run multiple tasks in sequence, stop on first failure
    wf = AgyWorkflow(workdir="/home/oleksii/dev/memory_os")
    for task in tasks:
        r = wf.run(task)
        if not r.ok:
            break

    # Run in tmux (keeps session visible for debugging)
    r = AgyWorkflow(workdir=...).run_in_tmux("Fix the eval runner", session="my-debug")
"""
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TIMEOUT = 300  # 5 minutes


@dataclass
class AgyResult:
    ok: bool
    output: str
    exit_code: int
    timed_out: bool = False
    rate_limited: bool = False
    error: str = ""


class AgyWorkflow:
    """
    Wraps agy CLI for non-interactive task delegation.

    All subprocess calls use Popen(list) — no shell=True — so flag order is safe
    and prompts with quotes/newlines work correctly.
    """

    def __init__(
        self,
        workdir: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.workdir = Path(workdir).resolve() if workdir else REPO_ROOT
        self.model = model
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, prompt: str) -> AgyResult:
        """
        Delegate a task to agy via subprocess and return the result.

        This is the recommended path: flag order is irrelevant when using
        Popen(list), and prompts are passed verbatim regardless of content.
        """
        cmd = self._build_cmd(prompt)
        return self._exec(cmd)

    def run_in_tmux(self, prompt: str, session: str = "agy-task") -> AgyResult:
        """
        Run agy inside a new tmux window, poll for completion, return output.

        Use this when you want the session visible for live debugging.
        Applies the shell-safe invocation pattern: flags before --print,
        prompt written to a temp file to avoid quoting issues.

        Returns AgyResult with combined stdout captured via tmux capture-pane.
        """
        import shutil
        if not shutil.which("tmux"):
            raise RuntimeError("tmux not found on PATH")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(prompt)
            prompt_path = f.name

        try:
            return self._run_tmux_session(session, prompt_path)
        finally:
            Path(prompt_path).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_cmd(self, prompt: str) -> list:
        # --dangerously-skip-permissions BEFORE -p: required in shell contexts;
        # harmless (but good hygiene) in Popen(list) too.
        cmd = ["agy", "--dangerously-skip-permissions", "-p", prompt]
        cmd += ["--print-timeout", f"{self.timeout}s"]
        if self.model:
            cmd += ["--model", self.model]
        return cmd

    def _exec(self, cmd: list) -> AgyResult:
        timed_out = {"hit": False}
        proc = subprocess.Popen(
            cmd,
            cwd=str(self.workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
        )

        def _kill():
            timed_out["hit"] = True
            try:
                proc.kill()
            except Exception:
                pass

        timer = threading.Timer(self.timeout, _kill)
        timer.start()

        lines = []
        rate_limited = False
        try:
            for line in proc.stdout:
                lines.append(line)
                if _looks_like_rate_limit(line):
                    rate_limited = True
                    proc.terminate()
                    break
            proc.wait()
        finally:
            timer.cancel()

        output = "".join(lines)
        if timed_out["hit"]:
            return AgyResult(ok=False, output=output, exit_code=124, timed_out=True,
                             error=f"agy exceeded {self.timeout}s timeout")
        if rate_limited:
            return AgyResult(ok=False, output=output, exit_code=429, rate_limited=True,
                             error="rate limit hit")
        ok = proc.returncode == 0
        return AgyResult(ok=ok, output=output, exit_code=proc.returncode,
                         error="" if ok else f"exit code {proc.returncode}")

    def _run_tmux_session(self, session: str, prompt_path: str) -> AgyResult:
        # Shell-safe invocation: flags before --print, prompt via $(cat file).
        # Double-quotes around $(cat ...) preserve newlines in the prompt.
        shell_cmd = (
            f'agy --dangerously-skip-permissions --print "$(cat {prompt_path})"'
        )
        if self.model:
            shell_cmd = f'agy --dangerously-skip-permissions --model {self.model} --print "$(cat {prompt_path})"'

        _tmux(["new-session", "-d", "-s", session, "-x", "220", "-y", "50"])
        _tmux(["send-keys", "-t", session, f"cd {self.workdir} && {shell_cmd}", "Enter"])

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            time.sleep(3)
            pane = _tmux_capture(session)
            if _shell_prompt_visible(pane):
                break
        else:
            _tmux(["kill-session", "-t", session])
            return AgyResult(ok=False, output="", exit_code=124, timed_out=True,
                             error=f"tmux session '{session}' exceeded {self.timeout}s")

        pane = _tmux_capture(session)
        # Strip the shell prompt lines, keep only agy output
        output_lines = []
        in_output = False
        for line in pane.splitlines():
            if shell_cmd[:30] in line:
                in_output = True
                continue
            if in_output:
                if line.strip().startswith("oleksii@") or line.strip().startswith("$"):
                    break
                output_lines.append(line)

        output = "\n".join(output_lines).strip()
        return AgyResult(ok=True, output=output, exit_code=0)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _looks_like_rate_limit(line: str) -> bool:
    import re
    stripped = line.strip()
    if len(stripped) > 200:
        return False
    pattern = re.compile(r"(rate\s*limit|quota\s*exhausted|limit\s*exceeded|usage\s*limit)", re.I)
    prefix = re.compile(r"(?i)^\s*(error|\[error\]|fatal)\b")
    return bool(pattern.search(stripped) and prefix.match(stripped))


def _tmux(args: list) -> str:
    result = subprocess.run(["tmux"] + args, capture_output=True, text=True)
    return result.stdout


def _tmux_capture(session: str) -> str:
    return _tmux(["capture-pane", "-t", session, "-p"])


def _shell_prompt_visible(pane: str) -> bool:
    for line in reversed(pane.splitlines()):
        stripped = line.strip()
        if stripped.startswith("oleksii@") and stripped.endswith("$"):
            return True
    return False


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Delegate a single task to agy and print the result.",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("prompt", help="Task prompt to send to agy")
    parser.add_argument("--workdir", default=str(REPO_ROOT), help="Working directory")
    parser.add_argument("--model", default="", help="Model override")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Timeout in seconds")
    parser.add_argument("--tmux", metavar="SESSION", default="",
                        help="Run inside a tmux session with this name instead of subprocess")
    args = parser.parse_args()

    wf = AgyWorkflow(
        workdir=args.workdir,
        model=args.model or None,
        timeout=args.timeout,
    )

    result = wf.run_in_tmux(args.prompt, session=args.tmux) if args.tmux else wf.run(args.prompt)

    print(result.output)
    if not result.ok:
        print(f"\n[agy_workflow] FAILED: {result.error}", file=sys.stderr)
    sys.exit(0 if result.ok else result.exit_code)


if __name__ == "__main__":
    main()
