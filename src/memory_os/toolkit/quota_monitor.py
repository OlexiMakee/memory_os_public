import os
import time
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.agent_health import AgentHealthProbe
from memory_os.toolkit.agent_registry import load_agent_registry
from memory_os.toolkit.multiplexer_manager import MultiplexerManager
from memory_os.toolkit.agent_comm import AgentComm
from memory_os.toolkit.quota_store import QuotaStore
from memory_os.toolkit.quota_time_parser import parse_reset_timestamp
from memory_os.adapters.telegram_adapter import TelegramAdapter

logger = logging.getLogger(__name__)

class AgentQuotaMonitor:
    def __init__(self, root: Path):
        self.root = root
        self.config = MemoryOSConfig(str(root / "memory_os.config.json"))
        self.probe = AgentHealthProbe(root)
        self.store = QuotaStore(self.root)
        self._load_state()

    def _load_state(self) -> None:
        self.state = self.store.load()

    def _save_state(self) -> None:
        self.store.save(self.state)

    def notify_telegram(self, text: str) -> None:
        import os
        chat_ids_raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
        chat_ids = [cid.strip() for cid in chat_ids_raw.split(",") if cid.strip()]
        if not chat_ids:
            logger.warning("[quota_monitor] No TELEGRAM_ALLOWED_CHAT_IDS configured, skipping notification.")
            return
        
        adapter = TelegramAdapter()
        for chat_id in chat_ids:
            try:
                adapter.send_message(chat_id, text)
            except Exception as e:
                logger.error(f"[quota_monitor] Failed to notify chat_id {chat_id}: {e}")

    def _last_agent_report_ts(self, agent_id: str, tail_lines: int = 400) -> Optional[float]:
        """Epoch of the newest STATUS_REPORT the agent itself sent, from task_events.jsonl."""
        events_path = self.root / "agent_context" / "task_events.jsonl"
        if not events_path.exists():
            return None
        try:
            lines = events_path.read_text(encoding="utf-8").splitlines()[-tail_lines:]
        except Exception:
            return None
        latest: Optional[float] = None
        for line in lines:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("event") != "comm.sent" or ev.get("kind") != "STATUS_REPORT":
                continue
            if ev.get("sender") != agent_id:
                continue
            ts_raw = str(ev.get("ts", ""))
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            if latest is None or ts > latest:
                latest = ts
        return latest

    def parse_reset_time(self, text: str) -> Optional[float]:
        return parse_reset_timestamp(text, now=datetime.now(timezone.utc))

    def check_and_recover(self) -> None:
        """Runs a check on all agents and attempts recovery if rate limits reset."""
        self._load_state()
        now = time.time()
        registry = load_agent_registry(self.root).get("agent", {})
        
        for agent_id, cfg in registry.items():
            kind = cfg.get("kind", "")
            if kind != "cli_agent":
                continue
            display_name = str(cfg.get("display_name") or agent_id.capitalize())
                
            mgr = MultiplexerManager(self.root)
            target_pane = mgr.resolve_pane_target(agent_id)
            is_active_terminal = (agent_id == "agy" or target_pane == os.environ.get("TMUX_PANE"))
            
            # Check current health status
            health = self.probe.check(agent_id, cfg=cfg, force=True)
            status = health.get("status")
            self._load_state()
            current_state = self.state.get(agent_id, {})
            if current_state.get("has_limit") is False and "reset_at" in current_state:
                current_state.pop("reset_at", None)
                self._save_state()
            if (
                current_state.get("usage_source") == "app_server"
                and current_state.get("has_limit") is False
            ):
                status = "ok"
            
            # 1. If currently rate limited / quota exhausted
            if status in ("quota_exhausted", "rate_limited"):
                # Retrieve reset time from pane if not tracked yet
                if is_active_terminal:
                    reset_at = None
                else:
                    mgr = MultiplexerManager(self.root)
                    pane_output = mgr.capture_pane(target_pane, lines=100, full_history=True)
                    reset_at = self.parse_reset_time(pane_output)
                
                agent_state = self.state.setdefault(agent_id, {})
                
                # Update resets info
                if reset_at:
                    agent_state["reset_at"] = reset_at
                    agent_state["has_limit"] = True
                    logger.info(f"[quota_monitor] {agent_id} rate limited. Resets at {datetime.fromtimestamp(reset_at, timezone.utc).isoformat()}")
                else:
                    agent_state.setdefault("reset_at", now + 600)  # Default 10 min fallback
                    agent_state["has_limit"] = True
                
                # Notify once per limit window. Model selection is an explicit user action.
                if agent_id in ("codex", "agy") and not agent_state.get("attempted_switch", False):
                    agent_state["attempted_switch"] = True
                    self._save_state()
                    self.notify_telegram(
                        f"⚠️ Агент {agent_id} вичерпав ліміти. Перемкніть модель вручну або скористайтеся іншим провайдером."
                    )
                
                self._save_state()
                
            # 2. If tracked as limited but now we should verify or if time arrived
            agent_state = self.state.get(agent_id, {})
            if agent_state.get("has_limit"):
                # Liveness short-circuit: an agent that sent a STATUS_REPORT after the
                # limit was seen is demonstrably working — no ping needed, clear + notify.
                last_report = self._last_agent_report_ts(agent_id)
                limit_seen = agent_state.get("limit_seen_at") or agent_state.get("reset_at", 0)
                if last_report and last_report > limit_seen:
                    logger.info(f"[quota_monitor] {agent_id} sent STATUS_REPORT after limit — recovered.")
                    agent_state["has_limit"] = False
                    agent_state["attempted_switch"] = False
                    agent_state.pop("task_id", None)
                    agent_state.pop("reset_at", None)
                    # Notify once per limit episode: the harvester may flip has_limit
                    # back on from a lagging usage snapshot on the very next tick.
                    already_notified = agent_state.get("restored_notified_at", 0) >= limit_seen
                    agent_state["restored_notified_at"] = now
                    self._save_state()
                    if not already_notified:
                        self.notify_telegram(f"✅ Ліміти {display_name} відновлено")
                    continue
                reset_at = agent_state.get("reset_at", 0)
                
                # If reset time reached, send test task
                if now >= reset_at:
                    if is_active_terminal:
                        # Skip automated task verification on the active developer pane
                        pass
                    else:
                        # Clean console screen first so probe won't read stale error output
                        mgr.send_shortcut(target_pane, "clear")
                    time.sleep(0.5)

                    # Create probe task
                    test_task_id = f"task_quota_test_{agent_id}_{int(now)}"
                    agent_state["task_id"] = test_task_id
                    agent_state["reset_at"] = now + 90  # check again in 90 seconds
                    self._save_state()

                    comm = AgentComm(self.root)
                    logger.info(f"[quota_monitor] Sending test probe {test_task_id} to {agent_id}...")
                    # Minimal-cost ping: the agent should burn as close to 1 output token as possible
                    comm.send(
                        recipient=agent_id,
                        sender="system",
                        kind="TASK_ASSIGN",
                        task_id=test_task_id,
                        message=(
                            "[QUOTA PING] Run exactly this command and output NOTHING else "
                            "(no analysis, no summary): memory_os comm send system ok "
                            f"--kind STATUS_REPORT --task-id {test_task_id} --sender {agent_id}"
                        ),
                    )
                else:
                    # There is a pending test task. Let's see if it finished.
                    if "task_id" in agent_state:
                        test_task_id = agent_state["task_id"]
                        done_file = self.root / "agent_context" / "done" / f"{test_task_id}.json"
                        
                        if done_file.exists():
                            # YES! Succeeded
                            logger.info(f"[quota_monitor] Probe {test_task_id} succeeded. {agent_id} is recovered.")
                            agent_state["has_limit"] = False
                            agent_state["attempted_switch"] = False
                            del agent_state["task_id"]
                            agent_state.pop("reset_at", None)
                            self._save_state()
                            
                            # Clear old error messages from pane buffer
                            MultiplexerManager(self.root).send_shortcut(target_pane, "clear")
                            time.sleep(0.5)
                            
                            # Set health cache to ok
                            probe_cache = self.probe._load_cache()
                            if agent_id in probe_cache:
                                probe_cache[agent_id]["status"] = "ok"
                                probe_cache[agent_id]["detail"] = "Available"
                                probe_cache[agent_id]["ts"] = now
                                self.probe._save_cache(probe_cache)
                                
                            # Send Telegram notification
                            self.notify_telegram(f"✅ Ліміти {display_name} відновлено")
                            
                            # Clean done file
                            try:
                                done_file.unlink()
                            except Exception as _e:
                                import sys as _sys
                                print(f'Ignored exception: {_e}', file=_sys.stderr)
                        else:
                            # Test task is not done yet. Check if it timed out.
                            try:
                                ts_part = int(test_task_id.split("_")[-1])
                                if now - ts_part > 60:  # Timeout after 60 seconds
                                    logger.info(f"[quota_monitor] Probe {test_task_id} timed out. Agent {agent_id} still rate limited.")
                                    # Update health cache to keep it rate limited
                                    pane_output = MultiplexerManager(self.root).capture_pane(target_pane, lines=30)
                                    new_reset = self.parse_reset_time(pane_output)
                                    agent_state["reset_at"] = new_reset if new_reset else (now + 300)
                                    del agent_state["task_id"]
                                    self._save_state()
                            except Exception:
                                del agent_state["task_id"]
                                self._save_state()
