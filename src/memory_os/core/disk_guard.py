"""
DiskGuard — measures disk and SQLite file health for Memory OS.

Read-only except for one small bounded state file (data/disk_guard_state.json)
used to estimate write-rate between snapshots. Knows nothing about LLM
providers, compaction, or UI — see DEV_STRATEGY.md Stage 1.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from memory_os.core.config import MemoryOSConfig

DEFAULT_RESOURCES_CONFIG: Dict[str, float] = {
    "min_free_disk_mb": 2048,
    "max_sqlite_db_mb": 256,
    "max_sqlite_wal_mb": 64,
    "max_jsonl_total_mb": 128,
    "max_observed_growth_mb_per_hour": 128,
}

DEFAULT_MEMORY_CONFIG: Dict[str, float] = {
    "events_soft_limit_mb": 16,
    "patches_soft_limit_mb": 256,
}


@dataclass
class SQLiteFileHealth:
    db_path: str
    db_mb: float
    wal_mb: float
    shm_mb: float
    exceeds_max_db: bool
    exceeds_max_wal: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "db_path": self.db_path,
            "db_mb": self.db_mb,
            "wal_mb": self.wal_mb,
            "shm_mb": self.shm_mb,
            "exceeds_max_db": self.exceeds_max_db,
            "exceeds_max_wal": self.exceeds_max_wal,
        }


@dataclass
class DiskSnapshot:
    timestamp: float
    free_disk_mb: float
    jsonl_total_mb: float
    events_jsonl_mb: float
    events_soft_limit_mb: float
    patches_jsonl_mb: float
    patches_soft_limit_mb: float
    sqlite: SQLiteFileHealth
    growth_mb_per_hour: Optional[float]
    low_disk: bool
    exceeds_max_jsonl: bool
    events_soft_limit_exceeded: bool
    patches_soft_limit_exceeded: bool
    growth_alert: bool

    @property
    def level(self) -> str:
        """'cool' | 'hot' — any configured threshold breached means 'hot'."""
        if (
            self.low_disk
            or self.sqlite.exceeds_max_db
            or self.sqlite.exceeds_max_wal
            or self.exceeds_max_jsonl
            or self.events_soft_limit_exceeded
            or self.patches_soft_limit_exceeded
            or self.growth_alert
        ):
            return "hot"
        return "cool"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "free_disk_mb": self.free_disk_mb,
            "jsonl_total_mb": self.jsonl_total_mb,
            "events_jsonl_mb": self.events_jsonl_mb,
            "events_soft_limit_mb": self.events_soft_limit_mb,
            "patches_jsonl_mb": self.patches_jsonl_mb,
            "patches_soft_limit_mb": self.patches_soft_limit_mb,
            "sqlite": self.sqlite.to_dict(),
            "growth_mb_per_hour": self.growth_mb_per_hour,
            "low_disk": self.low_disk,
            "exceeds_max_jsonl": self.exceeds_max_jsonl,
            "events_soft_limit_exceeded": self.events_soft_limit_exceeded,
            "patches_soft_limit_exceeded": self.patches_soft_limit_exceeded,
            "growth_alert": self.growth_alert,
            "level": self.level,
        }


class DiskGuard:
    """Snapshots free disk space, SQLite DB/WAL size, and JSONL size against configured budgets."""

    def __init__(self, config: MemoryOSConfig):
        self.config = config
        self.settings: Dict[str, float] = {
            **DEFAULT_RESOURCES_CONFIG,
            **config.data.get("resources", {}),
        }
        self.memory_settings: Dict[str, float] = {
            **DEFAULT_MEMORY_CONFIG,
            **config.data.get("memory", {}),
        }
        self.state_file = config.root_dir / "data" / "disk_guard_state.json"

    @staticmethod
    def _mb(path: Path) -> float:
        if not path.exists():
            return 0.0
        return round(path.stat().st_size / (1024 * 1024), 3)

    def _sqlite_health(self) -> SQLiteFileHealth:
        db_path = self.config.db_path
        db_mb = self._mb(db_path)
        wal_mb = self._mb(Path(str(db_path) + "-wal"))
        shm_mb = self._mb(Path(str(db_path) + "-shm"))
        return SQLiteFileHealth(
            db_path=str(db_path),
            db_mb=db_mb,
            wal_mb=wal_mb,
            shm_mb=shm_mb,
            exceeds_max_db=db_mb > self.settings["max_sqlite_db_mb"],
            exceeds_max_wal=wal_mb > self.settings["max_sqlite_wal_mb"],
        )

    def _jsonl_total_mb(self) -> float:
        memory_dir = self.config.memory_dir
        if not memory_dir.exists():
            return 0.0
        total = 0.0
        for p in memory_dir.glob("*.jsonl"):
            try:
                total += p.stat().st_size
            except FileNotFoundError:
                pass
        return round(total / (1024 * 1024), 3)

    def _events_jsonl_mb(self) -> float:
        return self._mb(self.config.memory_dir / "events.jsonl")

    def _patches_jsonl_mb(self) -> float:
        return self._mb(self.config.memory_dir / "patches.jsonl")

    def _free_disk_mb(self) -> float:
        try:
            usage = shutil.disk_usage(self.config.root_dir)
            return round(usage.free / (1024 * 1024), 1)
        except (FileNotFoundError, OSError):
            return 0.0

    def _load_previous(self) -> Optional[Dict[str, Any]]:
        if not self.state_file.exists():
            return None
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _save_state(self, timestamp: float, tracked_mb: float, growth_mb_per_hour: Optional[float] = None) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.state_file.write_text(
                json.dumps({
                    "timestamp": timestamp,
                    "tracked_mb": tracked_mb,
                    "growth_mb_per_hour": growth_mb_per_hour
                }),
                encoding="utf-8",
            )
        except OSError:
            pass

    def snapshot(self) -> DiskSnapshot:
        now = time.time()
        sqlite = self._sqlite_health()
        jsonl_mb = self._jsonl_total_mb()
        events_jsonl_mb = self._events_jsonl_mb()
        patches_jsonl_mb = self._patches_jsonl_mb()
        tracked_mb = sqlite.db_mb + sqlite.wal_mb + jsonl_mb

        growth_mb_per_hour = None
        previous = self._load_previous()
        if previous:
            elapsed_seconds = now - previous["timestamp"]
            if elapsed_seconds < 60:
                growth_mb_per_hour = previous.get("growth_mb_per_hour")
            else:
                elapsed_hours = elapsed_seconds / 3600
                if elapsed_hours > 0:
                    growth_mb_per_hour = round((tracked_mb - previous["tracked_mb"]) / elapsed_hours, 3)

        free_disk_mb = self._free_disk_mb()
        low_disk = free_disk_mb < self.settings["min_free_disk_mb"]
        exceeds_max_jsonl = jsonl_mb > self.settings["max_jsonl_total_mb"]
        events_soft_limit_mb = self.memory_settings["events_soft_limit_mb"]
        patches_soft_limit_mb = self.memory_settings["patches_soft_limit_mb"]
        events_soft_limit_exceeded = events_jsonl_mb > events_soft_limit_mb
        patches_soft_limit_exceeded = patches_jsonl_mb > patches_soft_limit_mb
        growth_alert = bool(
            growth_mb_per_hour is not None
            and growth_mb_per_hour > self.settings["max_observed_growth_mb_per_hour"]
        )

        result = DiskSnapshot(
            timestamp=now,
            free_disk_mb=free_disk_mb,
            jsonl_total_mb=jsonl_mb,
            events_jsonl_mb=events_jsonl_mb,
            events_soft_limit_mb=events_soft_limit_mb,
            patches_jsonl_mb=patches_jsonl_mb,
            patches_soft_limit_mb=patches_soft_limit_mb,
            sqlite=sqlite,
            growth_mb_per_hour=growth_mb_per_hour,
            low_disk=low_disk,
            exceeds_max_jsonl=exceeds_max_jsonl,
            events_soft_limit_exceeded=events_soft_limit_exceeded,
            patches_soft_limit_exceeded=patches_soft_limit_exceeded,
            growth_alert=growth_alert,
        )
        self._save_state(now, tracked_mb, growth_mb_per_hour)
        return result

    def compact_patches(self, dry_run: bool = False) -> Dict[str, Any]:
        """Archive superseded patch rows and externalize rollback snapshots from the hot log."""
        patches_path = self.config.memory_dir / "patches.jsonl"
        if not patches_path.exists():
            return {"ok": True, "dry_run": dry_run, "action": "patch_archive", "detail": "patches.jsonl missing"}

        records = []
        for idx, line in enumerate(patches_path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            record["_line_idx"] = idx
            records.append(record)

        latest_line_by_id: Dict[str, int] = {}
        for record in records:
            patch_id = str(record.get("id", "")).strip()
            if patch_id:
                latest_line_by_id[patch_id] = int(record["_line_idx"])

        keep_lines = set(latest_line_by_id.values())
        kept = [record for record in records if int(record["_line_idx"]) in keep_lines]
        archived = [record for record in records if int(record["_line_idx"]) not in keep_lines]
        rollback_archive_candidates = []
        rollback_archive_ids = set()
        keep_payload = []
        for record in kept:
            clean = {k: v for k, v in record.items() if k != "_line_idx"}
            payload = clean.get("payload")
            if not isinstance(payload, dict):
                keep_payload.append(clean)
                continue
            rollback = payload.get("_rollback")
            if not isinstance(rollback, dict):
                keep_payload.append(clean)
                continue
            payload = dict(payload)
            payload.pop("_rollback", None)
            patch_id = str(clean.get("id", ""))
            rollback_archive_candidates.append({
                "patch_id": patch_id,
                "rollback": rollback,
            })
            rollback_archive_ids.add(patch_id)
            clean["payload"] = payload
            keep_payload.append(clean)
        result = {
            "ok": True,
            "dry_run": dry_run,
            "action": "patch_archive",
            "before_records": len(records),
            "kept_records": len(keep_payload),
            "archived_records": len(archived),
            "rollback_archived_records": len(rollback_archive_candidates),
        }
        if dry_run or (not archived and not rollback_archive_candidates):
            return result

        archive_dir = self.config.memory_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"patches-{int(time.time())}.jsonl"
        archive_payload = [{k: v for k, v in record.items() if k != "_line_idx"} for record in archived]
        if archive_payload:
            archive_path.write_text(
                "\n".join(json.dumps(record, ensure_ascii=False) for record in archive_payload) + "\n",
                encoding="utf-8",
            )
            result["archive_path"] = str(archive_path)
        if rollback_archive_candidates:
            rollback_archive_path = archive_dir / f"patch-rollbacks-{int(time.time())}.jsonl"
            rollback_archive_path.write_text(
                "\n".join(json.dumps(record, ensure_ascii=False) for record in rollback_archive_candidates) + "\n",
                encoding="utf-8",
            )
            rollback_relpath = rollback_archive_path.relative_to(self.config.root_dir)
            for record in keep_payload:
                payload = record.get("payload")
                if not isinstance(payload, dict) or "_rollback" in payload:
                    continue
                if str(record.get("id", "")) not in rollback_archive_ids:
                    continue
                payload["_rollback_archived"] = True
                payload["_rollback_archive"] = str(rollback_relpath)
            result["rollback_archive_path"] = str(rollback_archive_path)
        patches_path.write_text(
            "\n".join(json.dumps(record, ensure_ascii=False) for record in keep_payload) + "\n",
            encoding="utf-8",
        )
        return result

    def compact(self, dry_run: bool = False) -> Dict[str, Any]:
        """Run bounded local resource compaction actions."""
        patch_archive = self.compact_patches(dry_run=dry_run)
        return {
            "ok": bool(patch_archive.get("ok")),
            "dry_run": dry_run,
            "patch_archive": patch_archive,
            "snapshot": self.snapshot().to_dict(),
        }
