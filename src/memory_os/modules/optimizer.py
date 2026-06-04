from typing import Dict, Any, List, Optional
from memory_os.core.core import MemoryOS

class RouteOptimizer:
    """Analyzes execution metrics and recommends optimal models/configurations."""

    def __init__(self, memory_os: MemoryOS):
        self.memory_os = memory_os

    def analyze_metrics(self, prompt_name: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Query average latency, cost, and cache ratio for each model/version."""
        conn = self.memory_os.get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT 
                    prompt_version,
                    provider_id,
                    model_id,
                    COUNT(*) as run_count,
                    AVG(latency_ms) as avg_latency_ms,
                    AVG(cost) as avg_cost,
                    AVG(CAST(cached_tokens AS REAL) / NULLIF(input_tokens, 0)) as avg_cache_ratio,
                    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as error_rate
                FROM memory_os_telemetry
                WHERE prompt_name = ?
                GROUP BY prompt_version, provider_id, model_id
                ORDER BY avg_cost ASC, avg_latency_ms ASC
                LIMIT ?
                """,
                (prompt_name, limit)
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def recommend_route(self, prompt_name: str, max_cost_cap: float = 0.05, max_error_threshold: float = 0.1) -> Optional[Dict[str, Any]]:
        """Suggest the best provider/model based on lowest cost and latency meeting thresholds."""
        stats = self.analyze_metrics(prompt_name)
        if not stats:
            return None

        # Filter out options exceeding error rate threshold
        candidates = [s for s in stats if s["error_rate"] <= max_error_threshold]
        
        # If cost caps are set, filter by cost
        if max_cost_cap > 0:
            candidates = [c for c in candidates if c["avg_cost"] <= max_cost_cap]

        if not candidates:
            # Fallback to absolute lowest error candidate if all exceed thresholds
            candidates = sorted(stats, key=lambda x: (x["error_rate"], x["avg_cost"], x["avg_latency_ms"]))

        return candidates[0] if candidates else None
