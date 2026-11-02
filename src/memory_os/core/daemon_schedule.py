import time

class ScheduleEngine:
    def __init__(self):
        self.tasks = []

    def add_task(self, name: str, interval_seconds: float, func):
        if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, (int, float)):
            raise ValueError(f"interval_seconds must be a number, got {interval_seconds!r}")
        if interval_seconds != interval_seconds or interval_seconds in (float("inf"), float("-inf")):
            raise ValueError(f"interval_seconds must be finite, got {interval_seconds!r}")
        if interval_seconds < 0:
            raise ValueError(f"interval_seconds must be non-negative, got {interval_seconds!r}")
        self.tasks.append({
            "name": name,
            "interval": interval_seconds,
            "func": func,
            "last_run": time.time()
        })

    def run_pending(self, logger):
        now = time.time()
        for task in self.tasks:
            try:
                # A corrupt task record (e.g. a non-numeric interval that
                # somehow got past add_task's validation) must not crash the
                # whole scheduler loop's comparison, which would otherwise
                # take the entire daemon down with it.
                should_run = now - task["last_run"] >= task["interval"]
            except Exception as e:
                logger.error(f"Invalid schedule for task {task.get('name')}: {e}", exc_info=True)
                continue
            if not should_run:
                continue
            try:
                logger.info(f"Running scheduled task: {task['name']}")
                task["func"]()
            except Exception as e:
                logger.error(f"Error in scheduled task {task['name']}: {e}", exc_info=True)
            finally:
                task["last_run"] = time.time()

DEFAULT_SCHEDULE_CONFIG: dict = {
    "watch_transcript_sec": 5.0,
    "auto_compact_sec": 30.0,
    "link_infer_sec": 3600.0,
    "decay_nodes_sec": 24 * 3600.0,
    "telemetry_analysis_sec": 6 * 3600.0,
    "db_optimize_sec": 24 * 3600.0,
    "auto_dispatch_tasks_sec": 10.0,
    "watch_done_files_sec": 5.0,
    "watchdog_limits_sec": 30.0,
    "task_gc_sec": 3600.0,
    "housekeeping_sec": 60.0,
    "auto_compact_min_uncompacted": 3,
    "auto_compact_tokens_per_capsule": 2000,
    "ingest_provider": "gemini",
    "compact_provider": "gemini",
}
