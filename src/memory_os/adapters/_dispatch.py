"""Agent dispatch for the Telegram polling daemon.

Owns sending a prompt to a swarm agent (direct delivery or formal SWARM
task protocol), watching it via AgentStateMonitor, and cascading to the
next candidate agent on rate-limit / stuck / delegate outcomes.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time

logger = logging.getLogger(__name__)


def _local_now_iso() -> str:
    from datetime import datetime
    from memory_os.core.config import MemoryOSConfig
    from memory_os.toolkit.agent_comm import _user_timezone
    try:
        return datetime.now(_user_timezone(MemoryOSConfig())).isoformat(timespec="seconds")
    except Exception:
        return datetime.now().astimezone().isoformat(timespec="seconds")


class _DispatchMixin:
    def _done_signal_rate_limited(self, done: dict) -> bool:
        """Return True if agent's STATUS_REPORT message reports rate-limit exhaustion.

        Agents self-report quota exhaustion in their STATUS_REPORT message.
        This is reliable unlike pane scanning — the pane always contains our own
        discussion of rate limits, causing false positives.
        """
        from memory_os.toolkit.agent_health import _RATE_LIMIT_KEYWORDS
        msg = (done.get("message") or "").lower()
        return any(kw in msg for kw in _RATE_LIMIT_KEYWORDS)

    def _dispatch(self, chat_id, prompt: str, agent: str | None = None, direct: bool = False) -> None:
        """Unified dispatch. All work runs in a background thread.

        direct=True: plain Telegram delivery — no SWARM task, no kernel, no [SWARM MESSAGE] wrapper.
          Used for conversational messages, KNOWN_AGENTS, natural text, /btw passthrough.
        direct=False: formal SWARM task protocol — kernel + AgentComm.send(TASK_ASSIGN).
          Used only for explicit /swarm invocations.

        Both modes: done-signal mechanism for reply tracking, cascade failover on timeout.
        Pane scanning is intentionally absent — panes contain our own
        discussion of rate limits which poisons keyword searches.
        Deduplication: identical (agent, prompt) combos within 60s are suppressed.
        """
        candidates = [agent] if (agent and agent != "auto") else self._ordered_cli_agents()
        dedup_key = self._dispatch_dedup_key(candidates[0], prompt)
        if self._duplicate_dispatch_pending(dedup_key):
            logger.info(f"[telegram] dedup: suppressed duplicate dispatch key={dedup_key}")
            return
        threading.Thread(
            target=lambda: self._run_dispatch(chat_id, prompt, candidates, dedup_key, direct),
            daemon=True,
        ).start()

    def _dispatch_dedup_key(self, agent_id: str, prompt: str) -> str:
        return f"{agent_id}:{hashlib.sha256(prompt.encode()).hexdigest()[:16]}"

    def _duplicate_dispatch_pending(self, dedup_key: str) -> bool:
        now_ts = time.time()
        return any(
            isinstance(item, dict)
            and item.get("dedup_key") == dedup_key
            and now_ts - item.get("ts", 0) < 60
            for item in self._swarm_pending_tasks.values()
        )

    def _run_dispatch(self, chat_id, prompt: str, candidates: list[str], dedup_key: str, direct: bool) -> None:
        from memory_os.toolkit.agent_comm import AgentComm
        from memory_os.toolkit.loop_kernel import LoopKernel
        from memory_os.toolkit.worktree import AgentWorktreeManager

        comm = AgentComm(self._root, config=self.config)
        kernel = None if direct else self._task_kernel()
        loop_kernel = LoopKernel(self._root)
        wt_manager = AgentWorktreeManager(self._root)
        task_id = self._create_dispatch_task(kernel, prompt, direct)

        for index, agent_id in enumerate(candidates):
            outcome = self._run_agent_attempt(
                chat_id=chat_id,
                prompt=prompt,
                candidates=candidates,
                index=index,
                agent_id=agent_id,
                task_id=task_id,
                dedup_key=dedup_key,
                direct=direct,
                comm=comm,
                kernel=kernel,
                loop_kernel=loop_kernel,
                wt_manager=wt_manager,
            )
            if outcome in {"complete", "pending"}:
                return
            if outcome == "abort":
                break

        self._send_text(chat_id, "Всі агенти не відповіли. Спробуйте пізніше.")
        self._relayed_done_tasks.add(task_id)

    def _create_dispatch_task(self, kernel, prompt: str, direct: bool) -> str:
        if direct:
            import uuid
            return f"task_{uuid.uuid4().hex[:8]}"
        task = kernel.create(
            title=f"telegram: {prompt[:80]}",
            goal=prompt,
            risk="medium",
            capabilities=["swarm.dispatch"],
            done_criteria="Agent sends STATUS_REPORT via memory_os comm send.",
        )
        return task["id"]

    def _run_agent_attempt(
        self, *, chat_id, prompt: str, candidates: list[str], index: int,
        agent_id: str, task_id: str, dedup_key: str, direct: bool,
        comm, kernel, loop_kernel, wt_manager,
    ) -> str:
        tmux_target = comm.resolve_delivery_target(agent_id)
        wt_path = None
        baseline = None
        keep_worktree = False
        if not direct:
            wt_path = wt_manager.create_worktree(agent_id, task_id)
            baseline = wt_manager.get_baseline_commit() if wt_path else None

        try:
            try:
                attempt = loop_kernel.start_attempt(task_id, agent_id, runtime=comm.transport.name)
            except RuntimeError as exc:
                logger.warning(f"[telegram] loop attempt start failed for task={task_id}: {exc}")
                self._send_text(chat_id, "⚠️ Спробу ретрансляції зупинено (ліміт спроб вичерпано).")
                return "abort"
            attempt_id = attempt["attempt_id"]

            if not self._deliver_dispatch_attempt(
                chat_id=chat_id,
                prompt=prompt,
                agent_id=agent_id,
                task_id=task_id,
                attempt_id=attempt_id,
                direct=direct,
                worktree_path=wt_path,
                comm=comm,
                kernel=kernel,
                loop_kernel=loop_kernel,
            ):
                return "next"

            self._track_pending_dispatch(
                chat_id, prompt, task_id, dedup_key, agent_id,
                attempt_id, wt_path, baseline, direct,
            )
            state, meta = self._watch_dispatch_attempt(
                agent_id, task_id, tmux_target, comm.transport,
            )
            outcome, keep_worktree = self._handle_dispatch_state(
                state=state,
                meta=meta,
                chat_id=chat_id,
                candidates=candidates,
                index=index,
                agent_id=agent_id,
                task_id=task_id,
                attempt_id=attempt_id,
                direct=direct,
                worktree_path=wt_path,
                baseline=baseline,
                kernel=kernel,
                loop_kernel=loop_kernel,
                wt_manager=wt_manager,
            )
            return outcome
        finally:
            if wt_path and not keep_worktree:
                wt_manager.remove_worktree(wt_path)

    def _deliver_dispatch_attempt(
        self, *, chat_id, prompt: str, agent_id: str, task_id: str,
        attempt_id: str, direct: bool, worktree_path, comm, kernel, loop_kernel,
    ) -> bool:
        if direct:
            message = (
                "[SYSTEM: Autonomous reply mode. Do NOT ask user. ALWAYS use memory_os search/comm/write tools and answer directly. Reply in the same language as the user's request.]\n"
                f"[TG_DELIVERY task={task_id} ts={_local_now_iso()}]: {prompt}\n\n"
                f"Reply: memory_os comm send --kind STATUS_REPORT --sender {agent_id} "
                f"--task-id {task_id} telegram \"<reply in the same language as the request>\""
            )
            result = comm.send_direct(
                recipient=agent_id,
                message=message,
                sender="telegram",
                task_id=task_id,
                worktree_path=worktree_path,
            )
            if result.ok:
                return True
            loop_kernel.record_verifier(
                task_id, attempt_id, verifier="telegram_polling", verdict="fail",
                feedback=f"direct send failed: {result.error}",
            )
            logger.warning(f"[telegram] direct send to {agent_id} failed: {result.error}")
            return False

        kernel.claim(task_id, agent=agent_id, lease_minutes=30)
        kernel.start(task_id)
        from memory_os.toolkit.quantizer import effort_directive
        delivery = (
            "[SYSTEM: Autonomous execution. Do NOT ask user. ALWAYS use memory_os search/comm/write tools directly. Run tests. Report done via comm send STATUS_REPORT.]\n"
            f"[TELEGRAM task={task_id} ts={_local_now_iso()}]\n"
            f"{effort_directive(prompt)}\n"
            f"{prompt}\n\n"
            f"Reply: memory_os comm send --kind STATUS_REPORT --sender {agent_id} "
            f"--task-id {task_id} telegram \"<reply in the same language as the request>\""
        )
        result = comm.send(
            recipient=agent_id,
            message=delivery,
            kind="TASK_ASSIGN",
            sender="telegram",
            task_id=task_id,
            worktree_path=worktree_path,
        )
        if result.ok:
            return True
        kernel.block(task_id, reason=f"dispatch failed: {result.error}")
        loop_kernel.record_verifier(
            task_id, attempt_id, verifier="telegram_polling", verdict="fail",
            feedback=f"dispatch failed: {result.error}",
        )
        logger.warning(f"[telegram] dispatch to {agent_id} failed: {result.error}")
        return False

    def _track_pending_dispatch(
        self, chat_id, prompt: str, task_id: str, dedup_key: str,
        agent_id: str, attempt_id: str, worktree_path, baseline, direct: bool,
    ) -> None:
        logger.info(f"[telegram] task={task_id} dispatched to {agent_id} direct={direct}")
        self._swarm_pending_tasks[task_id] = {
            "chat_id": chat_id,
            "prompt": prompt,
            "ts": time.time(),
            "dedup_key": dedup_key,
            "agent_id": agent_id,
            "attempt_id": attempt_id,
            "worktree_path": str(worktree_path) if worktree_path else None,
            "baseline_commit": baseline,
            "last_notified_at": time.time(),
        }
        self._last_active_agent[chat_id] = agent_id
        self._save_session_state()

    def _watch_dispatch_attempt(self, agent_id: str, task_id: str, target: str, transport):
        from memory_os.toolkit.agent_state_monitor import AgentStateMonitor

        monitor = AgentStateMonitor(
            root=self._root,
            agent_id=agent_id,
            task_id=task_id,
            tmux_target=target,
            poll_interval=2.0,
            stuck_sec=90.0,
            max_wait=600.0,
            transport=transport,
        )
        monitor.capture_baseline()
        self._actively_monitored.add(task_id)
        try:
            return monitor.watch()
        finally:
            self._actively_monitored.discard(task_id)

    def _handle_dispatch_state(
        self, *, state: str, meta: dict, chat_id, candidates: list[str], index: int,
        agent_id: str, task_id: str, attempt_id: str, direct: bool,
        worktree_path, baseline, kernel, loop_kernel, wt_manager,
    ) -> tuple[str, bool]:
        from memory_os.toolkit.agent_state_monitor import DONE, STUCK, RATE_LIMITED, DELEGATE

        if state == DONE:
            loop_kernel.record_verifier(
                task_id, attempt_id, verifier="telegram_polling", verdict="pass",
                feedback="STATUS_REPORT received cleanly",
            )
            keep_worktree = False
            if not direct and worktree_path and baseline:
                wt_manager.apply_changes_and_remove(worktree_path, baseline)
                keep_worktree = True
            if task_id not in self._relayed_done_tasks:
                message = meta.get("message", "")
                if message:
                    self._send_text(chat_id, message)
                self._relayed_done_tasks.add(task_id)
            return "complete", keep_worktree

        if state == RATE_LIMITED:
            keyword = meta.get("keyword", "?")
            if not direct:
                kernel.block(task_id, reason=f"rate_limited: {keyword}")
            loop_kernel.record_verifier(
                task_id, attempt_id, verifier="telegram_polling", verdict="fail",
                feedback=f"rate limited: {keyword}",
            )
            if loop_kernel.decision(task_id)["action"] == "stop":
                self._relayed_done_tasks.add(task_id)
                self._send_text(chat_id, f"⚠️ {agent_id} вичерпав ліміт. Спробу ретрансляції зупинено (retry budget exhausted).")
                return "complete", False
            next_agent = candidates[index + 1] if index + 1 < len(candidates) else None
            if next_agent:
                self._send_text(chat_id, f"⚠️ {agent_id} вичерпав ліміт — перенаправляю до {next_agent}...")
                return "next", False
            self._relayed_done_tasks.add(task_id)
            self._send_text(chat_id, f"⚠️ {agent_id} вичерпав ліміт. Інших агентів немає.")
            return "complete", False

        if state == DELEGATE:
            target = meta.get("target", "")
            if not direct:
                kernel.block(task_id, reason=f"agent delegated to {target}")
            loop_kernel.record_verifier(
                task_id, attempt_id, verifier="telegram_polling", verdict="fail",
                feedback=f"delegated to {target}",
            )
            if loop_kernel.decision(task_id)["action"] == "stop":
                self._relayed_done_tasks.add(task_id)
                self._send_text(chat_id, f"↩️ {agent_id} делегував. Спробу ретрансляції зупинено (retry budget exhausted).")
                return "complete", False
            next_agent = candidates[index + 1] if index + 1 < len(candidates) else None
            if next_agent:
                self._send_text(chat_id, f"↩️ {agent_id} делегує до {target or next_agent}...")
            return "next", False

        if state == STUCK:
            idle_sec = meta.get("idle_sec", 0)
            next_agent = candidates[index + 1] if index + 1 < len(candidates) else None
            if next_agent:
                loop_kernel.record_verifier(
                    task_id, attempt_id, verifier="telegram_polling", verdict="fail",
                    feedback=f"stuck after {idle_sec:.0f}s idle",
                )
                if loop_kernel.decision(task_id)["action"] == "stop":
                    self._relayed_done_tasks.add(task_id)
                    if not direct:
                        kernel.block(task_id, reason=f"stuck: {idle_sec:.0f}s idle")
                    self._send_text(chat_id, f"⏰ {agent_id} зупинився. Спробу ретрансляції зупинено (retry budget exhausted).")
                    return "complete", False
                if not direct:
                    kernel.block(task_id, reason=f"stuck: {idle_sec:.0f}s idle")
                logger.warning(f"[telegram] {agent_id} stuck, trying {next_agent}")
                self._send_text(chat_id, f"⏳ {agent_id} зупинився — перемикаю на {next_agent}...")
                return "next", False
            logger.info(f"[telegram] {agent_id} stuck ({idle_sec:.0f}s idle), leaving pending")
            return "pending", True

        return "next", False

    def _relay_status_report(self, chat_id, task_id: str) -> None:
        from memory_os.toolkit.workspace import watch_task

        if self.swarm_watch_timeout <= 0:
            return
        result = watch_task(
            task_id=task_id,
            root=self._root,
            timeout=self.swarm_watch_timeout,
            poll_interval=0.5,
            relay=False,
        )
        if result.get("timed_out"):
            return
        message = result.get("message", "")
        if message:
            self._send_text(chat_id, message)
