"""
Background Watchdog Daemon for Memory OS.
Monitors transcript logs and automatically triggers memory ingestion.
"""

import os
import time
import logging
import signal
import json
from pathlib import Path
from typing import Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.safe_id import validate_safe_id
from memory_os.toolkit.transcript_ingestor import TranscriptIngestor
from memory_os.core.alerts import AlertManager
from memory_os.core.auditors import AuditorManager, MockMLEmbeddingAuditor, MockOllamaAuditor

from memory_os.core.daemon_ipc import DaemonIPCServer
from memory_os.core.daemon_schedule import ScheduleEngine, DEFAULT_SCHEDULE_CONFIG
from memory_os.core.daemon_housekeeping import DaemonHousekeeping

class MemoryDaemon:
    # How many seconds of silence after the last write before we process.
    _DEBOUNCE_SECS: float = 3.0

    def __init__(self, config: MemoryOSConfig, transcript_path: Path):
        self.config = config
        self.transcript_path = transcript_path
        self.is_running = True
        self.data_dir = config.root_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.log_file = self.data_dir / "daemon.log"
        self.pid_file = self.data_dir / "daemon.pid"
        self.status_file = self.data_dir / "daemon_status.json"
        self.socket_path = str(self.data_dir / "memory_os.sock")

        self.alerts = AlertManager(config)
        self._setup_logging()
        self.last_mtime = 0.0
        self._last_change_time: float = 0.0  # debounce: wall-clock time of last detected mtime change
        self._transcript_cursor: int = self._load_cursor()  # line count at last successful ingestion
        
        self.auditor_manager = AuditorManager()
        if os.environ.get("MEMORY_OS_ENABLE_MOCK_AUDITORS") == "1":
            self.auditor_manager.register(MockMLEmbeddingAuditor())
            self.auditor_manager.register(MockOllamaAuditor())

        self.schedule_settings: dict = {
            **DEFAULT_SCHEDULE_CONFIG,
            **config.data.get("daemon", {}),
        }

        self.ipc_server = DaemonIPCServer(self)
        self.housekeeper = DaemonHousekeeping(self)
        self.scheduler = ScheduleEngine()
        
        # Watch transcript every 5 seconds
        self.scheduler.add_task("watch_transcript", self.schedule_settings["watch_transcript_sec"], self.check_file)
        # Check for auto-compaction every 30 seconds
        self.scheduler.add_task("auto_compact", self.schedule_settings["auto_compact_sec"], self.housekeeper.auto_compact)
        # Stage-0 cascade link inference every hour (BM25 + structural, no LLM)
        self.scheduler.add_task("link_infer", self.schedule_settings["link_infer_sec"], self.housekeeper.run_link_infer)
        # Algorithmic decay every 24 hours (Ebbinghaus forgetting for unaccessed nodes)
        self.scheduler.add_task("decay_nodes", self.schedule_settings["decay_nodes_sec"], self.housekeeper.run_decay_nodes)
        # Run telemetry analysis every 6 hours
        self.scheduler.add_task("telemetry_analysis", self.schedule_settings["telemetry_analysis_sec"], self.housekeeper.run_telemetry_analysis)
        # Run database optimization and vacuum every 24 hours
        self.scheduler.add_task("db_optimize", self.schedule_settings["db_optimize_sec"], self.housekeeper.optimize_database)
        # Agentic OS Phase 5: poll pending task queue and dispatch safe tasks.
        self.scheduler.add_task("auto_dispatch_tasks", self.schedule_settings["auto_dispatch_tasks_sec"], self.housekeeper.auto_dispatch_tasks)
        # Watch agent_context/done/ for STATUS_REPORT signals and relay to claude.
        self.scheduler.add_task("watch_done_files", self.schedule_settings["watch_done_files_sec"], self.housekeeper.watch_done_files)
        # Periodic watchdog to monitor rate limits, auto-switch models, and notify users via Telegram
        self.scheduler.add_task("watchdog_limits", self.schedule_settings["watchdog_limits_sec"], self.housekeeper.watchdog_limits)
        # Auto-close chat-originated kernel tasks abandoned for over a day
        self.scheduler.add_task("task_gc", self.schedule_settings["task_gc_sec"], self.housekeeper.task_gc)
        # One truth source for runtime/session state and relay lag snapshots
        self.scheduler.add_task("housekeeping", self.schedule_settings["housekeeping_sec"], self.housekeeper.housekeeping)

    def _setup_logging(self):
        # A shared "MemoryDaemon" logger name meant every instance after the
        # first in a process (any test, or repeated construction) silently
        # wrote through the first instance's already-attached handler --
        # test daemons were leaking real log lines into this repo's own
        # data/daemon.log. id(self) keeps each instance's handler isolated.
        self.logger = logging.getLogger(f"MemoryDaemon.{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        if not self.logger.handlers:
            handler = logging.FileHandler(self.log_file, encoding="utf-8")
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def _read_status_file(self) -> dict:
        if not self.status_file.exists():
            return {}
        try:
            return json.loads(self.status_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def get_status_dict(self) -> dict:
        from datetime import datetime
        status_data = self._read_status_file()

        status_data.update({
            "status": "running" if self.is_running else "stopped",
            "pid": os.getpid(),
            "last_activity_time": datetime.now().isoformat(timespec="seconds"),
            "transcript_cursor": self._transcript_cursor,
            "config": {
                "space": self.config.space,
                "transcript_path": str(self.transcript_path),
                "db_path": str(self.config.db_path),
                "daemon_port": self.config.daemon_port
            }
        })
        return status_data

    def switch_space(self, new_space: str):
        try:
            validate_safe_id(new_space, "space")
        except ValueError:
            self.logger.warning(f"Rejected unsafe space '{new_space}'; keeping '{self.config.space}'")
            return False
        self.config.space = new_space
        self.logger.info(f"Daemon context switched to space: {new_space}")
        self.write_status()
        return True

    def write_status(self, error: Optional[str] = None):
        import json
        from datetime import datetime
        try:
            status_data = self.get_status_dict()
            if error is not None:
                status_data["last_ingestion_error"] = error
                status_data["last_ingestion_error_time"] = datetime.now().isoformat(timespec="seconds")
            elif error == "":
                status_data["last_ingestion_error"] = None

            self.status_file.write_text(json.dumps(status_data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            self.logger.error(f"Failed to write daemon status file: {e}")

    def write_pid(self):
        self.pid_file.write_text(str(os.getpid()), encoding="utf-8")

    def remove_pid(self):
        if self.pid_file.exists():
            self.pid_file.unlink()

    def handle_signal(self, signum, frame):
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.is_running = False

    def _count_lines(self) -> int:
        try:
            with open(self.transcript_path, "rb") as f:
                return sum(1 for _ in f)
        except OSError:
            return 0

    def _load_cursor(self) -> int:
        return int(self._read_status_file().get("transcript_cursor", 0))

    def _do_ingest(self):
        try:
            ingestor = TranscriptIngestor(self.config)
            capsules = ingestor.ingest(self.transcript_path, provider=self.schedule_settings["ingest_provider"], model="")

            from datetime import datetime
            status_data = self._read_status_file()
            status_data["last_ingestion_time"] = datetime.now().isoformat(timespec="seconds")
            status_data["last_ingestion_error"] = None
            status_data["transcript_cursor"] = self._transcript_cursor
            self.status_file.write_text(json.dumps(status_data, indent=2), encoding="utf-8")

            if capsules:
                self.logger.info(f"Extracted {len(capsules)} task capsules.")
            else:
                self.logger.info("No new completed tasks found in transcript.")
        except Exception as e:
            self.logger.error(f"Error during ingestion: {e}", exc_info=True)
            self.alerts.send_alert("Memory OS Daemon Error", str(e), is_critical=True)
            self.write_status(error=str(e))

    def check_file(self, force: bool = False):
        if not self.transcript_path.exists():
            return

        current_mtime = os.path.getmtime(self.transcript_path)

        if self.last_mtime == 0.0 and not force:
            self.last_mtime = current_mtime
            self._transcript_cursor = self._count_lines()
            self.logger.info(
                f"Baseline: {self.transcript_path.name} "
                f"({self._transcript_cursor} lines already present, will process only new lines)"
            )
            self.write_status()
            return

        if force:
            self._do_ingest()
            self.last_mtime = current_mtime
            return

        now = time.time()

        if current_mtime > self.last_mtime:
            self.last_mtime = current_mtime
            if self._last_change_time == 0.0:
                self._last_change_time = now

        if self._last_change_time == 0.0:
            return

        if now - self._last_change_time < self._DEBOUNCE_SECS:
            return

        new_line_count = self._count_lines()
        if new_line_count < self._transcript_cursor:
            self.logger.info(
                f"{self.transcript_path.name} shrank from {self._transcript_cursor} to "
                f"{new_line_count} lines — resetting cursor."
            )
            self._transcript_cursor = new_line_count
            self._last_change_time = 0.0
            return
        if new_line_count == self._transcript_cursor:
            self._last_change_time = 0.0
            return

        self.logger.info(
            f"{new_line_count - self._transcript_cursor} new lines in "
            f"{self.transcript_path.name} — triggering ingestion."
        )
        self._transcript_cursor = new_line_count
        self._last_change_time = 0.0
        self._do_ingest()

    def run_script(self, script_path: str, env: Optional[dict] = None) -> dict:
        import subprocess
        try:
            result = subprocess.run(
                ["bash", script_path],
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, **(env or {})},
            )
            self.logger.info(f"run_script {script_path}: exit {result.returncode}")
            return {
                "returncode": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-2000:],
            }
        except Exception as e:
            self.logger.error(f"run_script {script_path} failed: {e}")
            return {"returncode": -1, "stdout": "", "stderr": str(e)}

    def run(self):
        signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)
        import sys as _sys
        if _sys.platform == "win32" and hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, self.handle_signal)

        self.write_pid()
        self.write_status()
        self.logger.info(f"Daemon started. Scheduler active.")
        self.ipc_server.start()

        try:
            while self.is_running:
                self.scheduler.run_pending(self.logger)
                time.sleep(1.0)
                self.write_status()
        except Exception as e:
            self.logger.critical(f"Daemon crashed: {e}")
            self.alerts.send_alert("Memory OS Daemon Crash", str(e), is_critical=True)
            self.write_status(error=f"Crashed: {e}")
        finally:
            self.logger.info("Daemon stopping...")
            self.ipc_server.stop()
            self.auditor_manager.shutdown()
            self.logger.info("Daemon stopped.")
            self.remove_pid()
            self.is_running = False
            self.write_status()

    # Public interface proxy methods for housekeeping
    def run_telemetry_analysis(self): return self.housekeeper.run_telemetry_analysis()
    def auto_compact(self): return self.housekeeper.auto_compact()
    def auto_dispatch_tasks(self, limit: int = 3): return self.housekeeper.auto_dispatch_tasks(limit)
    def optimize_database(self): return self.housekeeper.optimize_database()
    def run_link_infer(self): return self.housekeeper.run_link_infer()
    def run_decay_nodes(self): return self.housekeeper.run_decay_nodes()
    def watch_done_files(self): return self.housekeeper.watch_done_files()
    def watchdog_limits(self): return self.housekeeper.watchdog_limits()
    def task_gc(self): return self.housekeeper.task_gc()
    def housekeeping(self): return self.housekeeper.housekeeping()

    # Public interface proxy methods for IPC
    def start_ipc_server(self): return self.ipc_server.start()
    
    @property
    def http_server(self): return self.ipc_server.http_server

    @property
    def unix_server(self): return self.ipc_server.unix_server

    # Internal state proxy for backwards compatibility with tests
    @property
    def _processed_done(self): return self.housekeeper._processed_done

    @_processed_done.setter
    def _processed_done(self, value): self.housekeeper._processed_done = value

    @property
    def _done_dir(self): return self.housekeeper._done_dir
