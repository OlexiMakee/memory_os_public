"""Background relay duties for the Telegram polling daemon.

Runs each poll cycle after updates are processed: relays completed
swarm task results and stray agent→telegram inbox messages back to
chats, and restarts the core daemon if it dies or hangs.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class _RelayMixin:
    def _watch_core_daemon(self) -> None:
        """Restart the core daemon if it died or hung, and tell the user.

        The daemon was once down for four days before anyone noticed — this
        adapter is the only other always-on process, so it owns the watch.
        Checked every 5 minutes via a live IPC /status call.

        Regression: this used to read data/daemon_status.json's
        last_activity_time off disk and treat it stale after 10 minutes.
        That field is only ever computed in-memory inside
        MemoryDaemon.get_status_dict() for the IPC response -- it is never
        actually persisted to the status file by normal daemon operation, so
        the on-disk copy was permanently stale and this fired false "daemon
        dead/hung" alerts (and pointless restarts) against a daemon that was
        alive and responding fine. A successful IPC round-trip is itself
        proof of liveness; no separate staleness heuristic is needed.
        """
        now = time.time()
        if now - getattr(self, "_daemon_watch_last", 0) < 300:
            return
        self._daemon_watch_last = now
        try:
            root = self._root
            from memory_os.toolkit.daemon_client import DaemonClient

            response = DaemonClient(root, self.config.daemon_port, timeout=5).request("/status")
            alive = response.ok
            if alive:
                self._daemon_down_since = 0.0
                return

            first_detection = not getattr(self, "_daemon_down_since", 0.0)
            if first_detection:
                self._daemon_down_since = now
            logger.warning("[telegram] core daemon dead or hung — restarting")
            import subprocess
            import sys as _sys
            subprocess.Popen(
                [_sys.executable, "-m", "memory_os", "--root", str(root), "daemon", "start"],
                cwd=str(root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if first_detection:
                for cid in self._allowed_chat_ids():
                    chat_id = int(cid) if cid.isdigit() else cid
                    self._send_text(chat_id, "⚠️ Core daemon був мертвий/завис — перезапускаю автоматично.")
        except Exception as exc:
            logger.warning(f"[telegram] daemon watch failed: {exc}")

    def _relay_telegram_inbox(self) -> None:
        """Deliver UNREAD inbox/telegram.jsonl messages to allowed chats.

        Task-tracked relays cover only known task_ids; anything an agent
        sends to recipient 'telegram' outside that flow (untracked task ids,
        late replies after the 60s timeout) previously rotted unread. The
        per-recipient read cursor makes this loss-free and idempotent."""
        try:
            from memory_os.toolkit.agent_comm import AgentComm
            comm = AgentComm(self._root)
            # first run ever: fast-forward past the historical backlog —
            # relaying starts from this moment, not from hundreds of old rows
            if comm.fast_forward_inbox_if_uninitialized("telegram"):
                return
            result = comm.inbox("telegram", limit=10)
            messages = result.get("messages", [])
            if not messages:
                return
            chat_ids = self._allowed_chat_ids()
            if not chat_ids:
                return
            already_sent_tasks = self._relayed_done_tasks
            for msg in sorted(messages, key=lambda m: m.get("_idx", 0)):
                task_id = msg.get("task_id", "")
                # task-tracked relay already delivered (or will deliver) these
                if task_id and (task_id in already_sent_tasks or task_id in self._swarm_pending_tasks):
                    continue
                sender = msg.get("sender", "agent")
                text = msg.get("message", "")
                if not text:
                    continue
                for cid in chat_ids:
                    chat_id = int(cid) if cid.isdigit() else cid
                    self._send_text(chat_id, f"[{sender}] {text}")
        except Exception as exc:
            logger.warning(f"[telegram] inbox relay failed: {exc}")

    def _check_and_relay_done_tasks(self) -> None:
        from datetime import datetime, timezone
        root = self._root
        done_dir = root / "agent_context" / "done"
        done_dir.mkdir(parents=True, exist_ok=True)

        now = time.time()
        for task_id, item in list(self._swarm_pending_tasks.items()):
            if task_id in self._relayed_done_tasks:
                continue
            if task_id in self._actively_monitored:
                continue  # AgentStateMonitor thread is handling this task
            if isinstance(item, dict):
                chat_id = item.get("chat_id")
                prompt = item.get("prompt", "")
                created_ts = item.get("ts", now)
                attempt_id = item.get("attempt_id")
            else:
                chat_id = item
                prompt = ""
                created_ts = now
                attempt_id = None

            done_file = done_dir / f"{task_id}.json"
            if done_file.exists():
                try:
                    data = json.loads(done_file.read_text(encoding="utf-8"))
                    sender = data.get("sender", "agent")
                    msg = data.get("message", "")
                    if attempt_id:
                        try:
                            from memory_os.toolkit.loop_kernel import LoopKernel

                            LoopKernel(root).record_verifier(
                                task_id,
                                attempt_id,
                                verifier="telegram_async_relay",
                                verdict="pass",
                                feedback=f"STATUS_REPORT received from {sender}",
                            )
                        except Exception as exc:
                            logger.warning(f"[telegram] loop async pass record failed for {task_id}: {exc}")
                    logger.info(f"[telegram] RELAYING DONE SIGNAL task={task_id} to chat={chat_id}")
                    if msg:
                        sent = self._send_text(chat_id, msg)
                        if not sent:
                            self._append_task_event({
                                "event": "telegram.done_relay_failed",
                                "task_id": task_id,
                                "sender": sender,
                                "chat_ref": self._subject_ref("chat", chat_id),
                                "reason": "send_message returned ok=false",
                            })
                            continue
                        self._append_task_event({
                            "event": "telegram.done_relay",
                            "task_id": task_id,
                            "sender": sender,
                            "chat_ref": self._subject_ref("chat", chat_id),
                        })

                    # Worktree late patch application
                    wt_path_str = item.get("worktree_path") if isinstance(item, dict) else None
                    baseline = item.get("baseline_commit") if isinstance(item, dict) else None
                    if wt_path_str and baseline:
                        try:
                            from memory_os.toolkit.worktree import AgentWorktreeManager
                            wt_manager = AgentWorktreeManager(root)
                            wt_manager.apply_changes_and_remove(Path(wt_path_str), baseline)
                        except Exception as wt_exc:
                            logger.warning(f"[telegram] late worktree patch apply failed for {task_id}: {wt_exc}")

                    self._relayed_done_tasks.add(task_id)
                    del self._swarm_pending_tasks[task_id]
                except Exception as exc:
                    logger.warning(f"[telegram] done relay failed for {task_id}: {exc}")
            elif (now - created_ts) > 600.0:
                # Agent truly silent for 10 min.
                logger.warning(f"[telegram] task={task_id} timed out (600s, no STATUS_REPORT). Dropping.")
                timeout_msg = f"⏰ Задача `{task_id}` перевищила ліміт часу виконання (10 хвилин) і була скасована."
                if attempt_id:
                    try:
                        from memory_os.toolkit.loop_kernel import LoopKernel

                        LoopKernel(root).abandon_attempt(task_id, attempt_id, "async relay timeout")
                    except Exception as exc:
                        logger.warning(f"[telegram] loop async timeout record failed for {task_id}: {exc}")

                # Worktree timeout cleanup
                wt_path_str = item.get("worktree_path") if isinstance(item, dict) else None
                if wt_path_str:
                    try:
                        from memory_os.toolkit.worktree import AgentWorktreeManager
                        AgentWorktreeManager(root).remove_worktree(Path(wt_path_str))
                    except Exception as wt_exc:
                        logger.warning(f"[telegram] late worktree remove failed for {task_id}: {wt_exc}")

                self._send_text(chat_id, timeout_msg)
                self._relayed_done_tasks.add(task_id)
                del self._swarm_pending_tasks[task_id]
            else:
                # Send status update every 60 seconds
                last_notify = item.get("last_notified_at", created_ts) if isinstance(item, dict) else created_ts
                if now - last_notify >= 60.0:
                    agent_id = item.get("agent_id", "agent") if isinstance(item, dict) else "agent"

                    status_text = "в процесі виконання"
                    try:
                        from memory_os.toolkit.task_kernel import TaskKernel
                        task_data = TaskKernel(root).get(task_id)
                        if task_data:
                            if task_data.get("status") == "blocked":
                                status_text = f"⚠️ заблокована: {task_data.get('blocked_reason', 'невідома причина')}"
                            elif task_data.get("status") == "done":
                                continue
                    except Exception as _e:
                        import sys as _sys
                        print(f'Ignored exception: {_e}', file=_sys.stderr)

                    error_text = None
                    try:
                        from memory_os.toolkit.multiplexer_manager import MultiplexerManager
                        from memory_os.toolkit.console_parser import get_parser
                        mgr = MultiplexerManager(root)
                        target = mgr.resolve_pane_target(agent_id)
                        pane_text = mgr.capture_pane(target, lines=30)
                        if pane_text:
                            parsed = get_parser(agent_id).parse(agent_id, pane_text)
                            if parsed.get("last_error"):
                                error_text = parsed["last_error"]
                    except Exception as _e:
                        import sys as _sys
                        print(f'Ignored exception: {_e}', file=_sys.stderr)

                    if error_text:
                        last_err_line = error_text.splitlines()[-1] if error_text.splitlines() else error_text
                        msg = f"❌ У пейні {agent_id} виявлено помилку під час виконання `{task_id}`:\n`{last_err_line}`"
                    else:
                        elapsed = int(now - created_ts)
                        msg = f"⏳ Задача `{task_id}` {status_text} (агент `{agent_id}`). Працює вже {elapsed} сек."

                    self._send_text(chat_id, msg)
                    if isinstance(item, dict):
                        item["last_notified_at"] = now
