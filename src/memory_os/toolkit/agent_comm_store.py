"""File persistence for agent communication events, inboxes, and cursors."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_os.core.safe_id import validate_safe_id


EVENTS_FILE = "agent_context/task_events.jsonl"
INBOX_DIR = "agent_context/inbox"
DONE_DIR = "agent_context/done"
ROTATE_SIZE_BYTES = 1_500_000


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class AgentCommStore:
    def __init__(self, root: Path):
        self.root = root
        self.events_path = root / EVENTS_FILE
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self.inbox_dir = root / INBOX_DIR
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.done_dir = root / DONE_DIR
        self.done_dir.mkdir(parents=True, exist_ok=True)

    @property
    def feed_cursor_path(self) -> Path:
        return self.root / "agent_context" / "feed_cursor.json"

    def inbox_path(self, recipient: str) -> Path:
        validate_safe_id(recipient, "recipient")
        return self.inbox_dir / f"{recipient}.jsonl"

    def cursor_path(self, recipient: str) -> Path:
        validate_safe_id(recipient, "recipient")
        return self.inbox_dir / f".cursor_{recipient}.json"

    def append_event(self, record: Dict[str, Any]) -> Path:
        payload = dict(record)
        payload.setdefault("ts", utc_now_iso())
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        if self.events_path.stat().st_size > ROTATE_SIZE_BYTES:
            self.rotate_events()
        return self.events_path

    def append_inbox_payload(self, recipient: str, record: Dict[str, Any]) -> Path:
        path = self.inbox_path(recipient)
        payload = dict(record)
        payload.setdefault("ts", utc_now_iso())
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        if path.stat().st_size > ROTATE_SIZE_BYTES:
            self.rotate_inbox(recipient)
        return path

    def write_done_signal(self, task_id: str, sender: str, message: str) -> Path:
        path = self.done_dir / f"{task_id}.json"
        payload = {
            "task_id": task_id,
            "sender": sender,
            "message": message,
            "ts": utc_now_iso(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def rotate_events(self, keep: int = 1000) -> Optional[Path]:
        return self._rotate_file(self.events_path, "task_events", keep, self.feed_cursor_path)

    def rotate_inbox(self, recipient: str, keep: int = 200) -> Optional[Path]:
        return self._rotate_file(
            self.inbox_path(recipient),
            f"inbox-{recipient}",
            keep,
            self.cursor_path(recipient),
        )

    def _rotate_file(self, path: Path, label: str, keep: int, cursor_path: Path) -> Optional[Path]:
        if not path.exists():
            return None
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(lines) <= keep:
            return None
        dropped = len(lines) - keep
        archive_dir = self.root / "agent_context" / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        stamp = utc_now_iso().replace(":", "").replace("+00:00", "Z")
        archive = archive_dir / f"{label}-{stamp}.jsonl"
        archive.write_text("\n".join(lines[:dropped]) + "\n", encoding="utf-8")
        live_lines = lines[dropped:]
        path.write_text("\n".join(live_lines) + "\n", encoding="utf-8")
        if cursor_path.exists():
            try:
                cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
                cursor["line"] = min(len(live_lines), max(0, int(cursor.get("line", 0)) - dropped))
            except (json.JSONDecodeError, OSError, ValueError):
                cursor = {"line": len(live_lines)}
            cursor_path.write_text(json.dumps(cursor), encoding="utf-8")
        return archive

    def load_inbox_messages(self, recipient: str) -> tuple[List[Dict[str, Any]], int]:
        path = self.inbox_path(recipient)
        if not path.exists():
            return [], 0
        records: List[Dict[str, Any]] = []
        total = 0
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            total = index + 1
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            record["_idx"] = index
            records.append(record)
        return records, total

    def load_inbox_cursor(self, recipient: str, total_lines: Optional[int] = None) -> int:
        path = self.cursor_path(recipient)
        if not path.exists():
            return 0
        try:
            line = int(json.loads(path.read_text(encoding="utf-8")).get("line", 0))
        except (json.JSONDecodeError, OSError, ValueError):
            line = total_lines if total_lines is not None else 0
            self.save_inbox_cursor(recipient, line)
            return line
        if line < 0:
            self.save_inbox_cursor(recipient, 0)
            return 0
        if total_lines is not None and line > total_lines:
            self.save_inbox_cursor(recipient, total_lines)
            return total_lines
        return line

    def save_inbox_cursor(self, recipient: str, line: int) -> None:
        path = self.cursor_path(recipient)
        path.write_text(json.dumps({"line": line, "ts": utc_now_iso()}), encoding="utf-8")

    def read_message(self, recipient: str, index: int) -> Optional[Dict[str, Any]]:
        path = self.inbox_path(recipient)
        if not path.exists():
            return None
        for line_index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if line_index == index:
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    return None
        return None

    def load_comm_events(self, with_idx: bool = False) -> List[Dict[str, Any]]:
        if not self.events_path.exists():
            return []
        records: List[Dict[str, Any]] = []
        for index, line in enumerate(self.events_path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("event", "").startswith("comm."):
                if with_idx:
                    record["_idx"] = index
                records.append(record)
        return records

    def event_line_count(self) -> int:
        if not self.events_path.exists():
            return 0
        return len(self.events_path.read_text(encoding="utf-8").splitlines())

    def load_feed_cursor(self) -> int:
        if not self.feed_cursor_path.exists():
            return 0
        try:
            return int(json.loads(self.feed_cursor_path.read_text(encoding="utf-8")).get("line", 0))
        except (json.JSONDecodeError, OSError, ValueError):
            return 0

    def save_feed_cursor(self, line: int) -> None:
        self.feed_cursor_path.write_text(json.dumps({"line": line, "ts": utc_now_iso()}), encoding="utf-8")
