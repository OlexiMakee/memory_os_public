"""Langfuse Observability and Prompt Tracking Exporter for Memory OS.

Exports structured telemetry (tokens, latency, cost, status) and performance
metrics (algorithm_name, duration_ms) to Langfuse compatible targets.
This is an export path only and does not act as primary storage.
"""

from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict

from memory_os.core.config import MemoryOSConfig
from memory_os.core.core import MemoryOS


def is_available() -> bool:
    """Check if the langfuse package is installed and available."""
    try:
        return importlib.util.find_spec("langfuse") is not None
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


class LangfuseExporter:
    """Exporter that processes and pushes telemetry/performance data to Langfuse."""

    def __init__(self, config: MemoryOSConfig):
        self.config = config

    def audit(self) -> Dict[str, Any]:
        """Instant check to determine if the Langfuse SDK is available."""
        return {"available": is_available()}

    def export(self, dry_run: bool = True, sample_rate: float = 1.0) -> Dict[str, Any]:
        """Reads telemetry and performance metrics, samples them deterministically,
        and pushes them to Langfuse if available.
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
                "detail": "langfuse package not installed",
                "would_export_count": would_export_count,
            }

        # Lazily import Langfuse SDK components
        try:
            from langfuse import Langfuse

            # Extract configuration options if defined in config
            langfuse_config = self.config.data.get("langfuse", {})
            public_key = langfuse_config.get("public_key") or os.environ.get("LANGFUSE_PUBLIC_KEY")
            secret_key = langfuse_config.get("secret_key") or os.environ.get("LANGFUSE_SECRET_KEY")
            host = langfuse_config.get("host") or os.environ.get("LANGFUSE_HOST") or os.environ.get("LANGFUSE_BASE_URL")

            kwargs = {}
            if public_key:
                kwargs["public_key"] = public_key
            if secret_key:
                kwargs["secret_key"] = secret_key
            if host:
                kwargs["host"] = host

            # Instantiate client
            langfuse_client = Langfuse(**kwargs)

            # Export telemetry rows
            for row in sampled_telemetry:
                prompt_name = row.get("prompt_name") or "llm_call"

                # Standardize timestamps for Langfuse trace
                created_at_str = row.get("created_at")
                start_time = None
                end_time = None
                if created_at_str:
                    try:
                        t_str = created_at_str
                        if t_str.endswith("Z"):
                            t_str = t_str[:-1] + "+00:00"
                        start_time = datetime.fromisoformat(t_str)
                        latency_ms = int(row.get("latency_ms") or 0)
                        end_time = start_time + timedelta(milliseconds=latency_ms)
                    except Exception:
                        pass

                trace_metadata = {
                    "prompt_version": row.get("prompt_version") or "",
                    "prompt_hash": row.get("prompt_hash") or "",
                    "provider_id": row.get("provider_id") or "",
                    "status": row.get("status") or "",
                    "cached_tokens": int(row.get("cached_tokens") or 0),
                    "latency_ms": int(row.get("latency_ms") or 0),
                }

                trace_kwargs = {
                    "id": f"telemetry-{row['id']}",
                    "name": prompt_name,
                    "metadata": trace_metadata,
                }
                if start_time:
                    trace_kwargs["timestamp"] = start_time

                trace = langfuse_client.trace(**trace_kwargs)

                generation_kwargs = {
                    "name": prompt_name,
                    "model": row.get("model_id") or "",
                    "usage": {
                        "input": int(row.get("input_tokens") or 0),
                        "output": int(row.get("output_tokens") or 0),
                        "total": int(row.get("input_tokens") or 0) + int(row.get("output_tokens") or 0)
                    },
                    "cost": float(row.get("cost") or 0.0),
                    "input": "[Telemetry Export - Raw payload excluded]",
                    "output": "[Telemetry Export - Raw payload excluded]",
                }
                if start_time:
                    generation_kwargs["start_time"] = start_time

                generation = trace.generation(**generation_kwargs)

                if end_time:
                    generation.end(end_time=end_time)
                else:
                    generation.end()

            # Export performance rows
            for row in sampled_performance:
                algorithm_name = row.get("algorithm_name") or "algorithm_run"
                duration_ms = int(row.get("duration_ms") or 0)

                # Standardize timestamps for performance span
                created_at_str = row.get("created_at")
                start_time = None
                end_time = None
                if created_at_str:
                    try:
                        t_str = created_at_str
                        if t_str.endswith("Z"):
                            t_str = t_str[:-1] + "+00:00"
                        start_time = datetime.fromisoformat(t_str)
                        end_time = start_time + timedelta(milliseconds=duration_ms)
                    except Exception:
                        pass

                meta_dict = {}
                raw_metadata = row.get("metadata")
                if raw_metadata:
                    try:
                        meta_dict = json.loads(raw_metadata)
                        if not isinstance(meta_dict, dict):
                            meta_dict = {"raw_metadata": str(raw_metadata)}
                    except Exception:
                        meta_dict = {"raw_metadata": str(raw_metadata)}

                trace_kwargs = {
                    "id": f"performance-{row['id']}",
                    "name": algorithm_name,
                    "metadata": meta_dict,
                }
                if start_time:
                    trace_kwargs["timestamp"] = start_time

                trace = langfuse_client.trace(**trace_kwargs)

                span_kwargs = {
                    "name": algorithm_name,
                    "metadata": meta_dict,
                }
                if start_time:
                    span_kwargs["start_time"] = start_time

                span = trace.span(**span_kwargs)

                if end_time:
                    span.end(end_time=end_time)
                else:
                    span.end()

            # Flush the SDK buffer to ensure everything is sent
            langfuse_client.flush()

            return {
                "ok": True,
                "dry_run": False,
                "exported_count": would_export_count,
                "available": True,
            }

        except Exception as exc:
            return {"ok": False, "detail": f"export failed: {exc}"}
