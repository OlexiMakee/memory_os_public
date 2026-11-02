from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from typing import Any, Dict, List, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.patch import RelationPatchStore
from memory_os.core.repository import MemoryRepository
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.core.timecode import is_offset_aware, normalize_timecode, parse_timecode, user_timezone


@dataclass
class TimecodeNormalizationResult:
    nodes_fixed: int
    events_fixed: int
    unresolvable: int

    def to_dict(self) -> Dict[str, int]:
        return {
            "nodes_fixed": self.nodes_fixed,
            "events_fixed": self.events_fixed,
            "unresolvable": self.unresolvable,
        }


class TimecodeNormalizer:
    def __init__(self, config: Optional[MemoryOSConfig] = None, repository: Optional[MemoryRepository] = None):
        self.config = config or MemoryOSConfig()
        self.storage = FileSystemMemoryStorage()
        self.repository = repository or MemoryRepository(self.storage, self.config)

    def normalize(self) -> TimecodeNormalizationResult:
        nodes = self.storage.load_jsonl(self.config.memory_dir / "nodes.jsonl")
        events = self.storage.load_jsonl(self.config.memory_dir / "events.jsonl")
        target_tz = user_timezone(self.config)
        event_time_by_node = self._earliest_event_times(events, target_tz)

        updated_nodes: List[Dict[str, Any]] = []
        nodes_fixed = 0
        unresolvable = 0
        for node in nodes:
            updated = dict(node)
            changed = False
            for field in ("freshness", "valid_from", "valid_until"):
                if field not in updated:
                    continue
                resolved = self._normalize_node_field(updated, field, event_time_by_node, target_tz)
                if resolved is None:
                    continue
                value, unresolved = resolved
                if unresolved:
                    unresolvable += 1
                if updated.get(field) != value:
                    updated[field] = value
                    changed = True
            if changed:
                nodes_fixed += 1
            updated_nodes.append(updated)

        updated_events: List[Dict[str, Any]] = []
        events_fixed = 0
        for event in events:
            updated = dict(event)
            if is_offset_aware(updated.get("timestamp")):
                updated_events.append(updated)
                continue
            normalized = normalize_timecode(updated.get("timestamp"), target_tz, assume_tz=timezone.utc)
            if normalized is None:
                if updated.get("timestamp"):
                    unresolvable += 1
                updated_events.append(updated)
                continue
            if updated.get("timestamp") != normalized:
                updated["timestamp"] = normalized
                events_fixed += 1
            updated_events.append(updated)

        store = RelationPatchStore(self.repository)
        if events_fixed:
            patch = self.repository._make_patch(
                operation="replace_events",
                target="memory/events.jsonl",
                payload={"events": updated_events},
                reason="normalize memory event timecodes",
            )
            store.apply(store.propose(patch))

        if nodes_fixed:
            patch = self.repository._make_patch(
                operation="replace_nodes",
                target="memory/nodes.jsonl",
                payload={"nodes": updated_nodes},
                reason="normalize memory node timecodes",
            )
            store.apply(store.propose(patch))

        return TimecodeNormalizationResult(
            nodes_fixed=nodes_fixed,
            events_fixed=events_fixed,
            unresolvable=unresolvable,
        )

    def _earliest_event_times(self, events: List[Dict[str, Any]], target_tz: Any) -> Dict[str, str]:
        parsed_by_node: Dict[str, Any] = {}
        normalized_by_node: Dict[str, str] = {}
        for event in events:
            node_id = event.get("node_id")
            if not node_id:
                continue
            parsed = parse_timecode(event.get("timestamp"), assume_tz=timezone.utc)
            if parsed is None:
                continue
            if node_id not in parsed_by_node or parsed < parsed_by_node[node_id]:
                parsed_by_node[node_id] = parsed
                normalized_by_node[node_id] = parsed.astimezone(target_tz).replace(microsecond=0).isoformat(timespec="seconds")
        return normalized_by_node

    def _normalize_node_field(
        self,
        node: Dict[str, Any],
        field: str,
        event_time_by_node: Dict[str, str],
        target_tz: Any,
    ) -> Optional[tuple[str, bool]]:
        value = node.get(field)
        if not isinstance(value, str):
            return None
        if value.strip().lower() == "fresh":
            replacement = self._fresh_replacement(node, field, event_time_by_node, target_tz)
            return (replacement or "", not bool(replacement))
        if is_offset_aware(value):
            return None
        normalized = normalize_timecode(value, target_tz, assume_tz=timezone.utc)
        if normalized is None:
            return None
        return (normalized, False)

    def _fresh_replacement(
        self,
        node: Dict[str, Any],
        field: str,
        event_time_by_node: Dict[str, str],
        target_tz: Any,
    ) -> str:
        event_time = event_time_by_node.get(str(node.get("id", "")))
        if event_time:
            return event_time
        for fallback_field in ("valid_from", "freshness"):
            if fallback_field == field:
                continue
            normalized = normalize_timecode(node.get(fallback_field), target_tz, assume_tz=timezone.utc)
            if normalized:
                return normalized
        return ""
