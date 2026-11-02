"""Agent communication toolkit for file-backed inter-agent messages.

The payload is file-backed in agent_context/inbox/<agent>.jsonl so the actual
message can be read without depending on an interactive terminal. Optional
transports, such as tmux, only provide wake-up and live-console delivery.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from memory_os.core.config import MemoryOSConfig
from memory_os.core.repository import MemoryRepository
from memory_os.core.safe_id import validate_safe_id, validate_safe_node_id
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.core.models import MemoryNode
from memory_os.core.timecode import now_local_iso
from memory_os.toolkit.agent_limits import agent_limit_active, format_agent_limit_summary
from memory_os.toolkit.agent_comm_store import AgentCommStore, utc_now_iso
from memory_os.toolkit.agent_registry import load_agent_registry

from memory_os.toolkit.agent_transport import (
    AgentTransport,
    FileInboxTransport,
    MultiplexerAgentTransport,
)

_VALID_MESSAGE_KINDS = {"TASK_ASSIGN", "STATUS_REPORT", "DIRECT"}


def _now_iso() -> str:
    return utc_now_iso()


def _user_timezone(config: MemoryOSConfig) -> timezone:
    tz_name = (
        os.environ.get("MEMORY_OS_USER_TZ")
        or config.data.get("user_timezone")
        or config.data.get("timezone")
        or ""
    ).strip()
    if tz_name:
        try:
            return ZoneInfo(tz_name)  # type: ignore[return-value]
        except ZoneInfoNotFoundError:
            pass
    return datetime.now().astimezone().tzinfo or timezone.utc


def _coerce_timezone(value: str) -> timezone:
    if value:
        try:
            return ZoneInfo(value)  # type: ignore[return-value]
        except ZoneInfoNotFoundError:
            if value.upper() == "UTC":
                return timezone.utc
    return datetime.now().astimezone().tzinfo or timezone.utc


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _format_user_time(value: str, user_tz: timezone) -> str:
    parsed = _parse_iso(value)
    if parsed is None:
        return value
    return parsed.astimezone(user_tz).strftime("%Y-%m-%d %H:%M:%S %Z")


def _format_user_timestamp(ts: Any, user_tz: timezone) -> str:
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).astimezone(user_tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    except (TypeError, ValueError, OSError):
        return ""


def _short_text(text: str, limit: int = 120) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)] + "…"


def _normalized_text(text: str) -> str:
    return " ".join((text or "").split())


def _relative_time(ts_value: str, now: Optional[datetime] = None) -> str:
    """Compact '5m ago' / '2h 14m ago' / '3d ago' — deterministic deltas so
    LLM readers never have to compute timeline arithmetic themselves."""
    parsed = _parse_iso(str(ts_value or ""))
    if parsed is None:
        return ""
    delta = (now or datetime.now(timezone.utc)) - parsed
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "in future"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h {minutes % 60}m ago"
    return f"{hours // 24}d ago"


@dataclass
class CommResult:
    ok: bool
    event_path: Optional[str]
    inbox_path: Optional[str]
    tmux_target: Optional[str]
    recipient: str
    sender: str
    kind: str
    message: str
    task_id: str
    error: Optional[str] = None
    sync_path: Optional[str] = None
    transport: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "event_path": self.event_path,
            "inbox_path": self.inbox_path,
            "tmux_target": self.tmux_target,
            "recipient": self.recipient,
            "sender": self.sender,
            "kind": self.kind,
            "message": self.message,
            "task_id": self.task_id,
            "error": self.error,
            "sync_path": self.sync_path,
            "transport": self.transport,
        }


class AgentComm:
    """File-backed agent communication with pluggable wake-up transports."""

    def __init__(
        self,
        root: Path,
        config: Optional[MemoryOSConfig] = None,
        transport: Optional[AgentTransport] = None,
    ):
        self.root = root
        self.config = config or MemoryOSConfig(str(root / "memory_os.config.json"))
        self.transport = transport or self._default_transport()
        self.store = AgentCommStore(root)
        self.events_path = self.store.events_path
        self.inbox_dir = self.store.inbox_dir
        self.done_dir = self.store.done_dir

    def _default_transport(self) -> AgentTransport:
        requested = os.environ.get("MEMORY_OS_AGENT_TRANSPORT", "auto").strip().lower()
        if requested == "file":
            return FileInboxTransport(self.root)
        if requested in ("tmux", "zellij", "multiplexer"):
            return MultiplexerAgentTransport(self.root)
        if self._multiplexer_available():
            return MultiplexerAgentTransport(self.root)
        return FileInboxTransport(self.root)

    # ------------------------------------------------------------------
    # Registry / target resolution
    # ------------------------------------------------------------------

    def _agent_config(self, agent_id: str) -> Dict[str, Any]:
        registry = load_agent_registry(self.root)
        return dict(registry.get("agent", {}).get(agent_id, {}))

    def _live_delivery_target(self, recipient: str, tmux_target: Optional[str] = None) -> Optional[str]:
        if recipient == "telegram":
            return None
        if tmux_target:
            return self._resolve_tmux_target(recipient, tmux_target=tmux_target)
        cfg = self._agent_config(recipient)
        kind = cfg.get("kind")
        if kind is not None:
            # Explicit registry entry: only cli_agent gets live delivery.
            if kind != "cli_agent":
                return None
        else:
            # No registry entry: deliver only to known core agents (in agent_panes).
            from memory_os.core.config import MemoryOSConfig
            core_agents = MemoryOSConfig(str(self.root / "memory_os.config.json")).agent_panes
            if recipient not in core_agents:
                return None
        return self._resolve_tmux_target(recipient)

    def _resolve_tmux_target(self, recipient: str, tmux_target: Optional[str] = None) -> str:
        from memory_os.toolkit.multiplexer_manager import MultiplexerManager
        return MultiplexerManager(self.root).resolve_pane_target(tmux_target or recipient)

    def resolve_delivery_target(self, recipient: str, target: Optional[str] = None) -> str:
        return self._resolve_tmux_target(recipient, tmux_target=target)

    def _multiplexer_available(self) -> bool:
        from memory_os.toolkit.multiplexer_manager import MultiplexerManager
        return MultiplexerManager.is_available()

    def _send_tmux_keys(self, target: str, message: str, unlock_buffers: bool = True) -> None:
        result = MultiplexerAgentTransport(self.root).send_text(
            target,
            message,
            submit=True,
            unlock_buffers=unlock_buffers,
        )
        if not result.ok:
            raise RuntimeError(result.error or "tmux transport failed")

    def _send_transport_text(self, target: str, message: str, unlock_buffers: bool = True) -> None:
        result = self.transport.send_text(
            target,
            message,
            submit=True,
            unlock_buffers=unlock_buffers,
        )
        if not result.ok:
            raise RuntimeError(result.error or f"{result.backend} transport failed")

    # ------------------------------------------------------------------
    # Event log + memory sync
    # ------------------------------------------------------------------

    def _append_event(self, record: Dict[str, Any]) -> Path:
        return self.store.append_event(record)

    def _inbox_path(self, recipient: str) -> Path:
        return self.store.inbox_path(recipient)

    def _append_inbox_payload(self, recipient: str, record: Dict[str, Any]) -> Path:
        return self.store.append_inbox_payload(recipient, record)

    # ------------------------------------------------------------------
    # Log rotation — event/inbox JSONL grow monotonically and are read in
    # full on every feed/inbox call; rotation keeps the hot tail small and
    # rebases the line-based read cursors so nothing is re-shown or lost.
    # ------------------------------------------------------------------

    def rotate_events(self, keep: int = 1000) -> Optional[Path]:
        return self.store.rotate_events(keep)

    def rotate_inbox(self, recipient: str, keep: int = 200) -> Optional[Path]:
        return self.store.rotate_inbox(recipient, keep)

    def _sync_memory(self, sender: str, recipient: str, kind: str, message: str, task_id: str) -> Optional[str]:
        repo = MemoryRepository(FileSystemMemoryStorage(), self.config)
        digest_input = f"{sender}\0{recipient}\0{kind}\0{task_id}\0{message}\0{time.time_ns()}".encode("utf-8")
        digest = hashlib.sha1(digest_input).hexdigest()[:10]
        event_id = f"{task_id}:{digest}"
        validate_safe_node_id(event_id, "comm node id")
        summary = f"{kind} from {sender} to {recipient} for {task_id}: {_short_text(message, 90)}"
        node = MemoryNode(
            id=f"comm:{event_id}",
            type="fact",
            summary=summary,
            evidence=[str(self.events_path.relative_to(self.root))],
            status="observed",
            freshness=now_local_iso(self.config),
            trust="extracted",
            domain="agent_comm",
            tags=["agent_comm", kind.lower(), sender, recipient],
        )
        repo.upsert_node(node)
        return str(self.config.memory_dir / "nodes.jsonl")

    def _write_done_signal(self, task_id: str, sender: str, message: str) -> Path:
        """Write agent_context/done/{task_id}.json when a STATUS_REPORT arrives.

        Idempotent — overwrites if called twice for the same task.
        """
        return self.store.write_done_signal(task_id, sender, message)

    def get_interactive_prompt(self, agent_id: str, tmux_target: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Checks if the target agent pane currently displays an interactive question/prompt."""
        target = self._resolve_tmux_target(agent_id, tmux_target=tmux_target)
        try:
            from memory_os.toolkit.multiplexer_manager import MultiplexerManager
            mgr = MultiplexerManager(self.root)
            output = mgr.capture_pane(target, lines=30, full_history=True)
            if output:
                from memory_os.toolkit.console_parser import get_parser
                parsed = get_parser(agent_id).parse(agent_id, output)
                if parsed.get("interactive_question") and parsed.get("suggested_answers"):
                    return {
                        "question": parsed["interactive_question"],
                        "suggested_answers": parsed["suggested_answers"],
                    }
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)
        return None

    def answer_interactive_prompt(self, agent_id: str, answer: str, tmux_target: Optional[str] = None) -> None:
        """Answers the interactive question in the agent's console pane."""
        target = self._resolve_tmux_target(agent_id, tmux_target=tmux_target)
        from memory_os.toolkit.multiplexer_manager import MultiplexerManager
        mgr = MultiplexerManager(self.root)
        mgr.send_keys(target, answer, submit=True, unlock_buffers=False)

    def auto_resolve_pending_prompt(self, agent_id: str, target: str) -> None:
        """Helper to automatically detect and auto-confirm y/n prompts on the target pane."""
        prompt_info = self.get_interactive_prompt(agent_id, tmux_target=target)
        if prompt_info:
            question = prompt_info["question"]
            answers = prompt_info["suggested_answers"]
            if "y" in answers:
                self._append_event({
                    "event": "comm.auto_resolve_prompt",
                    "agent_id": agent_id,
                    "question": question,
                    "answer": "y"
                })
                self.answer_interactive_prompt(agent_id, "y", tmux_target=target)
                time.sleep(0.5)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(
        self,
        recipient: str,
        message: str,
        kind: str,
        sender: str = "codex",
        task_id: str = "",
        tmux_target: Optional[str] = None,
        unlock_buffers: bool = True,
        worktree_path: Optional[Path] = None,
        auto_resolve_prompts: bool = True,
    ) -> CommResult:
        validate_safe_id(recipient, "recipient")
        validate_safe_id(sender, "sender")
        if kind not in _VALID_MESSAGE_KINDS:
            raise ValueError(f"kind must be one of {sorted(_VALID_MESSAGE_KINDS)}")
        if not task_id:
            raise ValueError("task_id is required")
        validate_safe_id(task_id, "task_id")
        normalized_message = _normalized_text(message)
        max_len = 2000
        if len(normalized_message) > max_len:
            raise ValueError(f"message for {kind} must be at most {max_len} characters after whitespace normalization")

        target = self._live_delivery_target(recipient, tmux_target=tmux_target)
        if target and auto_resolve_prompts and recipient != "telegram":
            self.auto_resolve_pending_prompt(recipient, target)
        inbox_path = self._append_inbox_payload(
            recipient,
            {
                "event": "comm.payload",
                "kind": kind,
                "sender": sender,
                "recipient": recipient,
                "message": normalized_message,
                "task_id": task_id,
            }
        )
        event_path = self._append_event(
            {
                "event": "comm.sent",
                "kind": kind,
                "sender": sender,
                "recipient": recipient,
                "tmux_target": target,
                "task_id": task_id,
                "message": _short_text(normalized_message, 120),
                "inbox_path": str(inbox_path.relative_to(self.root)),
            }
        )

        header_ts = datetime.now(_user_timezone(self.config)).isoformat(timespec="seconds")
        formatted_text = f"[SWARM MESSAGE kind={kind} task={task_id} sender={sender} ts={header_ts}]\n{normalized_message}\n[END SWARM MESSAGE]"
        try:
            if kind == "STATUS_REPORT":
                self._write_done_signal(task_id, sender, normalized_message)
                # closed task = fresh rollout data; refresh usage immediately
                if sender == "codex":
                    try:
                        from memory_os.toolkit.quota_harvester import refresh_quota_state
                        refresh_quota_state(self.root, ttl=0.0)
                    except Exception as _e:
                        import sys as _sys
                        print(f'Ignored exception: {_e}', file=_sys.stderr)
            if target:
                if worktree_path and getattr(self.transport, "interactive", False):
                    import shlex
                    cd_cmd = f"cd {shlex.quote(str(self.root))} && cd {shlex.quote(str(worktree_path))}"
                    self._send_transport_text(target, cd_cmd, unlock_buffers=unlock_buffers)
                self._send_transport_text(target, formatted_text, unlock_buffers=unlock_buffers)
            sync_path = self._sync_memory(sender, recipient, kind, message, task_id)
            return CommResult(
                ok=True,
                event_path=str(event_path),
                inbox_path=str(inbox_path),
                tmux_target=target,
                recipient=recipient,
                sender=sender,
                kind=kind,
                message=message,
                task_id=task_id,
                sync_path=sync_path,
                transport=self.transport.name if target else f"{self.transport.name}:file-only",
            )
        except Exception as exc:
            self._append_event(
                {
                    "event": "comm.failed",
                    "kind": kind,
                    "sender": sender,
                    "recipient": recipient,
                    "tmux_target": target,
                    "task_id": task_id,
                    "message": _short_text(normalized_message, 120),
                    "error": str(exc),
                }
            )
            sync_path = self._sync_memory(sender, recipient, kind, message, task_id)
            return CommResult(
                ok=True,
                event_path=str(event_path),
                inbox_path=str(inbox_path),
                tmux_target=target,
                recipient=recipient,
                sender=sender,
                kind=kind,
                message=message,
                task_id=task_id,
                error=str(exc),
                sync_path=sync_path,
                transport=f"{self.transport.name}:inbox-only",
            )

    def send_direct(
        self,
        recipient: str,
        message: str,
        sender: str = "telegram",
        task_id: str = "",
        tmux_target: Optional[str] = None,
        unlock_buffers: bool = True,
        worktree_path: Optional[Path] = None,
        auto_resolve_prompts: bool = True,
    ) -> CommResult:
        validate_safe_id(recipient, "recipient")
        validate_safe_id(sender, "sender")
        if not task_id:
            raise ValueError("task_id is required")
        validate_safe_id(task_id, "task_id")

        target = self._live_delivery_target(recipient, tmux_target=tmux_target)
        if target and auto_resolve_prompts and recipient != "telegram":
            self.auto_resolve_pending_prompt(recipient, target)
        inbox_path = self._append_inbox_payload(
            recipient,
            {
                "event": "comm.payload",
                "kind": "DIRECT",
                "sender": sender,
                "recipient": recipient,
                "message": message,
                "task_id": task_id,
            },
        )
        event_path = self._append_event(
            {
                "event": "comm.direct",
                "kind": "DIRECT",
                "sender": sender,
                "recipient": recipient,
                "tmux_target": target,
                "task_id": task_id,
                "message": _short_text(message, 120),
                "inbox_path": str(inbox_path.relative_to(self.root)),
                "transport": self.transport.name,
            }
        )

        try:
            if target:
                if worktree_path and getattr(self.transport, "interactive", False):
                    import shlex
                    cd_cmd = f"cd {shlex.quote(str(self.root))} && cd {shlex.quote(str(worktree_path))}"
                    self._send_transport_text(target, cd_cmd, unlock_buffers=unlock_buffers)
                self._send_transport_text(target, message, unlock_buffers=unlock_buffers)
            sync_path = self._sync_memory(sender, recipient, "DIRECT", message, task_id)
            return CommResult(
                ok=True,
                event_path=str(event_path),
                inbox_path=str(inbox_path),
                tmux_target=target,
                recipient=recipient,
                sender=sender,
                kind="DIRECT",
                message=message,
                task_id=task_id,
                sync_path=sync_path,
                transport=self.transport.name if target else f"{self.transport.name}:file-only",
            )
        except Exception as exc:
            self._append_event(
                {
                    "event": "comm.failed",
                    "kind": "DIRECT",
                    "sender": sender,
                    "recipient": recipient,
                    "tmux_target": target,
                    "task_id": task_id,
                    "message": _short_text(message, 120),
                    "error": str(exc),
                    "transport": self.transport.name,
                }
            )
            sync_path = self._sync_memory(sender, recipient, "DIRECT", message, task_id)
            return CommResult(
                ok=True,
                event_path=str(event_path),
                inbox_path=str(inbox_path),
                tmux_target=target,
                recipient=recipient,
                sender=sender,
                kind="DIRECT",
                message=message,
                task_id=task_id,
                error=str(exc),
                sync_path=sync_path,
                transport=f"{self.transport.name}:inbox-only",
            )

    def _load_inbox_messages(self, recipient: str) -> tuple[List[Dict[str, Any]], int]:
        """Returns (records, total_line_count). Each record carries _idx = raw line
        number in the append-only inbox file — the stable message id for cursor/read."""
        return self.store.load_inbox_messages(recipient)

    def _cursor_path(self, recipient: str) -> Path:
        return self.store.cursor_path(recipient)

    def _load_inbox_cursor(self, recipient: str, total_lines: Optional[int] = None) -> int:
        return self.store.load_inbox_cursor(recipient, total_lines)

    def _save_inbox_cursor(self, recipient: str, line: int) -> None:
        self.store.save_inbox_cursor(recipient, line)

    def reset_inbox_cursor(self, recipient: str) -> None:
        validate_safe_id(recipient, "recipient")
        self._save_inbox_cursor(recipient, 0)

    def fast_forward_inbox_if_uninitialized(self, recipient: str) -> bool:
        validate_safe_id(recipient, "recipient")
        if self._cursor_path(recipient).exists():
            return False
        _, total = self._load_inbox_messages(recipient)
        self._save_inbox_cursor(recipient, total)
        return True

    def read_message(self, recipient: str, idx: int) -> Optional[Dict[str, Any]]:
        """Full body of one inbox message by its line index (shown as [#idx] in listings)."""
        validate_safe_id(recipient, "recipient")
        return self.store.read_message(recipient, idx)

    def _load_comm_events(self, with_idx: bool = False) -> List[Dict[str, Any]]:
        return self.store.load_comm_events(with_idx)

    @property
    def _feed_cursor_path(self) -> Path:
        return self.store.feed_cursor_path

    def _event_line_count(self) -> int:
        return self.store.event_line_count()

    def _load_tasks(self) -> List[Dict[str, Any]]:
        from memory_os.toolkit.task_kernel import TaskKernel

        return TaskKernel(self.root).list_tasks()

    def inbox(
        self,
        recipient: str,
        limit: int = 20,
        task_id: Optional[str] = None,
        unread_only: bool = True,
        peek: bool = False,
    ) -> Dict[str, Any]:
        validate_safe_id(recipient, "recipient")
        if task_id is not None:
            validate_safe_id(task_id, "task_id")

        tasks = self._load_tasks()
        task_rows: List[Dict[str, Any]] = []
        for task in tasks:
            if task_id and task.get("id") != task_id:
                continue
            if task.get("agent") not in (None, recipient):
                continue
            if task.get("status") not in {"pending", "claimed", "running", "blocked", "review"}:
                continue
            task_rows.append(task)
        task_rows.sort(key=lambda t: t.get("updated_at", ""), reverse=True)
        task_rows = task_rows[:limit]

        records, total_lines = self._load_inbox_messages(recipient)
        cursor = self._load_inbox_cursor(recipient, total_lines=total_lines) if unread_only else 0
        inbox_rows = [
            m for m in records
            if m["_idx"] >= cursor and (task_id is None or m.get("task_id") == task_id)
        ]
        if unread_only:
            # oldest-first FIFO so nothing is skipped when limit truncates;
            # cursor advances only past what was actually shown
            inbox_rows.sort(key=lambda m: m["_idx"])
            shown = inbox_rows[:limit]
            if not peek and task_id is None and shown:
                new_cursor = shown[-1]["_idx"] + 1 if len(inbox_rows) > limit else total_lines
                self._save_inbox_cursor(recipient, new_cursor)
        else:
            inbox_rows.sort(key=lambda m: m.get("ts", ""), reverse=True)
            shown = inbox_rows[:limit]
            if not peek and task_id is None:
                self._save_inbox_cursor(recipient, total_lines)

        return {
            "recipient": recipient,
            "tasks": task_rows,
            "messages": shown,
            "task_count": len(task_rows),
            "message_count": len(shown),
            "unread_remaining": max(0, len(inbox_rows) - limit) if unread_only else 0,
            "now": datetime.now(_user_timezone(self.config)).isoformat(timespec="seconds"),
        }

    def status(self) -> Dict[str, Any]:
        registry = load_agent_registry(self.root)
        agents = registry.get("agent", {})
        user_tz = _user_timezone(self.config)
        tmux_targets = {
            agent_id: self._resolve_tmux_target(agent_id)
            for agent_id in agents
            if self._agent_config(agent_id).get("kind") in {"cli_agent", "local_model", "script", "shell"}
        }
        comm_events = self._load_comm_events()
        agent_health: Dict[str, Dict[str, Any]] = {}
        try:
            from memory_os.toolkit.agent_health import AgentHealthProbe

            probe = AgentHealthProbe(self.root)
            agent_health = probe.check_all(ttl=60, force=False)
        except Exception:
            agent_health = {}

        try:
            from memory_os.toolkit.quota_harvester import refresh_quota_state

            quota_state = refresh_quota_state(self.root)
        except Exception:
            quota_state = {}

        return {
            "multiplexer_available": self._multiplexer_available(),
            "transport": self.transport.name,
            "event_log": str(self.events_path),
            "inbox_dir": str(self.inbox_dir),
            "registered_agents": sorted(agents.keys()),
            "agent_registry": agents,
            "tmux_targets": tmux_targets,
            "user_timezone": str(user_tz),
            "agent_health": agent_health,
            "quota_state": quota_state,
            "message_events": len(comm_events),
            "recent_events": comm_events[-10:],
        }

    def feed(self, limit: int = 30, new_only: bool = False) -> List[Dict[str, Any]]:
        events = self._load_comm_events(with_idx=new_only)
        if new_only:
            cursor = self.store.load_feed_cursor()
            events = [e for e in events if e["_idx"] >= cursor]
            self.store.save_feed_cursor(self._event_line_count())
            for e in events:
                e.pop("_idx", None)
            events.sort(key=lambda e: e.get("ts", ""))
            return events[:limit]
        events.sort(key=lambda e: e.get("ts", ""))
        return events[-limit:]

    def resume_report(self, limit: int = 5) -> Dict[str, Any]:
        user_tz = _user_timezone(self.config)
        events = self._load_comm_events()
        events.sort(key=lambda e: e.get("ts", ""))
        status_reports = [e for e in events if e.get("kind") == "STATUS_REPORT"]
        recent_reports = status_reports[-limit:]
        status = self.status()
        return {
            "generated_at": _format_user_time(_now_iso(), user_tz),
            "user_timezone": status.get("user_timezone", str(user_tz)),
            "agents": status.get("agent_health", {}),
            "quota_state": status.get("quota_state", {}),
            "recent_status_reports": recent_reports,
        }



def format_inbox_text(inbox: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"now: {inbox.get('now', '')}")
    lines.append(f"recipient: {inbox['recipient']}")
    lines.append(f"tasks: {inbox['task_count']}")
    lines.append(f"messages: {inbox['message_count']}")
    remaining = inbox.get("unread_remaining", 0)
    if remaining:
        lines.append(f"unread_remaining: {remaining} (run inbox again)")
    lines.append("")

    if inbox["tasks"]:
        lines.append("Tasks")
        for task in inbox["tasks"]:
            agent = task.get("agent") or "unassigned"
            lines.append(
                f"- {task.get('id')} [{task.get('status')}] [{task.get('risk')}] {_short_text(task.get('title', ''), 60)} (agent={agent})"
            )
        lines.append("")

    if inbox["messages"]:
        lines.append("Messages  (full body: memory_os comm read <#id> --recipient <agent>)")
        for msg in inbox["messages"]:
            rel = _relative_time(msg.get("ts", ""))
            rel_part = f" ({rel})" if rel else ""
            lines.append(
                f"- [#{msg.get('_idx', '?')}] {msg.get('ts')}{rel_part} [{msg.get('kind')}] {msg.get('sender')}: {_short_text(msg.get('message', ''), 120)}"
            )
        lines.append("")

    if not inbox["tasks"] and not inbox["messages"]:
        lines.append("(no new messages)")

    return "\n".join(lines).rstrip()


def format_status_text(status: Dict[str, Any]) -> str:
    lines = [
        f"multiplexer_available: {status['multiplexer_available']}",
        f"transport: {status.get('transport', 'unknown')}",
        f"user_timezone: {status.get('user_timezone', 'unknown')}",
        f"event_log: {status['event_log']}",
        f"message_events: {status['message_events']}",
        "",
        "agents:",
    ]
    agents = status.get("agent_health", {})
    quota_state = status.get("quota_state", {})
    registry = status.get("agent_registry", {})
    user_tz = _coerce_timezone(status.get("user_timezone", ""))
    if agents:
        for agent_id, health in agents.items():
            state = quota_state.get(agent_id, {}) if isinstance(quota_state, dict) else {}
            spec = registry.get(agent_id, {}) if isinstance(registry, dict) else {}
            limit_summary = format_agent_limit_summary(spec=spec, health=health, state=state)
            limit_suffix = ""
            if agent_limit_active(health=health, state=state):
                reset_at = _format_user_timestamp(state.get("reset_at"), user_tz)
                limit_suffix = f" {limit_summary} limit_until={reset_at}" if reset_at else f" {limit_summary} limit=active"
            elif state.get("has_limit") is False:
                limit_suffix = f" {limit_summary}"
            elif limit_summary:
                limit_suffix = f" {limit_summary}"
            lines.append(f"- {agent_id}: {health.get('status', '?')} ({health.get('detail', '')}){limit_suffix}")
    else:
        lines.append("- (unknown)")

    lines.extend([
        "",
        "tmux_targets:",
    ])
    if status["tmux_targets"]:
        for agent_id, target in status["tmux_targets"].items():
            lines.append(f"- {agent_id}: {target}")
    else:
        lines.append("- (none)")

    if status.get("recent_events"):
        lines.append("")
        lines.append("recent_events:")
        for event in status["recent_events"]:
            lines.append(
                f"- {_format_user_time(event.get('ts', ''), user_tz)} {event.get('event')} [{event.get('kind', '?')}] {event.get('sender', '?')} -> {event.get('recipient', '?')}"
            )

    return "\n".join(lines)


def format_feed_text(events: List[Dict[str, Any]]) -> str:
    if not events:
        return "=== Memory OS Live Feed ===\n(no inter-agent communication events recorded)"
    user_tz = _user_timezone(MemoryOSConfig())
    now_str = datetime.now(user_tz).isoformat(timespec="seconds")
    lines = [f"=== Memory OS Live Feed ===  now: {now_str}"]
    for ev in events:
        ts = _format_user_time(ev.get("ts", ""), user_tz)
        rel = _relative_time(ev.get("ts", ""))
        rel_part = f" ({rel})" if rel else ""
        kind = ev.get("kind", "?")
        sender = ev.get("sender", "?")
        recipient = ev.get("recipient", "?")
        msg = ev.get("message", "")
        lines.append(f"[{ts}]{rel_part} [{kind}] {sender} -> {recipient} | {msg}")
    return "\n".join(lines)


def format_resume_report(report: Dict[str, Any]) -> str:
    lines = [
        f"Resume report: {report.get('generated_at', '')}",
        f"Timezone: {report.get('user_timezone', 'unknown')}",
        "",
        "Agents:",
    ]
    agents = report.get("agents", {})
    quota_state = report.get("quota_state", {})
    if agents:
        for agent_id, health in agents.items():
            status = health.get("status", "?")
            detail = health.get("detail", "")
            state = quota_state.get(agent_id, {}) if isinstance(quota_state, dict) else {}
            suffix = ""
            if state.get("has_limit") is True:
                suffix = " | limit active"
            elif state.get("has_limit") is False:
                suffix = " | limit clear"
            lines.append(f"- {agent_id}: {status} ({detail}){suffix}")
    else:
        lines.append("- unknown")

    lines.append("")
    lines.append("Last completed tasks:")
    reports = report.get("recent_status_reports", [])
    if reports:
        user_tz = _coerce_timezone(report.get("user_timezone", ""))
        for ev in reports:
            ts = _format_user_time(ev.get("ts", ""), user_tz)
            msg = _short_text(ev.get("message", ""), 180)
            lines.append(f"- {ts} [{ev.get('task_id', '?')}] {ev.get('sender', '?')} -> {ev.get('recipient', '?')}: {msg}")
    else:
        lines.append("- no STATUS_REPORT events")
    return "\n".join(lines)
