"""OpenTelemetry Exporter for Memory OS.

Exports structured telemetry (tokens, latency, cost, status) and performance
metrics (algorithm_name, duration_ms) to OpenTelemetry compatible targets.
This is an export path only and does not act as primary storage.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from typing import Any, Dict, List, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.core import MemoryOS


def is_available() -> bool:
    """Check if OpenTelemetry SDK is installed and available."""
    try:
        return importlib.util.find_spec("opentelemetry.sdk") is not None
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


class OtelExporter:
    """Exporter that processes and pushes telemetry/performance data to OpenTelemetry."""

    def __init__(self, config: MemoryOSConfig):
        self.config = config

    def audit(self) -> Dict[str, Any]:
        """Instant check to determine if the OpenTelemetry SDK is available."""
        return {"available": is_available()}

    def export(self, dry_run: bool = True, sample_rate: float = 1.0) -> Dict[str, Any]:
        """Reads telemetry and performance metrics, samples them deterministically,

        and builds OpenTelemetry spans and metrics if SDK is installed.
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
                "detail": "opentelemetry sdk not installed",
                "would_export_count": would_export_count,
            }

        # Lazily import OpenTelemetry SDK components
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import InMemoryMetricReader

            # Setup trace pipeline in-memory
            trace_exporter = InMemorySpanExporter()
            span_processor = SimpleSpanProcessor(trace_exporter)
            tracer_provider = TracerProvider()
            tracer_provider.add_span_processor(span_processor)
            tracer = tracer_provider.get_tracer("memory_os.otel_exporter")

            # Setup metric pipeline in-memory
            metric_reader = InMemoryMetricReader()
            meter_provider = MeterProvider(metric_readers=[metric_reader])
            meter = meter_provider.get_meter("memory_os.otel_exporter")

            # Initialize metrics instruments
            input_tokens_counter = meter.create_counter(
                "memory_os.telemetry.input_tokens",
                description="Total LLM input tokens"
            )
            output_tokens_counter = meter.create_counter(
                "memory_os.telemetry.output_tokens",
                description="Total LLM output tokens"
            )
            cached_tokens_counter = meter.create_counter(
                "memory_os.telemetry.cached_tokens",
                description="Total LLM cached tokens"
            )
            latency_histogram = meter.create_histogram(
                "memory_os.telemetry.latency_ms",
                description="LLM execution latency in milliseconds"
            )
            cost_counter = meter.create_counter(
                "memory_os.telemetry.cost",
                description="Total LLM call cost"
            )
            duration_histogram = meter.create_histogram(
                "memory_os.performance.duration_ms",
                description="Algorithm duration in milliseconds"
            )

            # Build trace spans and metric records for telemetry
            for row in sampled_telemetry:
                prompt_name = row.get("prompt_name") or "llm_call"

                # Standardize structures fields per DEV_STRATEGY.md
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
                    "status": row.get("status") or "",
                }

                span = tracer.start_span(name=prompt_name, attributes=attrs)
                if attrs["status"] == "success":
                    span.set_status(trace.StatusCode.OK)
                else:
                    span.set_status(trace.StatusCode.ERROR, description=attrs["status"])
                span.end()

                metric_attrs = {
                    "prompt_name": prompt_name,
                    "model_id": attrs["model_id"],
                    "status": attrs["status"],
                }
                input_tokens_counter.add(attrs["input_tokens"], metric_attrs)
                output_tokens_counter.add(attrs["output_tokens"], metric_attrs)
                cached_tokens_counter.add(attrs["cached_tokens"], metric_attrs)
                cost_counter.add(attrs["cost"], metric_attrs)
                latency_histogram.record(attrs["latency_ms"], metric_attrs)

            # Build trace spans and metric records for performance
            for row in sampled_performance:
                algorithm_name = row.get("algorithm_name") or "algorithm_run"
                duration_ms = int(row.get("duration_ms") or 0)

                perf_attrs = {
                    "algorithm_name": algorithm_name,
                    "duration_ms": duration_ms,
                }

                span = tracer.start_span(name=algorithm_name, attributes=perf_attrs)
                span.set_status(trace.StatusCode.OK)
                span.end()

                metric_attrs = {
                    "algorithm_name": algorithm_name,
                }
                duration_histogram.record(duration_ms, metric_attrs)

            return {
                "ok": True,
                "dry_run": False,
                "exported_count": would_export_count,
                "available": True,
            }

        except Exception as exc:
            return {"ok": False, "detail": f"export failed: {exc}"}
