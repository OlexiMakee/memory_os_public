import os
import time
import json
from pathlib import Path
from typing import Optional

class DaemonHousekeeping:
    def __init__(self, daemon):
        self.daemon = daemon
        self._done_dir = self.daemon.config.root_dir / "agent_context" / "done"
        self._done_dir.mkdir(parents=True, exist_ok=True)
        # Pre-populate from files already on disk: without this, every daemon
        # restart treats the entire historical done/ backlog as unprocessed
        # and re-relays all of it into claude's pane in one burst (confirmed
        # live: 2267 stale daemon.done_relay events fired in ~1s after a
        # restart). Mirrors telegram_polling.py's TelegramPollingDaemon.run()
        # startup scan, which already does this correctly.
        self._processed_done: set = {df.name for df in self._done_dir.glob("*.json")}

    @property
    def config(self):
        return self.daemon.config

    @property
    def logger(self):
        return self.daemon.logger

    @property
    def schedule_settings(self):
        return self.daemon.schedule_settings

    @property
    def alerts(self):
        return self.daemon.alerts

    def run_telemetry_analysis(self):
        from memory_os.toolkit.analyzer import OSPerformanceAnalyzer
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
        from memory_os.core.resource_guard import ResourceGuard
        
        guard = ResourceGuard(config=self.config)
        snapshot = guard.snapshot()
        if not guard.is_safe():
            self.logger.warning(
                f"Auto-compaction skipped: machine is under load (snapshot: {snapshot.to_dict()})."
            )
            return

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
                with open(events_path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            ev = json.loads(line)
                            if ev.get("event") == "memory.task_capsules.compacted":
                                for ts in ev.get("compacted_timestamps", []):
                                    compacted_timestamps.add(ts)
                        except Exception:
                            import sys as _sys
                            print('Ignored exception', file=_sys.stderr)

            uncompacted = [cap for cap in capsules if cap.get("timestamp") not in compacted_timestamps]

            if len(uncompacted) >= self.schedule_settings["auto_compact_min_uncompacted"]:
                self.logger.info(f"Auto-compacting {len(uncompacted)} uncompacted capsules...")
                estimated_tokens = len(uncompacted) * self.schedule_settings["auto_compact_tokens_per_capsule"]
                budget.add_usage(estimated_tokens)

                compactor.compact_capsules(provider=self.schedule_settings["compact_provider"], model="")
                self.logger.info("Auto-compaction complete.")
        except Exception as e:
            self.logger.error(f"Error during auto-compaction: {e}", exc_info=True)

    def auto_dispatch_tasks(self, limit: int = 3) -> dict:
        from memory_os.toolkit.dispatcher import DispatcherEngine
        from memory_os.toolkit.router_plan import RouterPlan
        from memory_os.toolkit.task_kernel import TaskKernel

        kernel = TaskKernel(self.config.root_dir)
        router = RouterPlan(self.config.root_dir)
        dispatcher = None
        pending = sorted(kernel.list_tasks(status="pending"), key=lambda t: t.get("created_at", ""))[:limit]

        result = {"seen": len(pending), "dispatched": 0, "blocked": 0, "skipped": 0, "errors": 0}
        for task in pending:
            task_id = task["id"]
            try:
                plan = router.route(task_id=task_id)
                blocked_reason = getattr(plan, "blocked_reason", None)
                if blocked_reason:
                    kernel.claim(task_id, agent="daemon:router", lease_minutes=15)
                    kernel.block(task_id, reason=blocked_reason)
                    result["blocked"] += 1
                    self.logger.warning(f"Auto-dispatch blocked {task_id}: {blocked_reason}")
                    continue
                if task.get("risk") == "high" or plan.requires_review:
                    self.logger.info(f"Auto-dispatch skipped {task_id}: review required.")
                    result["skipped"] += 1
                    continue

                kernel.claim(task_id, agent=f"daemon:{plan.agent}", lease_minutes=15)
                kernel.start(task_id)
                if dispatcher is None:
                    dispatcher = DispatcherEngine(self.config.root_dir)
                dispatch_result = dispatcher.dispatch_plan(plan)
                if dispatch_result.ok:
                    result["dispatched"] += 1
                    self.logger.info(
                        f"Auto-dispatched {task_id} via {dispatch_result.adapter}/{dispatch_result.agent}."
                    )
                else:
                    result["errors"] += 1
                    self.logger.warning(
                        f"Auto-dispatch failed {task_id}: {dispatch_result.error or dispatch_result.stderr[:120]}"
                    )
            except Exception as e:
                result["errors"] += 1
                self.logger.error(f"Auto-dispatch error for {task_id}: {e}", exc_info=True)
                try:
                    current = kernel.get(task_id)
                    if current and current.get("status") in ("claimed", "running"):
                        kernel.block(task_id, reason=f"auto-dispatch error: {e}")
                except Exception:
                    import sys as _sys
                    print('Ignored exception', file=_sys.stderr)
        return result

    def optimize_database(self):
        db_path = self.config.db_path
        if not db_path.exists():
            self.logger.info("Database does not exist yet; skipping optimization.")
            return

        size_before = db_path.stat().st_size
        try:
            from memory_os.core.core import MemoryOS

            MemoryOS(self.config).optimize_db()
            size_after = db_path.stat().st_size
            reclaimed = size_before - size_after
            self.logger.info(
                f"Database optimization complete: {size_before} -> {size_after} bytes "
                f"({reclaimed:+d} bytes reclaimed)."
            )
        except Exception as e:
            self.logger.error(f"Database optimization failed: {e}", exc_info=True)
            self.alerts.send_alert("Memory OS DB Optimization Error", str(e), is_critical=False)

    def run_link_infer(self):
        from memory_os.core.resource_guard import ResourceGuard
        guard = ResourceGuard(config=self.config)
        snapshot = guard.snapshot()
        if not guard.is_safe():
            self.logger.warning(
                f"Link inference skipped: machine is under load (snapshot: {snapshot.to_dict()})."
            )
            return
        try:
            from memory_os.toolkit.link_inferrer import LinkInferrer
            result = LinkInferrer(self.config).run(method="cascade", resource_mode="quiet")
            added = result.get("added", 0) if isinstance(result, dict) else 0
            self.logger.info(f"Link inference complete: {added} edges proposed.")
        except Exception as e:
            self.logger.error(f"Link inference failed: {e}", exc_info=True)

    def run_decay_nodes(self):
        from memory_os.core.resource_guard import ResourceGuard
        guard = ResourceGuard(config=self.config)
        snapshot = guard.snapshot()
        if not guard.is_safe():
            self.logger.warning(
                f"Decay nodes skipped: machine is under load (snapshot: {snapshot.to_dict()})."
            )
            return
        try:
            from memory_os.modules.lifecycle import LifecycleManager
            archived = LifecycleManager(self.config).decay_nodes(days_stale=30)
            self.logger.info(f"Decay nodes complete: {archived} node(s) archived.")
        except Exception as e:
            self.logger.error(f"Decay nodes failed: {e}", exc_info=True)

    def watch_done_files(self) -> None:
        import subprocess, shutil as _shutil
        try:
            for done_file in sorted(self._done_dir.glob("*.json")):
                if done_file.name in self._processed_done:
                    continue
                try:
                    payload = json.loads(done_file.read_text(encoding="utf-8"))
                except Exception:
                    continue
                task_id = payload.get("task_id", done_file.stem)
                sender = payload.get("sender", "agent")
                message = payload.get("message", "")
                self.logger.info(f"Done signal: task={task_id} from={sender}")
                events_path = self.config.root_dir / "agent_context" / "task_events.jsonl"
                events_path.parent.mkdir(parents=True, exist_ok=True)
                relay_event = json.dumps({
                    "event": "daemon.done_relay",
                    "task_id": task_id,
                    "sender": sender,
                    "message": message,
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }, ensure_ascii=False)
                with events_path.open("a", encoding="utf-8") as fh:
                    fh.write(relay_event + "\n")
                from memory_os.toolkit.multiplexer_manager import MultiplexerManager
                try:
                    summary = f"\n[DAEMON RELAY task={task_id}] from {sender}: {message[:120]}\n"
                    mgr = MultiplexerManager(self.config.root_dir)
                    target_pane = mgr.resolve_pane_target("claude")
                    if target_pane.startswith("%"):
                        mgr.send_keys(target_pane, summary, submit=True, unlock_buffers=True)
                except Exception:
                    import sys as _sys
                    print('Ignored exception', file=_sys.stderr)
                self._processed_done.add(done_file.name)
        except Exception as e:
            self.logger.error(f"watch_done_files error: {e}", exc_info=True)

    def watchdog_limits(self) -> None:
        try:
            from memory_os.toolkit.agent_console_scanner import AgentConsoleScanner
            from memory_os.toolkit.quota_monitor import AgentQuotaMonitor
            AgentConsoleScanner(self.config.root_dir).scan_once()
            monitor = AgentQuotaMonitor(self.config.root_dir)
            monitor.check_and_recover()
        except Exception as e:
            self.logger.error(f"watchdog_limits error: {e}", exc_info=True)

    def task_gc(self) -> None:
        try:
            from memory_os.toolkit.task_kernel import TaskKernel
            expired = TaskKernel(self.config.root_dir).expire_stale(hours=24.0)
            if expired:
                self.logger.info(f"task_gc expired {len(expired)} stale task(s): "
                                 + ", ".join(t["id"] for t in expired))
        except Exception as e:
            self.logger.error(f"task_gc error: {e}", exc_info=True)

    def housekeeping(self) -> None:
        try:
            from memory_os.toolkit.daemon_hygiene import DaemonHygiene
            from memory_os.toolkit.task_kernel import TaskKernel
            report = DaemonHygiene(self.config.root_dir).run_once()
            relay_watch = report.get("relay_watch", {})
            stale_actions = TaskKernel(self.config.root_dir).release_stale_leases()
            if relay_watch.get("lagging_done_count"):
                self.daemon.watch_done_files()
            if relay_watch.get("lagging_done_count") or relay_watch.get("stale_lease_count"):
                self.logger.warning(
                    "housekeeping flags: lagging_done=%s stale_leases=%s healed=%s",
                    relay_watch.get("lagging_done_count", 0),
                    relay_watch.get("stale_lease_count", 0),
                    len(stale_actions),
                )
            telegram_check = report.get("telegram_daemon", {})
            if telegram_check.get("restarted"):
                self.logger.warning("housekeeping: telegram-chat pane was dead, restarted")
            reconciler = report.get("agent_reconciler", {})
            if reconciler.get("restarted"):
                self.logger.warning(
                    "housekeeping: restarted ghost agent pane(s): %s",
                    ", ".join(reconciler["restarted"]),
                )
            if reconciler.get("protected"):
                self.logger.warning(
                    "housekeeping: protected ghost pane requires manual restart: %s",
                    ", ".join(reconciler["protected"]),
                )
            if reconciler.get("failed"):
                self.logger.error("housekeeping: ghost pane restart failed: %s", reconciler["failed"])
        except Exception as e:
            self.logger.error(f"housekeeping error: {e}", exc_info=True)
