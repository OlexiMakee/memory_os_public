"""File-backed Task Kernel for Memory OS agentic OS layer.

Storage layout (all under project root):
  agent_context/tasks.jsonl        — append-only task records
  agent_context/task_events.jsonl  — append-only event log
  agent_context/leases.json        — mutable lease map {task_id: {owner, expires}}

State machine:
  pending → claimed → running → blocked → review → done
                 ↑_______________↓ (unblock)
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


_TASKS_FILE = "agent_context/tasks.jsonl"
_EVENTS_FILE = "agent_context/task_events.jsonl"
_LEASES_FILE = "agent_context/leases.json"

_VALID_STATUSES = {"pending", "claimed", "running", "blocked", "review", "done"}
_VALID_RISKS = {"low", "medium", "high"}

_TRANSITIONS: Dict[str, List[str]] = {
    "pending":  ["claimed", "done"],
    "claimed":  ["running", "blocked", "pending"],
    "running":  ["blocked", "review", "done"],
    "blocked":  ["claimed", "running", "done"],
    "review":   ["done", "running"],
    "done":     [],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


class TaskKernel:
    def __init__(self, root: Path):
        self.root = root
        self.tasks_path = root / _TASKS_FILE
        self.events_path = root / _EVENTS_FILE
        self.leases_path = root / _LEASES_FILE
        self.tasks_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Storage helpers                                                       #
    # ------------------------------------------------------------------ #

    def _load_tasks(self) -> List[Dict[str, Any]]:
        if not self.tasks_path.exists():
            return []
        records: Dict[str, Dict] = {}
        for line in self.tasks_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            task_id = rec.get("id")
            if task_id:
                records[task_id] = rec  # last write wins
        return list(records.values())

    def _load_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        for t in self._load_tasks():
            if t["id"] == task_id:
                return t
        return None

    def _append_task(self, task: Dict[str, Any]) -> None:
        with self.tasks_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(task, ensure_ascii=False) + "\n")

    def _append_event(self, task_id: str, event: str,
                      agent: Optional[str] = None,
                      reason: Optional[str] = None) -> None:
        record = {"task_id": task_id, "event": event, "ts": _now_iso()}
        if agent:
            record["agent"] = agent
        if reason:
            record["reason"] = reason
        if not self.events_path.exists():
            self.events_path.touch()
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _load_leases(self) -> Dict[str, Any]:
        if not self.leases_path.exists():
            return {}
        try:
            return json.loads(self.leases_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_leases(self, leases: Dict[str, Any]) -> None:
        self.leases_path.write_text(json.dumps(leases, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------ #
    # Public API                                                            #
    # ------------------------------------------------------------------ #

    def list_leases(self) -> Dict[str, Any]:
        return self._load_leases()

    def create(
        self,
        title: str,
        goal: str = "",
        risk: str = "low",
        capabilities: Optional[List[str]] = None,
        done_criteria: Optional[str] = None,
    ) -> Dict[str, Any]:
        if risk not in _VALID_RISKS:
            raise ValueError(f"risk must be one of {_VALID_RISKS}")
        now = _now_iso()
        task: Dict[str, Any] = {
            "id": f"task_{_short_id()}",
            "title": title,
            "goal": goal,
            "status": "pending",
            "risk": risk,
            "capabilities": capabilities or [],
            "agent": None,
            "lease_owner": None,
            "lease_expires": None,
            "context_pack": None,
            "evidence": None,
            "retry_count": 0,
            "blocked_reason": None,
            "handoff_summary": None,
            "done_criteria": done_criteria,
            "created_at": now,
            "updated_at": now,
        }
        self._append_task(task)
        self._append_event(task["id"], "created")
        return task

    def list_tasks(
        self,
        status: Optional[str] = None,
        agent: Optional[str] = None,
        risk: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        tasks = self._load_tasks()
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        if agent:
            tasks = [t for t in tasks if t.get("agent") == agent]
        if risk:
            tasks = [t for t in tasks if t.get("risk") == risk]
        return tasks

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._load_task(task_id)

    def _update(self, task_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        task = self._load_task(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")
        task.update(updates)
        task["updated_at"] = _now_iso()
        self._append_task(task)
        return task

    def claim(self, task_id: str, agent: str, lease_minutes: int = 30) -> Dict[str, Any]:
        task = self._load_task(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")
        if task["status"] not in ("pending", "blocked"):
            raise ValueError(f"Cannot claim task in status '{task['status']}'")
        from datetime import timedelta
        expires = (datetime.now(timezone.utc) + timedelta(minutes=lease_minutes)).replace(microsecond=0).isoformat()
        leases = self._load_leases()
        leases[task_id] = {"owner": agent, "expires": expires}
        self._save_leases(leases)
        task = self._update(task_id, {"status": "claimed", "agent": agent, "lease_owner": agent, "lease_expires": expires})
        self._append_event(task_id, "claimed", agent=agent)
        return task

    def start(self, task_id: str) -> Dict[str, Any]:
        task = self._load_task(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")
        if task["status"] not in ("claimed", "blocked"):
            raise ValueError(f"Cannot start task in status '{task['status']}'")
        task = self._update(task_id, {"status": "running"})
        self._append_event(task_id, "started", agent=task.get("agent"))
        return task

    def block(self, task_id: str, reason: str) -> Dict[str, Any]:
        task = self._load_task(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")
        if task["status"] not in ("claimed", "running"):
            raise ValueError(f"Cannot block task in status '{task['status']}'")
        task = self._update(task_id, {"status": "blocked", "blocked_reason": reason})
        self._append_event(task_id, "blocked", reason=reason)
        return task

    def review(self, task_id: str, summary: Optional[str] = None) -> Dict[str, Any]:
        task = self._load_task(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")
        if task["status"] not in ("running",):
            raise ValueError(f"Cannot move task to review from status '{task['status']}'")
        updates: Dict[str, Any] = {"status": "review"}
        if summary:
            updates["handoff_summary"] = summary
        task = self._update(task_id, updates)
        self._append_event(task_id, "review", agent=task.get("agent"))
        return task

    def done(self, task_id: str, summary: Optional[str] = None) -> Dict[str, Any]:
        task = self._load_task(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")
        if task["status"] not in ("running", "review", "pending", "blocked"):
            raise ValueError(f"Cannot mark done from status '{task['status']}'")
        updates: Dict[str, Any] = {"status": "done"}
        if summary:
            updates["handoff_summary"] = summary
        task = self._update(task_id, updates)
        leases = self._load_leases()
        leases.pop(task_id, None)
        self._save_leases(leases)
        self._append_event(task_id, "done", agent=task.get("agent"))
        return task

    def unclaim(self, task_id: str) -> Dict[str, Any]:
        """Release a claim without completing the task — returns to pending."""
        task = self._load_task(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")
        task = self._update(task_id, {
            "status": "pending",
            "agent": None,
            "lease_owner": None,
            "lease_expires": None,
        })
        leases = self._load_leases()
        leases.pop(task_id, None)
        self._save_leases(leases)
        self._append_event(task_id, "unclaimed")
        return task

    def expire_stale(self, hours: float = 24.0, title_prefix: str = "telegram") -> List[Dict[str, Any]]:
        """Auto-close chat-originated tasks with no activity for `hours`.

        Telegram dispatch creates a kernel task per chat message and nothing
        closes them once the conversation moves on, so they pile up in
        running/blocked forever. Only tasks whose title starts with
        `title_prefix` are touched — real work items stay untouched.
        """
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        expired: List[Dict[str, Any]] = []
        for task in self._load_tasks():
            if task.get("status") not in ("pending", "claimed", "running", "blocked", "review"):
                continue
            if not str(task.get("title", "")).startswith(title_prefix):
                continue
            updated_raw = str(task.get("updated_at") or task.get("created_at") or "")
            try:
                updated = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if updated >= cutoff:
                continue
            task = self._update(task["id"], {
                "status": "done",
                "handoff_summary": f"auto-expired: no activity for {hours:g}h",
            })
            leases = self._load_leases()
            leases.pop(task["id"], None)
            self._save_leases(leases)
            self._append_event(task["id"], "expired")
            expired.append(task)
        return expired

    def stale_leases(self) -> List[Dict[str, Any]]:
        """Return leases that are past their expiry time."""
        leases = self._load_leases()
        now = _now_iso()
        stale = []
        for task_id, lease in leases.items():
            if lease.get("expires", "9999") < now:
                stale.append({"task_id": task_id, **lease})
        return stale

    def release_stale_leases(self) -> List[Dict[str, Any]]:
        """Deterministically heal tasks whose lease expired.

        claimed -> pending (lease vanished before work really started)
        running/review -> blocked (agent disappeared mid-flight)
        """
        healed: List[Dict[str, Any]] = []
        for lease in self.stale_leases():
            task = self.get(lease["task_id"])
            if not task:
                continue
            status = task.get("status")
            if status == "claimed":
                updated = self.unclaim(lease["task_id"])
                self._append_event(lease["task_id"], "lease_expired", reason="claimed lease expired; returned to pending")
                healed.append({"task_id": lease["task_id"], "action": "unclaim", "status": updated["status"]})
                continue
            if status in ("running", "review"):
                updated = self._update(lease["task_id"], {
                    "status": "blocked",
                    "blocked_reason": "lease expired; agent likely abandoned task",
                })
                leases = self._load_leases()
                leases.pop(lease["task_id"], None)
                self._save_leases(leases)
                self._append_event(lease["task_id"], "lease_expired", reason="running lease expired; blocked for reassignment")
                healed.append({"task_id": lease["task_id"], "action": "block", "status": updated["status"]})
        return healed

    def events(self, task_id: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.events_path.exists():
            return []
        records = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if task_id is None or rec.get("task_id") == task_id:
                records.append(rec)
        if limit:
            records = records[-limit:]
        return records
