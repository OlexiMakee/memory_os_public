import argparse
import os
import subprocess
import sys
from datetime import timezone
from pathlib import Path
from typing import List, Optional

from memory_os import MemoryOSConfig

UTC = timezone.utc
def cmd_telegram_daemon(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    """Start the Telegram long-polling daemon (blocks until SIGINT/SIGTERM)."""
    import logging as _logging
    import signal

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s  %(levelname)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    from memory_os.adapters.telegram_polling import TelegramPollingDaemon

    daemon = TelegramPollingDaemon(
        config,
        system_prompt=getattr(args, "system_prompt", None),
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        track_tasks=not getattr(args, "no_task_tracking", False),
        swarm_control=getattr(args, "swarm_control", False),
        swarm_watch_timeout=getattr(args, "swarm_watch_timeout", 10.0),
    )
    once = getattr(args, "once", False)

    stop = [False]

    def _stop(signum, frame):
        print("\n[telegram] stopping…")
        stop[0] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    poll_interval = getattr(args, "poll_interval", 2.0)
    import time as _time

    max_retries = getattr(args, "max_retries", 5)
    mode = "swarm-control" if getattr(args, "swarm_control", False) else "responder"
    print(f"[telegram] polling started  mode={mode}  interval={poll_interval}s  task_tracking={not getattr(args, 'no_task_tracking', False)}  (Ctrl+C to stop)")

    restart_count = 0
    watchdog_backoff = 5.0
    while not stop[0]:
        try:
            daemon.run(poll_interval=poll_interval, once=once, max_retries=max_retries,
                       should_stop=lambda: stop[0])
        except Exception as exc:
            import logging
            logging.error(f"[telegram] daemon crashed: {exc}")
        if once or stop[0]:
            break
        restart_count += 1
        print(f"[telegram] watchdog: restart #{restart_count} in {watchdog_backoff:.0f}s …")
        _time.sleep(watchdog_backoff)
        # Re-create daemon so fresh state (offsets, pending tasks reset)
        from memory_os.adapters.telegram_polling import TelegramPollingDaemon as _TPD
        daemon = _TPD(
            config,
            system_prompt=getattr(args, "system_prompt", None),
            provider=getattr(args, "provider", None),
            model=getattr(args, "model", None),
            track_tasks=not getattr(args, "no_task_tracking", False),
            swarm_control=getattr(args, "swarm_control", False),
            swarm_watch_timeout=getattr(args, "swarm_watch_timeout", 10.0),
        )
    return 0

def _telegram_daemon_paths(root: Path) -> tuple[Path, Path]:
    data_dir = root / "data"
    return data_dir / "telegram-daemon.pid", data_dir / "telegram-daemon.log"

def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def _pid_is_telegram_daemon(pid: int, root: Path) -> bool:
    proc_dir = Path("/proc") / str(pid)
    if not proc_dir.exists():
        return _is_pid_alive(pid)
    try:
        argv = [
            part.decode("utf-8", errors="ignore")
            for part in (proc_dir / "cmdline").read_bytes().split(b"\x00")
            if part
        ]
        cwd = (proc_dir / "cwd").resolve()
    except OSError:
        return False
    return "telegram-daemon" in argv and any("memory_os" in part for part in argv) and cwd == root

def _pid_file_live_pid(pid_file: Path, root: Path) -> Optional[int]:
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        pid_file.unlink(missing_ok=True)
        return None
    if _is_pid_alive(pid) and _pid_is_telegram_daemon(pid, root):
        return pid
    pid_file.unlink(missing_ok=True)
    return None

def _discover_telegram_daemon_pids(root: Path) -> List[int]:
    proc_root = Path("/proc")
    if not proc_root.exists():
        return []
    pids: List[int] = []
    current_pid = os.getpid()
    for proc_dir in proc_root.iterdir():
        if not proc_dir.name.isdigit():
            continue
        pid = int(proc_dir.name)
        if pid == current_pid:
            continue
        try:
            argv = [
                part.decode("utf-8", errors="ignore")
                for part in (proc_dir / "cmdline").read_bytes().split(b"\x00")
                if part
            ]
            if "telegram-daemon" not in argv or not any("memory_os" in part for part in argv):
                continue
            cwd = (proc_dir / "cwd").resolve()
        except OSError:
            continue
        if cwd == root:
            pids.append(pid)
    return sorted(pids)

def _telegram_daemon_running_pid(root: Path, pid_file: Path) -> Optional[int]:
    pid = _pid_file_live_pid(pid_file, root)
    if pid:
        return pid
    discovered = _discover_telegram_daemon_pids(root)
    if discovered:
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(f"{discovered[0]}\n", encoding="utf-8")
        return discovered[0]
    return None

def cmd_telegram_daemon_control(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    import signal
    import subprocess
    import time as _time

    root = Path(config.root_dir).resolve()
    pid_file, log_file = _telegram_daemon_paths(root)
    action = args.telegram_daemon_action

    def _start() -> int:
        running_pid = _telegram_daemon_running_pid(root, pid_file)
        if running_pid:
            print(f"Telegram daemon is already running (PID {running_pid}).")
            return 0
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable,
            "-u",
            "-m",
            "memory_os",
            "--root",
            str(root),
            "telegram-daemon",
            "--swarm-control",
            "--swarm-watch-timeout",
            str(getattr(args, "swarm_watch_timeout", 0)),
            "--poll-interval",
            str(getattr(args, "poll_interval", 2.0)),
        ]
        if getattr(args, "no_task_tracking", False):
            cmd.append("--no-task-tracking")
        log_fh = log_file.open("a", encoding="utf-8")
        popen_kwargs: dict = {
            "cwd": str(root),
            "stdin": subprocess.DEVNULL,
            "stdout": log_fh,
            "stderr": subprocess.STDOUT,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True
        process = subprocess.Popen(cmd, **popen_kwargs)
        log_fh.close()
        pid_file.write_text(f"{process.pid}\n", encoding="utf-8")
        print(f"Telegram daemon started (PID {process.pid}).")
        print(f"log: {log_file}")
        return 0

    def _stop() -> int:
        running_pid = _telegram_daemon_running_pid(root, pid_file)
        if not running_pid:
            print("Telegram daemon is not running.")
            return 1
        os.kill(running_pid, signal.SIGTERM)
        deadline = _time.monotonic() + 3.0
        while _time.monotonic() < deadline:
            if not _is_pid_alive(running_pid):
                pid_file.unlink(missing_ok=True)
                print(f"Telegram daemon stopped (PID {running_pid}).")
                return 0
            _time.sleep(0.1)
        if getattr(args, "force", False):
            os.kill(running_pid, signal.SIGKILL)
            pid_file.unlink(missing_ok=True)
            print(f"Telegram daemon killed (PID {running_pid}).")
            return 0
        print(f"Telegram daemon did not stop after SIGTERM (PID {running_pid}). Use --force.")
        return 1

    if action == "start":
        return _start()
    if action == "stop":
        return _stop()
    if action == "restart":
        running_pid = _telegram_daemon_running_pid(root, pid_file)
        if running_pid:
            stop_code = _stop()
            if stop_code != 0:
                return stop_code
        return _start()
    if action == "status":
        running_pid = _telegram_daemon_running_pid(root, pid_file)
        if running_pid:
            print(f"Telegram daemon is RUNNING (PID {running_pid})")
            print(f"pid_file: {pid_file}")
            print(f"log: {log_file}")
            return 0
        print("Telegram daemon is STOPPED")
        print(f"pid_file: {pid_file}")
        print(f"log: {log_file}")
        return 1
    return 1
