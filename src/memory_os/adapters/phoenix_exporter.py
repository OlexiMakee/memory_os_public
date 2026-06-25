"""Phoenix Observability Exporter for Memory OS.

Exports structured telemetry (tokens, latency, cost, status) and performance
metrics (algorithm_name, duration_ms) to Arize Phoenix / OpenInference compatible targets.
This is an export path only and does not act as primary storage.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from typing import Any, Dict, List, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.core import MemoryOS


def is_available() -> bool:
    """Check if Arize Phoenix is installed and available."""
    try:
        return importlib.util.find_spec("phoenix") is not None
    except Exception:
        return False


def _is_sampled(row_id: int, sample_rate: float) -> bool:
    """Apply a deterministic sample rate using a simple modulo on row ID."""
    if sample_rate >= 1.0:
        return True
    if sample_rate <= 0.0:
        return False
    # High-resolution modulo to handle floats with precision
    return (row_id % 10000) < (sample_rate * 10000)


class PhoenixExporter:
    """Exporter that processes and pushes telemetry/performance data to Arize Phoenix."""

    def __init__(self, config: MemoryOSConfig):
        self.config = config

    def audit(self) -> Dict[str, Any]:
        """Instant check to determine if the Phoenix SDK is available."""
        return {"available": is_available()}

    def export(self, dry_run: bool = True, sample_rate: float = 1.0) -> Dict[str, Any]:
        """Reads telemetry and performance metrics, samples them deterministically,

        and sends traces to Phoenix using OpenInference conventions if installed.
        """
        conn = None
        try:
            mos = MemoryOS(self.config)
            conn = mos.get_connection()
            cursor = conn.cursor()

            # Read all rows from telemetry
            cursor.execute(
                """
                SELECT id, prompt_name, prompt_version, prompt_hash, provider_id, model_id,
                       input_tokens, output_tokens, cached_tokens, latency_ms, cost, status, created_at
                FROM memory_os_telemetry
                """
            )
            telemetry_rows = [dict(row) for row in cursor.fetchall()]

            # Read all rows from performance
            cursor.execute(
                """
                SELECT id, algorithm_name, duration_ms, metadata, created_at
                FROM memory_os_performance
                """
            )
            performance_rows = [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            return {"ok": False, "detail": f"Database read failed: {e}"}
        finally:
            if conn is not None:
                conn.close()

        # Apply deterministic sample_rate filter
        sampled_telemetry = [row for row in telemetry_rows if _is_sampled(row["id"], sample_rate)]
        sampled_performance = [row for row in performance_rows if _is_sampled(row["id"], sample_rate)]
        would_export_count = len(sampled_telemetry) + len(sampled_performance)

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "would_export_count": would_export_count,
                "available": is_available(),
            }

        # If not dry_run, check if SDK is available
        if not is_available():
            return {
                "ok": False,
                "detail": "phoenix package not installed",
                "would_export_count": would_export_count,
            }

        # Lazily import phoenix and OTel trace SDK
        try:
            from opentelemetry import trace
            from phoenix.otel import register

            # Setup trace provider via Phoenix
            tracer_provider = register()
            tracer = tracer_provider.get_tracer("memory_os.phoenix_exporter")

            # Build trace spans for telemetry
            for row in sampled_telemetry:
                prompt_name = row.get("prompt_name") or "llm_call"
                status = row.get("status") or ""

                # Standardize attributes with OpenInference conventions
                attrs = {
                    "prompt_name": prompt_name,
                    "prompt_version": row.get("prompt_version") or "",
                    "prompt_hash": row.get("prompt_hash") or "",
                    "provider_id": row.get("provider_id") or "",
                    "model_id": row.get("model_id") or "",
                    "input_tokens": int(row.get("input_tokens") or 0),
                    "output_tokens": int(row.get("output_tokens") or 0),
                    "cached_tokens": int(row.get("cached_tokens") or 0),
                    "latency_ms": int(row.get("latency_ms") or 0),
                    "cost": float(row.get("cost") or 0.0),
                    "status": status,
                    # OpenInference span conventions for Phoenix dashboard
                    "openinference.span.kind": "LLM",
                    "llm.model_name": row.get("model_id") or "",
                    "llm.provider": row.get("provider_id") or "",
                    "llm.token_count.prompt": int(row.get("input_tokens") or 0),
                    "llm.token_count.completion": int(row.get("output_tokens") or 0),
                    "llm.token_count.total": int(row.get("input_tokens") or 0) + int(row.get("output_tokens") or 0),
                    "llm.cost.total": float(row.get("cost") or 0.0),
                }

                span = tracer.start_span(name=prompt_name, attributes=attrs)
                if status == "success":
                    span.set_status(trace.StatusCode.OK)
                else:
                    span.set_status(trace.StatusCode.ERROR, description=status)
                span.end()

            # Build trace spans for performance
            for row in sampled_performance:
                algorithm_name = row.get("algorithm_name") or "algorithm_run"
                duration_ms = int(row.get("duration_ms") or 0)

                perf_attrs = {
                    "algorithm_name": algorithm_name,
                    "duration_ms": duration_ms,
                    "openinference.span.kind": "CHAIN",
                }

                span = tracer.start_span(name=algorithm_name, attributes=perf_attrs)
                span.set_status(trace.StatusCode.OK)
                span.end()

            # Clean up / flush if possible
            if hasattr(tracer_provider, "force_flush"):
                try:
                    tracer_provider.force_flush()
                except Exception:
                    pass

            return {
                "ok": True,
                "dry_run": False,
                "exported_count": would_export_count,
                "available": True,
            }

        except Exception as exc:
            return {"ok": False, "detail": f"export failed: {exc}"}
