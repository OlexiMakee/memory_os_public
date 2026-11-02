"""Telegram long-polling daemon loop.

Wires TelegramAdapter → Task Kernel → ActionBrain → Executor → LocalLLMResponder → send_message.

Usage:
    TELEGRAM_BOT_TOKEN=... memory_os telegram-daemon --poll-interval 2

The loop:
1. GET updates from Telegram (long-polling)
2. For each message:
   a. Create a task in the Task Kernel (track message lifecycle)
   b. Run Orchestrator to determine action + execute
   c. Feed ActionResult into LocalLLMResponder to generate natural-language reply
   d. Send reply back to the chat
   e. Mark task done/blocked in the kernel

Both action and responder use the local llama_cpp provider with their respective
LoRA adapters (LLAMA_CPP_LORA and LLAMA_CPP_LORA_RESPONDER from env).

Behavior is split across mixins by concern:
- _routing.py: command parsing + routing incoming updates (_RoutingMixin)
- _dispatch.py: sending prompts to swarm agents and watching them (_DispatchMixin)
- _relay.py: relaying done-signals/inbox messages, core daemon watchdog (_RelayMixin)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from memory_os.adapters._dispatch import _DispatchMixin
from memory_os.adapters._relay import _RelayMixin
from memory_os.adapters._routing import _RoutingMixin
from memory_os.toolkit.agent_registry import KNOWN_AGENTS

logger = logging.getLogger(__name__)

_RATE_LIMIT_SEC = 0.5   # minimum seconds between send_message calls per chat
_FAILOVER_WAIT_SEC = 15  # wait for done signal before checking pane for rate limit


class TelegramPollingDaemon(_RoutingMixin, _DispatchMixin, _RelayMixin):
    def __init__(
        self,
        config,
        system_prompt: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        track_tasks: bool = True,
        swarm_control: bool = False,
        swarm_watch_timeout: float = 10.0,
    ):
        from memory_os.adapters.telegram_adapter import TelegramAdapter
        from memory_os.agent_brain.brain import LocalLLMActionBrain
        from memory_os.agent_brain.executors import default_executors
        from memory_os.agent_brain.orchestrator import Orchestrator
        from memory_os.agent_brain.responder import LocalLLMResponder
        from memory_os.lora.dataset import UK_RESPONDER_SYSTEM_PROMPT

        self.config = config
        self._root = Path(config.root_dir)
        self.telegram = TelegramAdapter()
        brain = LocalLLMActionBrain(provider=provider, model=model)
        self.orchestrator = Orchestrator(brain=brain, executors=default_executors(config))
        self.responder = LocalLLMResponder(
            system_prompt=system_prompt or UK_RESPONDER_SYSTEM_PROMPT,
            provider=provider,
            model=model,
        )
        self.track_tasks = track_tasks
        self.swarm_control = swarm_control
        self.swarm_watch_timeout = swarm_watch_timeout
        self._offset: int = 0
        self._last_send: dict = {}   # chat_id → last send timestamp
        self._swarm_pending_tasks: dict = {}  # task_id -> chat_id
        self._relayed_done_tasks: set = set()
        self._actively_monitored: set = set()  # task_ids currently watched by AgentStateMonitor
        self.session_file = self._root / "agent_context" / "telegram_session.json"
        self._session_agent: dict = {}  # chat_id -> agent_id ("auto", *KNOWN_AGENTS)
        self._last_active_agent: dict = {}  # chat_id -> last actual recipient agent
        self._chat_notes: dict = {}  # chat_id -> list of note strings
        self._load_session_state()

    def _load_session_state(self) -> None:
        if self.session_file.exists():
            try:
                data = json.loads(self.session_file.read_text(encoding="utf-8"))
                self._session_agent = {int(k) if k.isdigit() else k: v for k, v in data.get("session_agent", {}).items()}
                self._last_active_agent = {int(k) if k.isdigit() else k: v for k, v in data.get("last_active_agent", {}).items()}
            except Exception as exc:
                logger.warning(f"[telegram] failed to load session file: {exc}")

        # Fallback event log recovery if empty
        if not self._last_active_agent:
            recovered = self._recover_last_agent_from_log()
            if recovered != "auto":
                for cid in self._allowed_chat_ids():
                    chat_id = int(cid) if cid.isdigit() else cid
                    self._last_active_agent[chat_id] = recovered

    def _recover_last_agent_from_log(self) -> str:
        log_path = self._root / "agent_context" / "task_events.jsonl"
        if not log_path.exists():
            return "auto"
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-50:]
            for line in reversed(lines):
                if not line.strip():
                    continue
                evt = json.loads(line)
                if evt.get("event") == "comm.sent" and evt.get("recipient") == "telegram":
                    sender = evt.get("sender")
                    if sender in KNOWN_AGENTS:
                        return sender
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)
        return "auto"

    def _save_session_state(self) -> None:
        try:
            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "session_agent": {str(k): v for k, v in self._session_agent.items()},
                "last_active_agent": {str(k): v for k, v in self._last_active_agent.items()},
            }
            self.session_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception as exc:
            logger.warning(f"[telegram] failed to save session file: {exc}")

    def _subject_ref(self, kind: str, value) -> str:
        salt = getattr(self.config, "workspace_id", str(getattr(self.config, "root_dir", "")))
        payload = f"{salt}:{kind}:{value}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]

    def _task_kernel(self):
        from memory_os.toolkit.task_kernel import TaskKernel
        return TaskKernel(self._root)

    def _rate_limit(self, chat_id) -> None:
        now = time.monotonic()
        last = self._last_send.get(chat_id, 0)
        wait = _RATE_LIMIT_SEC - (now - last)
        if wait > 0:
            time.sleep(wait)
        self._last_send[chat_id] = time.monotonic()

    def _send_text(self, chat_id, text: str) -> bool:
        self._rate_limit(chat_id)
        logger.info(f"[telegram] OUTGOING chat={chat_id}: {text[:100]!r}")
        result = self.telegram.send_message(chat_id, text)
        ok = bool(result.get("ok", False))
        if not ok:
            logger.warning(f"[telegram] send_message failed chat={chat_id}: {result.get('detail', result)}")
        return ok

    def _append_task_event(self, payload: dict) -> None:
        events_path = self._root / "agent_context" / "task_events.jsonl"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        payload.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        with events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _allowed_chat_ids(self) -> set[str]:
        raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
        return {part.strip() for part in raw.split(",") if part.strip()}

    def _chat_authorized(self, chat_id) -> bool:
        allowed = self._allowed_chat_ids()
        return bool(allowed) and str(chat_id) in allowed

    def run(
        self,
        poll_interval: float = 2.0,
        once: bool = False,
        max_retries: int = 5,
        retry_backoff: float = 5.0,
        should_stop=None,
    ) -> None:
        """Main polling loop. Set once=True to process one batch and exit.

        should_stop: optional zero-arg callable checked every cycle — the CLI
        signal handler only flips a flag, so without this hook Ctrl+C/SIGTERM
        never actually leaves the loop."""
        logger.info("[telegram] starting polling loop")
        done_dir = self._root / "agent_context" / "done"
        if done_dir.exists():
            for df in done_dir.glob("*.json"):
                self._relayed_done_tasks.add(df.stem)

        consecutive_errors = 0

        while not (should_stop and should_stop()):
            updates = []
            try:
                result = self.telegram.get_updates(offset=self._offset, limit=100)
                updates = result.get("updates", [])
                consecutive_errors = 0
            except Exception as exc:
                logger.error(f"[telegram] get_updates failed: {exc}")
                consecutive_errors += 1
                if consecutive_errors >= max_retries:
                    logger.error(f"[telegram] {max_retries} consecutive errors, stopping")
                    break
                if not once:
                    time.sleep(retry_backoff * consecutive_errors)

            for upd in updates:
                update_id = upd.get("update_id", 0)
                try:
                    self.process_update(upd)
                except Exception as exc:
                    logger.error(f"[telegram] unhandled error in process_update: {exc}")
                self._offset = max(self._offset, update_id + 1)

            self._check_and_relay_done_tasks()
            self._relay_telegram_inbox()
            self._watch_core_daemon()

            if once:
                break
            if not updates and not (should_stop and should_stop()):
                time.sleep(poll_interval)
