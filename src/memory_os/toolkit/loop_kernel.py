"""File-backed loop engineering kernel.

TaskKernel owns task lifecycle. LoopKernel owns repeated attempts around a
task: which agent tried, what verifier said, whether retry/failover is allowed.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOOPS_FILE = "agent_context/loops.jsonl"
_VALID_STATUSES = {"running", "passed", "failed", "abandoned"}
_VALID_VERDICTS = {"pass", "fail"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass(frozen=True)
class LoopPolicy:
    max_attempts: int = 5
    verifier_required: bool = True
    allow_failover: bool = True


class LoopKernel:
    def __init__(self, root: Path, policy: Optional[LoopPolicy] = None):
        self.root = root
        self.policy = policy or LoopPolicy()
        self.path = root / _LOOPS_FILE
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, record: Dict[str, Any]) -> None:
        payload = dict(record)
        payload.setdefault("ts", _now_iso())
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _records(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def attempts(self, task_id: str) -> List[Dict[str, Any]]:
        attempts: Dict[str, Dict[str, Any]] = {}
        for rec in self._records():
            if rec.get("task_id") != task_id:
                continue
            attempt_id = rec.get("attempt_id")
            if not attempt_id:
                continue
            current = attempts.get(attempt_id, {})
            current.update(rec)
            attempts[attempt_id] = current
        return sorted(attempts.values(), key=lambda item: item.get("created_at", item.get("ts", "")))

    def start_attempt(
        self,
        task_id: str,
        agent_id: str,
        *,
        runtime: str = "unknown",
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        existing = self.attempts(task_id)
        if len(existing) >= self.policy.max_attempts:
            raise RuntimeError(f"retry budget exhausted for {task_id}")
        attempt = {
            "event": "loop.attempt_started",
            "task_id": task_id,
            "attempt_id": f"attempt_{_short_id()}",
            "attempt_no": len(existing) + 1,
            "agent_id": agent_id,
            "runtime": runtime,
            "workspace": workspace,
            "status": "running",
            "created_at": _now_iso(),
        }
        self._append(attempt)
        return attempt

    def record_verifier(
        self,
        task_id: str,
        attempt_id: str,
        *,
        verifier: str,
        verdict: str,
        feedback: str = "",
    ) -> Dict[str, Any]:
        if verdict not in _VALID_VERDICTS:
            raise ValueError(f"verdict must be one of {sorted(_VALID_VERDICTS)}")
        status = "passed" if verdict == "pass" else "failed"
        record = {
            "event": "loop.verifier_result",
            "task_id": task_id,
            "attempt_id": attempt_id,
            "verifier": verifier,
            "verdict": verdict,
            "feedback": feedback,
            "status": status,
        }
        self._append(record)
        return record

    def abandon_attempt(self, task_id: str, attempt_id: str, reason: str) -> Dict[str, Any]:
        record = {
            "event": "loop.attempt_abandoned",
            "task_id": task_id,
            "attempt_id": attempt_id,
            "reason": reason,
            "status": "abandoned",
        }
        self._append(record)
        return record

    def decision(self, task_id: str) -> Dict[str, Any]:
        attempts = self.attempts(task_id)
        if any(attempt.get("status") == "passed" for attempt in attempts):
            return {"action": "complete", "reason": "verifier passed", "attempts": len(attempts)}
        running = [attempt for attempt in attempts if attempt.get("status") == "running"]
        if running:
            return {"action": "wait", "reason": "attempt running", "attempts": len(attempts)}
        if len(attempts) >= self.policy.max_attempts:
            return {"action": "stop", "reason": "retry budget exhausted", "attempts": len(attempts)}
        failed = [attempt for attempt in attempts if attempt.get("status") in {"failed", "abandoned"}]
        if failed and self.policy.allow_failover:
            return {"action": "failover", "reason": "latest attempt failed", "attempts": len(attempts)}
        return {"action": "retry", "reason": "budget available", "attempts": len(attempts)}
