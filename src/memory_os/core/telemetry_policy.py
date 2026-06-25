"""
TelemetryPolicy — bounded-growth guard for memory_os_telemetry / memory_os_performance.

Enforces row caps, DB-size caps, and retention TTL so the shared SQLite DB
cannot grow unbounded the way Codex's TRACE logging did. The recorder already
stores only structured metrics (tokens, latency, cost, status) rather than
raw payloads — this module adds the missing caps, not raw-payload redaction.
See DEV_STRATEGY.md Stage 2.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from memory_os.core.config import MemoryOSConfig
from memory_os.core.exceptions import TelemetryBudgetExceeded

TELEMETRY_TABLES: Sequence[str] = ("memory_os_telemetry", "memory_os_performance")

DEFAULT_TELEMETRY_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "raw_payloads": False,
    "min_level": "INFO",
    "max_db_mb": 256,
    "max_rows_per_table": 100000,
    "retention_days": 30,
    "max_writes_per_minute": 120,
}

WARN_THRESHOLD = 0.8


@dataclass
class TableBudget:
    table: str
    row_count: int
    max_rows: int
    over_cap: bool
    warn_cap: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table": self.table,
            "row_count": self.row_count,
            "max_rows": self.max_rows,
            "over_cap": self.over_cap,
            "warn_cap": self.warn_cap,
        }


class TelemetryPolicy:
    """Bounded-growth policy for telemetry/performance tables in the shared SQLite DB."""

    def __init__(self, config: MemoryOSConfig, db_path: Optional[Path] = None):
        self.config = config
        self.db_path = Path(db_path) if db_path is not None else config.db_path
        self.settings: Dict[str, Any] = {
            **DEFAULT_TELEMETRY_CONFIG,
            **config.data.get("telemetry", {}),
        }

    @property
    def enabled(self) -> bool:
        return bool(self.settings["enabled"])

    def db_size_mb(self) -> float:
        if not self.db_path.exists():
            return 0.0
        return round(self.db_path.stat().st_size / (1024 * 1024), 3)

    @staticmethod
    def _row_count(conn: sqlite3.Connection, table: str) -> int:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def table_budget(self, conn: sqlite3.Connection, table: str) -> TableBudget:
        max_rows = int(self.settings["max_rows_per_table"])
        count = self._row_count(conn, table)
        return TableBudget(
            table=table,
            row_count=count,
            max_rows=max_rows,
            over_cap=count > max_rows,
            warn_cap=count >= WARN_THRESHOLD * max_rows,
        )

    def db_over_cap(self) -> bool:
        return self.db_size_mb() > float(self.settings["max_db_mb"])

    def db_warn_cap(self) -> bool:
        return self.db_size_mb() >= WARN_THRESHOLD * float(self.settings["max_db_mb"])

    def assert_writable(self, conn: sqlite3.Connection, table: str) -> None:
        """Raise TelemetryBudgetExceeded if a hard cap blocks further writes to `table`."""
        if not self.enabled:
            raise TelemetryBudgetExceeded("telemetry is disabled by config")
        budget = self.table_budget(conn, table)
        if budget.over_cap:
            raise TelemetryBudgetExceeded(
                f"{table} has {budget.row_count} rows (cap {budget.max_rows}); prune before writing more"
            )
        if self.db_over_cap():
            raise TelemetryBudgetExceeded(
                f"telemetry DB is {self.db_size_mb()} MB (cap {self.settings['max_db_mb']} MB); prune before writing more"
            )

    def prune(self, conn: sqlite3.Connection, table: str) -> Dict[str, int]:
        """Delete rows older than retention_days, then trim oldest rows beyond max_rows_per_table."""
        retention_days = int(self.settings["retention_days"])
        max_rows = int(self.settings["max_rows_per_table"])

        cur = conn.execute(
            f"DELETE FROM {table} WHERE created_at < datetime('now', ?)",
            (f"-{retention_days} days",),
        )
        deleted_by_retention = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

        remaining = self._row_count(conn, table)
        deleted_by_cap = 0
        if remaining > max_rows:
            excess = remaining - max_rows
            conn.execute(
                f"DELETE FROM {table} WHERE id IN "
                f"(SELECT id FROM {table} ORDER BY id ASC LIMIT ?)",
                (excess,),
            )
            deleted_by_cap = excess

        conn.commit()

        total_deleted = deleted_by_retention + deleted_by_cap
        if total_deleted > 0 and self.db_over_cap():
            conn.execute("VACUUM")

        return {"deleted_by_retention": deleted_by_retention, "deleted_by_cap": deleted_by_cap}

    def audit(self, conn: sqlite3.Connection, tables: Sequence[str] = TELEMETRY_TABLES) -> Dict[str, Any]:
        budgets = [self.table_budget(conn, t) for t in tables]
        return {
            "enabled": self.enabled,
            "db_mb": self.db_size_mb(),
            "max_db_mb": float(self.settings["max_db_mb"]),
            "db_over_cap": self.db_over_cap(),
            "db_warn_cap": self.db_warn_cap(),
            "retention_days": int(self.settings["retention_days"]),
            "tables": [b.to_dict() for b in budgets],
        }
