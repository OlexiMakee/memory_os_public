"""Runtime schema and persistence for node access statistics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

from memory_os.core.interfaces import IMemoryStorage
from memory_os.core.storage import FileSystemMemoryStorage


@dataclass(frozen=True)
class NodeAccessStat:
    count: int = 0
    last_accessed: str = ""

    @classmethod
    def from_dict(cls, value: object) -> "NodeAccessStat":
        if not isinstance(value, dict):
            return cls()
        count = value.get("count", 0)
        return cls(
            count=max(0, int(count)) if isinstance(count, (int, float)) else 0,
            last_accessed=str(value.get("last_accessed") or ""),
        )


class NodeStatsStore:
    def __init__(self, path: Path, storage: Optional[IMemoryStorage] = None):
        self.path = Path(path)
        self.storage = storage or FileSystemMemoryStorage()

    def load(self) -> Dict[str, NodeAccessStat]:
        try:
            payload = self.storage.load_json(self.path)
        except (OSError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(node_id): NodeAccessStat.from_dict(value) for node_id, value in payload.items()}

    def record_access(self, node_ids: Iterable[str], accessed_at: Optional[str] = None) -> None:
        stats = self.load()
        timestamp = accessed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for node_id in dict.fromkeys(str(value) for value in node_ids if str(value)):
            current = stats.get(node_id, NodeAccessStat())
            stats[node_id] = NodeAccessStat(count=current.count + 1, last_accessed=timestamp)
        self.storage.save_json(self.path, {node_id: asdict(stat) for node_id, stat in stats.items()})
