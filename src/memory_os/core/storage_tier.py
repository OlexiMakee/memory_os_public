"""
StorageTierAdvisor — measures actual local resource constraints and
recommends whether SQLite (tier 1) is still sufficient, or whether
escalating to a local Postgres (tier 2) or a hosted cloud Postgres (tier 3)
is warranted.

Mirrors the local-first-then-escalate pattern already used for LLM
providers in core/llm_service.py (Ollama -> free cloud -> paid cloud):
try the cheapest local option, only point further when it is *measurably*
insufficient. This module never migrates or connects to anything beyond
the existing local SQLite db — it only measures and recommends. Standing
up a new backend is a deliberate, user-driven decision, not something this
advisor should ever do silently.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.disk_guard import DiskGuard

# Conservative, documented thresholds. SQLite's own ceiling is in the TBs —
# these don't mark "SQLite breaks," they mark "this project's actual
# workload (single local agent, occasional swarm bursts) has outgrown the
# zero-config default," which is a much lower bar.
DEFAULT_TIER_THRESHOLDS: Dict[str, float] = {
    "db_mb_tier2": 512,
    "wal_mb_tier2": 64,
    "active_leases_tier2": 4,
}


@dataclass
class StorageTierAssessment:
    tier: str  # "sqlite" | "local_postgres" | "cloud_postgres"
    reasons: List[str] = field(default_factory=list)
    signals: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"tier": self.tier, "reasons": self.reasons, "signals": self.signals}


class StorageTierAdvisor:
    """Read-only. Call assess() to get a tier recommendation; nothing here
    creates a connection, installs anything, or moves data."""

    def __init__(self, config: MemoryOSConfig, thresholds: Optional[Dict[str, float]] = None):
        self.config = config
        self.thresholds = {**DEFAULT_TIER_THRESHOLDS, **(thresholds or {})}

    def _active_swarm_leases(self) -> int:
        leases_path = self.config.root_dir / "data" / "swarm_leases.json"
        if not leases_path.exists():
            return 0
        try:
            data = json.loads(leases_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return 0
        return len(data) if isinstance(data, dict) else 0

    @staticmethod
    def _local_postgres_available() -> bool:
        return shutil.which("psql") is not None

    def assess(self) -> StorageTierAssessment:
        snapshot = DiskGuard(self.config).snapshot()
        active_leases = self._active_swarm_leases()

        signals: Dict[str, Any] = {
            "db_mb": snapshot.sqlite.db_mb,
            "wal_mb": snapshot.sqlite.wal_mb,
            "events_jsonl_mb": snapshot.events_jsonl_mb,
            "events_soft_limit_mb": snapshot.events_soft_limit_mb,
            "events_soft_limit_exceeded": snapshot.events_soft_limit_exceeded,
            "patches_jsonl_mb": snapshot.patches_jsonl_mb,
            "patches_soft_limit_mb": snapshot.patches_soft_limit_mb,
            "patches_soft_limit_exceeded": snapshot.patches_soft_limit_exceeded,
            "free_disk_mb": snapshot.free_disk_mb,
            "active_swarm_leases": active_leases,
            "local_postgres_available": self._local_postgres_available(),
        }

        reasons: List[str] = []
        tier = "sqlite"

        if snapshot.low_disk:
            reasons.append(
                f"free disk ({snapshot.free_disk_mb} MB) is below the configured minimum — "
                "fix disk space before considering any heavier backend."
            )

        if snapshot.sqlite.db_mb > self.thresholds["db_mb_tier2"]:
            reasons.append(
                f"memory_os.db is {snapshot.sqlite.db_mb} MB, above the tier-2 watch "
                f"threshold ({self.thresholds['db_mb_tier2']} MB)."
            )
            tier = "local_postgres"

        if snapshot.sqlite.wal_mb > self.thresholds["wal_mb_tier2"]:
            reasons.append(
                f"WAL is {snapshot.sqlite.wal_mb} MB — sustained WAL growth usually means "
                "writes aren't draining (write contention), not just data size."
            )
            tier = "local_postgres"

        if snapshot.events_soft_limit_exceeded:
            reasons.append(
                f"events.jsonl is {snapshot.events_jsonl_mb} MB, above the soft audit-log "
                f"threshold ({snapshot.events_soft_limit_mb} MB); plan explicit archive rotation."
            )

        if snapshot.patches_soft_limit_exceeded:
            reasons.append(
                f"patches.jsonl is {snapshot.patches_jsonl_mb} MB, above the soft patch-audit "
                f"threshold ({snapshot.patches_soft_limit_mb} MB); run bounded archive compaction to keep only the latest state per patch hot."
            )

        if active_leases > self.thresholds["active_leases_tier2"]:
            reasons.append(
                f"{active_leases} swarm tasks currently hold file leases — concurrent "
                "writers are exactly where SQLite's single-writer WAL lock starts to queue."
            )
            tier = "local_postgres"

        if tier == "local_postgres" and not signals["local_postgres_available"]:
            reasons.append(
                "no local 'psql' found — installing local Postgres is the first option; "
                "a free-tier hosted Postgres (e.g. Neon) is the fallback if you'd rather "
                "not run a local server."
            )
            tier = "cloud_postgres"

        if not reasons:
            reasons.append(
                "db size, WAL growth, and concurrent swarm leases are all within "
                "comfortable SQLite range — no reason to add a server."
            )

        return StorageTierAssessment(tier=tier, reasons=reasons, signals=signals)
