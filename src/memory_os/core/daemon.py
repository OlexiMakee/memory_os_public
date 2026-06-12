"""
Background Watchdog Daemon for Memory OS.
Monitors transcript logs and automatically triggers memory ingestion.
"""

import os
import time
import logging
import signal
from pathlib import Path

from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.transcript_ingestor import TranscriptIngestor
from memory_os.core.alerts import AlertManager

class ScheduleEngine:
    def __init__(self):
        self.tasks = []
        
    def add_task(self, name: str, interval_seconds: float, func):
        self.tasks.append({
            "name": name,
            "interval": interval_seconds,
            "func": func,
            "last_run": time.time()
        })
        
    def run_pending(self, logger):
        now = time.time()
        for task in self.tasks:
            if now - task["last_run"] >= task["interval"]:
                try:
                    logger.info(f"Running scheduled task: {task['name']}")
                    task["func"]()
                except Exception as e:
                    logger.error(f"Error in scheduled task {task['name']}: {e}", exc_info=True)
                finally:
                    task["last_run"] = time.time()

class MemoryDaemon:
    def __init__(self, config: MemoryOSConfig, transcript_path: Path):
        self.config = config
        self.transcript_path = transcript_path
        self.is_running = True
        self.data_dir = config.root_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.log_file = self.data_dir / "daemon.log"
        self.pid_file = self.data_dir / "daemon.pid"
        
        self.alerts = AlertManager(config)
        self._setup_logging()
        self.last_mtime = 0.0
        
        self.scheduler = ScheduleEngine()
        # Watch transcript every 5 seconds
        self.scheduler.add_task("watch_transcript", 5.0, self.check_file)
        # We can add sync or compact tasks here (e.g., every 12 hours)
        # self.scheduler.add_task("sync_memory", 12 * 3600, self.sync_memory)

    def _setup_logging(self):
        self.logger = logging.getLogger("MemoryDaemon")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.FileHandler(self.log_file, encoding="utf-8")
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def write_pid(self):
        self.pid_file.write_text(str(os.getpid()), encoding="utf-8")

    def remove_pid(self):
        if self.pid_file.exists():
            self.pid_file.unlink()

    def handle_signal(self, signum, frame):
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.is_running = False

    def check_file(self):
        if not self.transcript_path.exists():
            return

        current_mtime = os.path.getmtime(self.transcript_path)
        if self.last_mtime == 0.0:
            # First run, just record the time
            self.last_mtime = current_mtime
            self.logger.info(f"Baseline established for {self.transcript_path.name}")
            return

        if current_mtime > self.last_mtime:
            self.logger.info(f"Detected changes in {self.transcript_path.name}. Triggering ingestion...")
            try:
                ingestor = TranscriptIngestor(self.config)
                # Defaults to cheap models for background tasks to save cost
                capsules = ingestor.ingest(self.transcript_path, provider="gemini", model="")
                if capsules:
                    self.logger.info(f"Successfully extracted {len(capsules)} task capsules.")
                else:
                    self.logger.info("No new completed tasks found in transcript.")
            except Exception as e:
                self.logger.error(f"Error during ingestion: {e}", exc_info=True)
                self.alerts.send_alert("Memory OS Daemon Error", str(e), is_critical=True)
            finally:
                self.last_mtime = current_mtime

    def run(self):
        signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)
        
        self.write_pid()
        self.logger.info(f"Daemon started. Scheduler active.")
        
        try:
            while self.is_running:
                self.scheduler.run_pending(self.logger)
                time.sleep(1.0)  # Main loop tick
        except Exception as e:
            self.logger.critical(f"Daemon crashed: {e}")
            self.alerts.send_alert("Memory OS Daemon Crash", str(e), is_critical=True)
        finally:
            self.logger.info("Daemon stopped.")
            self.remove_pid()
