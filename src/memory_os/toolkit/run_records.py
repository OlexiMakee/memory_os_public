"""
Native Memory OS run/checkpoint records.

Each run is one small JSON record under:
agent_context/runs/<run_id>/record.json
"""

from __future__ import annotations

import fcntl
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.safe_id import validate_safe_id
from memory_os.core.write_budget import ArtifactWriteBudget

MAX_CHECKPOINTS = 200
VALID_STATUSES = {"running", "completed", "failed", "aborted"}
VALID_APPROVAL_STATES = {"not_required", "pending", "approved", "rejected"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run_id_prefix(workflow_name: str) -> str:
    chars = []
    for char in workflow_name.strip():
        if char.isalnum() or char in {"-", "_", "."}:
            chars.append(char)
        elif char.isspace():
            chars.append("-")
    prefix = "".join(chars).strip("-._")
    return prefix or "run"


class RunRecordStore:
    """Reads/writes plain-file workflow run records."""

    def __init__(self, config: MemoryOSConfig):
        self.config = config
        self.runs_dir = config.root_dir / "agent_context" / "runs"

    def record_path(self, run_id: str) -> Path:
        validate_safe_id(run_id, "run_id")
        return self.runs_dir / run_id / "record.json"

    @contextmanager
    def _locked(self, run_id: str) -> Iterator[None]:
        """Hold an exclusive interprocess lock for the duration of a read-modify-write.

        Without this, two concurrent checkpoint() calls for the same run_id can
        both load the same record before either saves, silently dropping one
        checkpoint even though both calls report success.
        """
        record_path = self.record_path(run_id)
        record_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = record_path.with_suffix(".lock")
        with open(lock_path, "w", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _load(self, run_id: str) -> Dict[str, Any]:
        path = self.record_path(run_id)
        if not path.exists():
            raise FileNotFoundError(f"No run record for run_id '{run_id}'.")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, record: Dict[str, Any]) -> None:
        path = self.record_path(record["run_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        record["updated_at"] = _now()
        ArtifactWriteBudget(self.config).write_text(path, json.dumps(record, indent=2) + "\n", encoding="utf-8")

    def start(self, workflow_name: str, inputs: Optional[Dict] = None) -> Dict[str, Any]:
        run_id = f"{_run_id_prefix(workflow_name)}-{uuid.uuid4().hex[:8]}"
        now = _now()
        record = {
            "run_id": run_id,
            "workflow_name": workflow_name,
            "status": "running",
            "current_step": "",
            "inputs": dict(inputs or {}),
            "outputs": {},
            "checkpoints": [],
            "resource_budget": {},
            "evidence_links": [],
            "approval_state": "not_required",
            "created_at": now,
            "updated_at": now,
        }
        self._save(record)
        return record

    def status(self, run_id: str) -> Dict[str, Any]:
        return self._load(run_id)

    def checkpoint(self, run_id: str, step: str, output: Any = None) -> Dict[str, Any]:
        with self._locked(run_id):
            record = self._load(run_id)
            checkpoints = list(record.get("checkpoints", []))
            checkpoints.append({"step": step, "output": output, "at": _now()})
            record["checkpoints"] = checkpoints[-MAX_CHECKPOINTS:]
            record["current_step"] = step
            self._save(record)
            return record

    def resume(self, run_id: str) -> Dict[str, Any]:
        record = self._load(run_id)
        status = record.get("status")
        if status in ("completed", "aborted"):
            raise ValueError(f"run '{run_id}' is already {status} and cannot be resumed")
        return record

    def abort(self, run_id: str) -> Dict[str, Any]:
        with self._locked(run_id):
            record = self._load(run_id)
            record["status"] = "aborted"
            self._save(record)
            return record

    def complete(self, run_id: str, outputs: Optional[Dict] = None) -> Dict[str, Any]:
        with self._locked(run_id):
            record = self._load(run_id)
            record["status"] = "completed"
            if outputs is not None:
                existing_outputs = record.get("outputs")
                if isinstance(existing_outputs, dict):
                    merged_outputs = dict(existing_outputs)
                else:
                    merged_outputs = {}
                merged_outputs.update(outputs)
                record["outputs"] = merged_outputs
            self._save(record)
            return record

    def list_runs(self) -> List[Dict[str, Any]]:
        if not self.runs_dir.exists():
            return []

        summaries: List[Dict[str, Any]] = []
        for path in self.runs_dir.glob("*/record.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            summaries.append(
                {
                    "run_id": record.get("run_id", path.parent.name),
                    "workflow_name": record.get("workflow_name", ""),
                    "status": record.get("status", ""),
                    "current_step": record.get("current_step", ""),
                    "updated_at": record.get("updated_at", ""),
                }
            )
        return sorted(summaries, key=lambda item: item.get("updated_at", ""), reverse=True)
