"""Passive console scanner for agent quota/status signals."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from memory_os.toolkit.agent_registry import load_agent_registry
from memory_os.toolkit.console_parser import get_parser
from memory_os.toolkit.multiplexer_manager import MultiplexerManager, MultiplexerPaneInfo
from memory_os.toolkit.usage_probe import parse_usage_screen, persist_usage_state


@dataclass
class ConsoleScanEvent:
    agent_id: str
    kind: str
    keyword: str
    line: str
    reset_at: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "agent_id": self.agent_id,
            "kind": self.kind,
            "keyword": self.keyword,
            "line": self.line,
        }
        if self.reset_at is not None:
            payload["reset_at"] = self.reset_at
        return payload


class AgentConsoleScanner:
    def __init__(
        self,
        root: Path,
        multiplexer: Optional[MultiplexerManager] = None,
        lines: int = 300,
    ):
        self.root = root
        self.multiplexer = multiplexer or MultiplexerManager(root)
        self.lines = lines
        self.state_file = self.root / "agent_context" / "agents" / "console_scan_state.json"
        self.health_file = self.root / "agent_context" / "agents" / "health_cache.json"

    def scan_once(self, agent_ids: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        registry = load_agent_registry(self.root).get("agent", {})
        wanted = set(agent_ids or [])
        agents = {
            agent_id: spec
            for agent_id, spec in registry.items()
            if spec.get("kind") == "cli_agent" and (not wanted or agent_id in wanted)
        }
        if not agents:
            return []

        state = self._load_json(self.state_file)
        panes = self._list_panes()
        events: List[Dict[str, Any]] = []

        for agent_id in sorted(agents):
            try:
                target = self.multiplexer.resolve_pane_target(agent_id)
                if not self._pane_active(agent_id, target, panes):
                    continue
                content = self.multiplexer.capture_pane(target, lines=self.lines, full_history=True)
                if not content:
                    continue
                event = self._scan_agent_text(agent_id, content, state.setdefault(agent_id, {}))
                if event:
                    if event.kind == "quota_exhausted":
                        self._record_limit_event(event)
                    events.append(event.to_dict())
            except Exception:
                continue

        self._save_json(self.state_file, state)
        return events

    def _scan_agent_text(self, agent_id: str, content: str, state_entry: Dict[str, Any]) -> Optional[ConsoleScanEvent]:
        current_lines = [line for line in content.splitlines() if line.strip()]
        previous_lines = state_entry.get("lines") if isinstance(state_entry.get("lines"), list) else []
        previous_set = set(previous_lines)

        if previous_lines:
            candidate_lines = [line for line in current_lines if line not in previous_set]
        else:
            candidate_lines = current_lines[-40:]

        state_entry["lines"] = current_lines[-self.lines:]
        state_entry["scanned_at"] = time.time()

        usage = parse_usage_screen(content)
        if usage:
            signature = json.dumps(usage, sort_keys=True)
            if state_entry.get("usage_signature") != signature:
                state_entry["usage_signature"] = signature
                persist_usage_state(self.root, agent_id, usage)
                return ConsoleScanEvent(
                    agent_id=agent_id,
                    kind="usage_snapshot",
                    keyword="usage",
                    line="usage screen parsed",
                )

        if not candidate_lines:
            return None
        if agent_id == "codex":
            return None

        text = "\n".join(candidate_lines)
        parser = get_parser(agent_id)
        if hasattr(parser, "extract_limit_event"):
            limit_event = parser.extract_limit_event(text, strict=True)  # type: ignore[attr-defined]
        else:
            limit_event = parser.parse(agent_id, text).get("limit_event")
        if not limit_event:
            return None

        return ConsoleScanEvent(
            agent_id=agent_id,
            kind="quota_exhausted",
            keyword=str(limit_event.get("keyword", "limit")),
            line=str(limit_event.get("line", "")),
        )

    def _record_limit_event(self, event: ConsoleScanEvent) -> None:
        from memory_os.toolkit.quota_harvester import record_limit_mention
        from memory_os.toolkit.quota_store import QuotaStore

        record_limit_mention(self.root, event.agent_id, event.line)
        quota_state = QuotaStore(self.root).load()
        quota_entry = quota_state.get(event.agent_id, {})
        event.reset_at = quota_entry.get("reset_at")

        health = self._load_json(self.health_file)
        existing = health.get(event.agent_id, {}) if isinstance(health.get(event.agent_id), dict) else {}
        existing.update({
            "status": "quota_exhausted",
            "detail": f"Quota limit detected in {event.agent_id} console",
            "ts": time.time(),
            "console_info": get_parser(event.agent_id).parse(event.agent_id, event.line),
        })
        health[event.agent_id] = existing
        self._save_json(self.health_file, health)

    def _list_panes(self) -> List[MultiplexerPaneInfo]:
        try:
            return self.multiplexer.list_panes(self.multiplexer.session_name)
        except Exception:
            return []

    @staticmethod
    def _pane_active(agent_id: str, target: str, panes: List[MultiplexerPaneInfo]) -> bool:
        if not panes:
            return bool(target)
        return any(
            str(pane.target) == str(target) or str(pane.current_command) == agent_id
            for pane in panes
        )

    @staticmethod
    def _load_json(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    @staticmethod
    def _save_json(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
