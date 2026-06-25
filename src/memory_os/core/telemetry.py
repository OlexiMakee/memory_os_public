from typing import Optional

from memory_os.core.logger import get_logger
logger = get_logger(__name__)
from memory_os.core.core import MemoryOS
from memory_os.core.config import MemoryOSConfig
from memory_os.core.telemetry_policy import TelemetryPolicy

class TelemetryRecorder:
    """Logs LLM execution metrics (tokens, latency, cost, and statuses)."""

    def __init__(self, memory_os: MemoryOS, config: Optional[MemoryOSConfig] = None):
        self.memory_os = memory_os
        self.policy = TelemetryPolicy(config or MemoryOSConfig(), db_path=memory_os.db_path)

    def _enforce_bounds(self, conn, table: str) -> None:
        """Self-heal a table that has drifted over its row/DB-size cap before writing more.

        Prune is best-effort (e.g. pruning the telemetry table can't shrink a DB
        that's over cap because of unrelated tables). assert_writable() re-checks
        after pruning and actually blocks the write via TelemetryBudgetExceeded
        if the cap still holds, instead of writing anyway.
        """
        if not self.policy.enabled:
            return
        budget = self.policy.table_budget(conn, table)
        if budget.over_cap or self.policy.db_over_cap():
            self.policy.prune(conn, table)
        self.policy.assert_writable(conn, table)

    def record_run(
        self,
        prompt_name: str,
        prompt_version: str,
        prompt_hash: str,
        provider_id: str,
        model_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        latency_ms: int = 0,
        cost: float = 0.0,
        status: str = "success"
    ) -> bool:
        """Record a single LLM execution transaction in SQLite."""
        try:
            conn = self.memory_os.get_connection()
            try:
                self._enforce_bounds(conn, "memory_os_telemetry")
                conn.execute(
                    """
                    INSERT INTO memory_os_telemetry (
                        prompt_name, prompt_version, prompt_hash, provider_id, model_id,
                        input_tokens, output_tokens, cached_tokens, latency_ms, cost, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prompt_name,
                        prompt_version,
                        prompt_hash,
                        provider_id,
                        model_id,
                        int(input_tokens),
                        int(output_tokens),
                        int(cached_tokens),
                        int(latency_ms),
                        float(cost),
                        status
                    )
                )
                conn.commit()
                return True
            finally:
                conn.close()
        except Exception as e:
            logger.info(f"[TelemetryRecorder] Logging failed: {e}")
            return False

    def record_performance(self, algorithm_name: str, duration_ms: int, metadata: str = "{}") -> bool:
        """Record the performance of an internal algorithm."""
        try:
            conn = self.memory_os.get_connection()
            try:
                self._enforce_bounds(conn, "memory_os_performance")
                conn.execute(
                    """
                    INSERT INTO memory_os_performance (
                        algorithm_name, duration_ms, metadata
                    ) VALUES (?, ?, ?)
                    """,
                    (algorithm_name, int(duration_ms), metadata)
                )
                conn.commit()
                return True
            finally:
                conn.close()
        except Exception as e:
            logger.info(f"[TelemetryRecorder] Performance logging failed: {e}")
            return False
