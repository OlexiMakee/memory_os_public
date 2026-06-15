"""
Background Watchdog Daemon for Memory OS.
Monitors transcript logs and automatically triggers memory ingestion.
"""

import os
import sqlite3
import time
import logging
import signal
import http.server
import threading
import json
from pathlib import Path
from typing import Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.transcript_ingestor import TranscriptIngestor
from memory_os.core.alerts import AlertManager
from memory_os.toolkit.analyzer import OSPerformanceAnalyzer
from memory_os.core.auditors import AuditorManager, MockMLEmbeddingAuditor, MockOllamaAuditor
from urllib.parse import urlparse, parse_qs

class DaemonHttpHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            status_data = self.server.daemon.get_status_dict()
            self.wfile.write(json.dumps(status_data).encode("utf-8"))
        elif parsed.path == "/auditors/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            status_data = self.server.daemon.auditor_manager.get_status()
            
            # Basic CPU metric using loadavg
            try:
                load1, load5, load15 = os.getloadavg()
                cpu_percent = min(100.0, (load1 / os.cpu_count()) * 100)
            except Exception:
                cpu_percent = 0.0
                
            resp = {
                "auditors": status_data,
                "metrics": {
                    "cpu_percent": round(cpu_percent, 1),
                    "ram_percent": 45.0  # Placeholder without psutil
                }
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
        else:
            self.send_response(404)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        name = qs.get("name", [""])[0]

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        if parsed.path == "/sync":
            self.server.daemon.logger.info("IPC request: Triggering manual sync")
            self.server.daemon.check_file(force=True)
            self.wfile.write(json.dumps({"status": "sync_triggered"}).encode("utf-8"))
        elif parsed.path == "/stop":
            self.server.daemon.logger.info("IPC request: Shutting down daemon")
            self.server.daemon.is_running = False
            self.wfile.write(json.dumps({"status": "stopping"}).encode("utf-8"))
        elif parsed.path == "/auditors/start":
            self.server.daemon.auditor_manager.start_auditor(name)
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
        elif parsed.path == "/auditors/pause":
            self.server.daemon.auditor_manager.pause_auditor(name)
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
        elif parsed.path == "/auditors/stop":
            self.server.daemon.auditor_manager.stop_auditor(name)
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
        elif parsed.path == "/space":
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                post_data = self.rfile.read(content_length)
                try:
                    payload = json.loads(post_data.decode("utf-8"))
                    new_space = payload.get("space", "default")
                    self.server.daemon.logger.info(f"IPC request: Switching space to '{new_space}'")
                    self.server.daemon.switch_space(new_space)
                    self.wfile.write(json.dumps({"status": "space_switched", "space": new_space}).encode("utf-8"))
                except Exception as e:
                    self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            else:
                self.wfile.write(json.dumps({"error": "Missing payload"}).encode("utf-8"))
        else:
            # Override 200 sent above for 404
            pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

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
        self.status_file = self.data_dir / "daemon_status.json"

        self.alerts = AlertManager(config)
        self._setup_logging()
        self.last_mtime = 0.0
        self._last_change_time: float = 0.0  # debounce: wall-clock time of last detected mtime change
        self._transcript_cursor: int = self._load_cursor()  # line count at last successful ingestion
        self.http_server = None

        self.auditor_manager = AuditorManager()
        self.auditor_manager.register(MockMLEmbeddingAuditor())
        self.auditor_manager.register(MockOllamaAuditor())

        self.scheduler = ScheduleEngine()
        # Watch transcript every 5 seconds
        self.scheduler.add_task("watch_transcript", 5.0, self.check_file)
        # Check for auto-compaction every 30 seconds
        self.scheduler.add_task("auto_compact", 30.0, self.auto_compact)
        # Run telemetry analysis every 6 hours
        self.scheduler.add_task("telemetry_analysis", 6 * 3600, self.run_telemetry_analysis)
        # Run database optimization and vacuum every 24 hours
        self.scheduler.add_task("db_optimize", 24 * 3600, self.optimize_database)

    def _setup_logging(self):
        self.logger = logging.getLogger("MemoryDaemon")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.FileHandler(self.log_file, encoding="utf-8")
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def get_status_dict(self) -> dict:
        import json
        from datetime import datetime
        status_data = {}
        if self.status_file.exists():
            try:
                status_data = json.loads(self.status_file.read_text(encoding="utf-8"))
            except Exception:
                pass

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
        self.config.space = new_space
        self.logger.info(f"Daemon context switched to space: {new_space}")
        self.write_status()

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

    def start_ipc_server(self):
        port = self.config.daemon_port
        server_address = ("127.0.0.1", port)
        class CustomHttpServer(http.server.HTTPServer):
            def __init__(self, addr, handler, daemon):
                self.daemon = daemon
                super().__init__(addr, handler)

        try:
            self.http_server = CustomHttpServer(server_address, DaemonHttpHandler, self)
            self.logger.info(f"IPC Server listening on http://127.0.0.1:{port}")
            self.ipc_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
            self.ipc_thread.start()
        except Exception as e:
            self.logger.error(f"Failed to start IPC Server: {e}")
            self.http_server = None

    def write_pid(self):
        self.pid_file.write_text(str(os.getpid()), encoding="utf-8")

    def remove_pid(self):
        if self.pid_file.exists():
            self.pid_file.unlink()

    def handle_signal(self, signum, frame):
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.is_running = False

    # How many seconds of silence after the last write before we process.
    _DEBOUNCE_SECS: float = 3.0

    def _count_lines(self) -> int:
        """Count lines in transcript file using binary read (fast, cross-platform)."""
        try:
            with open(self.transcript_path, "rb") as f:
                return sum(1 for _ in f)
        except OSError:
            return 0

    def _load_cursor(self) -> int:
        """Load transcript line cursor from daemon status file (survives restarts)."""
        try:
            if self.status_file.exists():
                data = json.loads(self.status_file.read_text(encoding="utf-8"))
                return int(data.get("transcript_cursor", 0))
        except Exception:
            pass
        return 0

    def _do_ingest(self):
        """Run TranscriptIngestor and update status. Extracted for reuse by force-sync IPC."""
        try:
            ingestor = TranscriptIngestor(self.config)
            capsules = ingestor.ingest(self.transcript_path, provider="gemini", model="")

            from datetime import datetime
            status_data = {}
            if self.status_file.exists():
                try:
                    status_data = json.loads(self.status_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
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

        # First run: record baseline without processing.
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

        # Mark the moment we first see a new mtime.
        if current_mtime > self.last_mtime:
            self.last_mtime = current_mtime
            if self._last_change_time == 0.0:
                self._last_change_time = now

        # Nothing pending.
        if self._last_change_time == 0.0:
            return

        # Wait for the file to stop changing (debounce).
        if now - self._last_change_time < self._DEBOUNCE_SECS:
            return

        # Confirm the file actually grew — avoids LLM call on metadata-only updates.
        new_line_count = self._count_lines()
        if new_line_count <= self._transcript_cursor:
            self._last_change_time = 0.0
            return

        self.logger.info(
            f"{new_line_count - self._transcript_cursor} new lines in "
            f"{self.transcript_path.name} — triggering ingestion."
        )
        self._transcript_cursor = new_line_count
        self._last_change_time = 0.0
        self._do_ingest()

    def run_telemetry_analysis(self):
        analyzer = OSPerformanceAnalyzer(self.config)
        result = analyzer.generate_insights()
        status = result.get("status")
        if status == "success":
            self.logger.info(f"Telemetry analysis complete: {result.get('created_proposals', 0)} new proposals written.")
        elif status == "skipped":
            self.logger.info(f"Telemetry analysis skipped: {result.get('reason')}")
        else:
            self.logger.error(f"Telemetry analysis failed: {result.get('reason')}")

    def auto_compact(self):
        from memory_os.core.budget import BudgetManager
        from memory_os.modules.compactor import MemoryCompactor

        budget = BudgetManager(self.config)
        if budget.is_budget_exhausted():
            self.logger.warning("Auto-compaction skipped: daily token budget is exhausted.")
            return

        try:
            compactor = MemoryCompactor(config=self.config)
            task_capsules_path = self.config.capsules_file
            events_path = self.config.memory_dir / "events.jsonl"

            if not task_capsules_path.exists():
                return

            capsules = [c.to_dict() for c in compactor.repository.get_task_capsules()]

            compacted_timestamps = set()
            if events_path.exists():
                import json
                with open(events_path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            ev = json.loads(line)
                            if ev.get("event") == "memory.task_capsules.compacted":
                                for ts in ev.get("compacted_timestamps", []):
                                    compacted_timestamps.add(ts)
                        except Exception:
                            pass

            uncompacted = [cap for cap in capsules if cap.get("timestamp") not in compacted_timestamps]

            if len(uncompacted) >= 3:
                self.logger.info(f"Auto-compacting {len(uncompacted)} uncompacted capsules...")
                estimated_tokens = len(uncompacted) * 2000
                budget.add_usage(estimated_tokens)

                compactor.compact_capsules(provider="gemini", model="")
                self.logger.info("Auto-compaction complete.")
        except Exception as e:
            self.logger.error(f"Error during auto-compaction: {e}", exc_info=True)

    def optimize_database(self):
        """Run VACUUM and ANALYZE on the SQLite database to reclaim space and refresh query planner stats."""
        db_path = self.config.db_path
        if not db_path.exists():
            self.logger.info("Database does not exist yet; skipping optimization.")
            return

        size_before = db_path.stat().st_size
        try:
            conn = sqlite3.connect(str(db_path))
            try:
                # Checkpoint WAL file before vacuuming so VACUUM can reclaim all free pages
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("VACUUM")
                conn.execute("ANALYZE")
            finally:
                conn.close()
            size_after = db_path.stat().st_size
            reclaimed = size_before - size_after
            self.logger.info(
                f"Database optimization complete: {size_before} -> {size_after} bytes "
                f"({reclaimed:+d} bytes reclaimed)."
            )
        except Exception as e:
            self.logger.error(f"Database optimization failed: {e}", exc_info=True)
            self.alerts.send_alert("Memory OS DB Optimization Error", str(e), is_critical=False)

    def run(self):
        signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)
        import sys as _sys
        if _sys.platform == "win32" and hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, self.handle_signal)

        self.write_pid()
        self.write_status()
        self.logger.info(f"Daemon started. Scheduler active.")
        self.start_ipc_server()

        try:
            while self.is_running:
                self.scheduler.run_pending(self.logger)
                time.sleep(1.0)  # Main loop tick
                # Periodically update last activity in status
                self.write_status()
        except Exception as e:
            self.logger.critical(f"Daemon crashed: {e}")
            self.alerts.send_alert("Memory OS Daemon Crash", str(e), is_critical=True)
            self.write_status(error=f"Crashed: {e}")
        finally:
            self.logger.info("Daemon stopping...")
            if self.http_server:
                self.logger.info("Stopping IPC Server...")
                self.http_server.shutdown()
                self.http_server.server_close()
            self.auditor_manager.shutdown()
            self.logger.info("Daemon stopped.")
            self.remove_pid()
            # Update status to stopped
            self.is_running = False
            self.write_status()
