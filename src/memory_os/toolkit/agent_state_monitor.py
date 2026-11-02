"""Adaptive agent state monitor via tmux pane polling.

Replaces fixed-timeout failover with state-aware polling:
  DONE         — STATUS_REPORT arrived (done-signal file exists)
  ACTIVE       — pane content changed since last poll (agent working)
  STUCK        — no pane change for stuck_sec (agent silent / crashed)
  RATE_LIMITED — rate-limit keywords in delta content (new since baseline)
  DELEGATE     — agent signals delegation via pane output marker

Delta-based scanning avoids self-poisoning: baseline captures pane state at
dispatch time; only NEW lines (not in baseline) are checked for keywords.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from memory_os.toolkit.agent_transport import AgentTransport, FileInboxTransport

logger = logging.getLogger(__name__)

DONE = "done"
ACTIVE = "active"
STUCK = "stuck"
RATE_LIMITED = "rate_limited"
DELEGATE = "delegate"

_TERMINAL_STATES = {DONE, STUCK, RATE_LIMITED, DELEGATE}

_DELEGATE_RE = re.compile(
    r"\[DELEGATE(?:\s+to)?\s+([a-z][a-z0-9_-]+)\]"
    r"|swarm-send\s+.*?--agent\s+([a-z][a-z0-9_-]+)",
    re.IGNORECASE,
)


class AgentStateMonitor:
    """Poll tmux pane + done-signal to track a running agent task.

    Usage:
        monitor = AgentStateMonitor(root, agent_id, task_id, tmux_target)
        monitor.capture_baseline()   # immediately after dispatching the message
        state, meta = monitor.watch()
    """

    def __init__(
        self,
        root: Path,
        agent_id: str,
        task_id: str,
        tmux_target: str,
        poll_interval: float = 2.0,
        stuck_sec: float = 90.0,
        max_wait: float = 600.0,
        transport: Optional[AgentTransport] = None,
    ):
        self.root = root
        self.agent_id = agent_id
        self.task_id = task_id
        self.tmux_target = tmux_target
        self.poll_interval = poll_interval
        self.stuck_sec = stuck_sec
        self.max_wait = max_wait
        self.transport = transport or FileInboxTransport(root)

        self._baseline_lines: frozenset[str] = frozenset()
        self._last_content: str = ""
        self._last_change_ts: float = time.time()

    def capture_baseline(self) -> None:
        """Record pane state right after dispatch — delta checks compare against this."""
        content = self._capture_pane() or ""
        self._baseline_lines = frozenset(ln for ln in content.splitlines() if ln.strip())
        self._last_content = content
        self._last_change_ts = time.time()

    def watch(self) -> tuple[str, dict]:
        """Block-poll until terminal state or max_wait exceeded.

        Returns (state, meta). Terminal states: DONE, STUCK, RATE_LIMITED, DELEGATE.
        """
        deadline = time.time() + self.max_wait
        while time.time() < deadline:
            state, meta = self.poll_once()
            if state in _TERMINAL_STATES:
                return state, meta
            time.sleep(self.poll_interval)
        return STUCK, {"reason": "max_wait exceeded", "max_wait_sec": self.max_wait, "agent": self.agent_id}

    def poll_once(self) -> tuple[str, dict]:
        """Non-blocking single poll."""
        # Done-signal is authoritative — fast path
        done_file = self.root / "agent_context" / "done" / f"{self.task_id}.json"
        if done_file.exists():
            try:
                data = json.loads(done_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
            return DONE, data

        # Pane capture
        current = self._capture_pane()
        if current is None:
            # tmux unavailable — assume agent is working
            return ACTIVE, {"pane": "unavailable"}

        # Delta: non-empty lines not present at dispatch baseline
        new_lines = [ln for ln in current.splitlines() if ln.strip() and ln not in self._baseline_lines]
        new_content_lower = "\n".join(new_lines).lower()

        # Delta-only detection avoids self-poisoning from task text that merely
        # discusses rate limits.
        if new_content_lower:
            from memory_os.toolkit.console_parser import get_parser
            parser = get_parser(self.agent_id)
            limit_event = parser.extract_limit_event("\n".join(new_lines), strict=True)
            if limit_event:
                keyword = str(limit_event.get("keyword", "limit"))
                logger.debug(f"[monitor] {self.agent_id}/{self.task_id} rate_limited: keyword={keyword!r}")
                try:
                    from memory_os.toolkit.quota_harvester import record_limit_mention
                    record_limit_mention(self.root, self.agent_id, str(limit_event.get("line", "")))
                except Exception as _e:
                    import sys as _sys
                    print(f'Ignored exception: {_e}', file=_sys.stderr)
                return RATE_LIMITED, {"keyword": keyword, "agent": self.agent_id}

        # Delegation signal in delta
        m = _DELEGATE_RE.search("\n".join(new_lines))
        if m:
            target = m.group(1) or m.group(2)
            logger.debug(f"[monitor] {self.agent_id}/{self.task_id} delegate→{target}")
            return DELEGATE, {"target": target, "from": self.agent_id}

        # Activity: did pane change since last poll?
        if current != self._last_content:
            self._last_change_ts = time.time()
            self._last_content = current
            return ACTIVE, {}

        # Stuck: no change for stuck_sec
        idle_sec = time.time() - self._last_change_ts
        if idle_sec >= self.stuck_sec:
            logger.debug(f"[monitor] {self.agent_id}/{self.task_id} stuck idle={idle_sec:.0f}s")
            return STUCK, {"stuck_sec": self.stuck_sec, "idle_sec": idle_sec, "agent": self.agent_id}

        return ACTIVE, {}

    def _capture_pane(self) -> Optional[str]:
        return self.transport.capture_text(self.tmux_target, lines=150, full_history=True)
