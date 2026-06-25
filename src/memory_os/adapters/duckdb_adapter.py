"""Optional DuckDB analytics adapter over existing local Memory OS artifacts."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_os.core.config import MemoryOSConfig


def is_available() -> bool:
    """Return True when the optional duckdb package is importable."""
    return importlib.util.find_spec("duckdb") is not None


class DuckDBAdapter:
    """Run local analytical reports without making DuckDB a source of truth."""

    def __init__(self, config: MemoryOSConfig):
        self.config = config

    def report(self, topic: str) -> Dict[str, Any]:
        """Aggregate a supported analytics topic with an in-memory DuckDB connection."""
        if topic not in {"evals", "telemetry", "evidence"}:
            return {
                "ok": False,
                "detail": f"unsupported topic: {topic}",
                "topic": topic,
            }

        if not is_available():
            return {
                "ok": False,
                "detail": "duckdb package not installed",
                "topic": topic,
            }

        try:
            import duckdb  # type: ignore

            conn = duckdb.connect()
            try:
                if topic == "evals":
                    return self._report_evals(conn)
                if topic == "telemetry":
                    return self._report_telemetry(conn)
                if topic == "evidence":
                    return self._report_evidence(conn)
                return {
                    "ok": False,
                    "detail": f"unsupported topic: {topic}",
                    "topic": topic,
                }
            finally:
                conn.close()
        except Exception as exc:
            return {
                "ok": False,
                "detail": f"report failed: {exc}",
                "topic": topic,
            }

    def export(self, format: str = "json", dry_run: bool = True) -> Dict[str, Any]:
        """Export a small analytics inventory without touching source-of-truth files."""
        relative_target = f"agent_context/analytics_export.{format}"
        if dry_run or not is_available():
            return {
                "ok": True,
                "dry_run": True,
                "would_write": relative_target,
            }

        try:
            import duckdb  # type: ignore

            target = self.config.root_dir / relative_target
            target.parent.mkdir(parents=True, exist_ok=True)

            conn = duckdb.connect()
            try:
                rows = self._export_inventory_rows()
                self._create_export_table(conn)
                conn.executemany(
                    "INSERT INTO analytics_export VALUES (?, ?, ?, ?)",
                    [
                        (
                            row["topic"],
                            row["name"],
                            row["metric"],
                            row["value"],
                        )
                        for row in rows
                    ],
                )
                if format == "parquet":
                    escaped = str(target).replace("'", "''")
                    conn.execute(
                        f"COPY analytics_export TO '{escaped}' (FORMAT PARQUET)"
                    )
                elif format == "json":
                    with target.open("w", encoding="utf-8") as f:
                        json.dump(rows, f, ensure_ascii=False, indent=2)
                else:
                    return {
                        "ok": False,
                        "dry_run": False,
                        "detail": f"unsupported export format: {format}",
                        "would_write": relative_target,
                    }
            finally:
                conn.close()

            return {
                "ok": True,
                "dry_run": False,
                "wrote": relative_target,
                "rows": len(rows),
            }
        except Exception as exc:
            return {
                "ok": False,
                "dry_run": False,
                "detail": f"export failed: {exc}",
                "would_write": relative_target,
            }

    def audit(self) -> Dict[str, Any]:
        """Return instant adapter availability without reading project data."""
        return {"available": is_available()}

    def _report_evals(self, conn: Any) -> Dict[str, Any]:
        rows = self._load_eval_suites()
        conn.execute(
            """
            CREATE TABLE eval_suites (
                name VARCHAR,
                kind VARCHAR,
                case_count INTEGER,
                pass_threshold DOUBLE,
                description VARCHAR
            )
            """
        )
        if rows:
            conn.executemany(
                "INSERT INTO eval_suites VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        row["name"],
                        row["kind"],
                        row["case_count"],
                        row["pass_threshold"],
                        row["description"],
                    )
                    for row in rows
                ],
            )

        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS suite_count,
                COALESCE(SUM(case_count), 0) AS case_count,
                COALESCE(AVG(pass_threshold), 0.0) AS avg_pass_threshold
            FROM eval_suites
            """
        ).fetchone()
        by_kind = conn.execute(
            """
            SELECT kind, COUNT(*) AS suites, COALESCE(SUM(case_count), 0) AS cases
            FROM eval_suites
            GROUP BY kind
            ORDER BY kind
            """
        ).fetchall()

        return {
            "ok": True,
            "topic": "evals",
            "rows": int(totals[0]),
            "summary": {
                "suites": int(totals[0]),
                "cases": int(totals[1]),
                "avg_pass_threshold": float(totals[2]),
                "by_kind": {
                    str(kind): {"suites": int(suites), "cases": int(cases)}
                    for kind, suites, cases in by_kind
                },
            },
        }

    def _report_telemetry(self, conn: Any) -> Dict[str, Any]:
        rows = self._load_telemetry_rows()
        conn.execute(
            """
            CREATE TABLE telemetry_events (
                kind VARCHAR,
                name VARCHAR,
                status VARCHAR,
                tokens BIGINT,
                latency_ms DOUBLE,
                cost DOUBLE,
                duration_ms DOUBLE
            )
            """
        )
        if rows:
            conn.executemany(
                "INSERT INTO telemetry_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        row["kind"],
                        row["name"],
                        row["status"],
                        row["tokens"],
                        row["latency_ms"],
                        row["cost"],
                        row["duration_ms"],
                    )
                    for row in rows
                ],
            )

        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS rows,
                COALESCE(SUM(tokens), 0) AS tokens,
                COALESCE(SUM(cost), 0.0) AS cost,
                COALESCE(AVG(latency_ms), 0.0) AS avg_latency_ms,
                COALESCE(AVG(duration_ms), 0.0) AS avg_duration_ms
            FROM telemetry_events
            """
        ).fetchone()
        by_kind = conn.execute(
            """
            SELECT kind, COUNT(*) AS rows
            FROM telemetry_events
            GROUP BY kind
            ORDER BY kind
            """
        ).fetchall()
        by_status = conn.execute(
            """
            SELECT status, COUNT(*) AS rows
            FROM telemetry_events
            WHERE kind = 'telemetry'
            GROUP BY status
            ORDER BY status
            """
        ).fetchall()

        return {
            "ok": True,
            "topic": "telemetry",
            "rows": int(totals[0]),
            "summary": {
                "tokens": int(totals[1]),
                "cost": float(totals[2]),
                "avg_latency_ms": float(totals[3]),
                "avg_duration_ms": float(totals[4]),
                "by_kind": {str(kind): int(count) for kind, count in by_kind},
                "by_status": {
                    str(status): int(count) for status, count in by_status
                },
            },
        }

    def _report_evidence(self, conn: Any) -> Dict[str, Any]:
        rows = self._load_evidence_bundles()
        conn.execute(
            """
            CREATE TABLE evidence_bundles (
                task_id VARCHAR,
                risk_class VARCHAR,
                command_count INTEGER,
                known_gap_count INTEGER
            )
            """
        )
        if rows:
            conn.executemany(
                "INSERT INTO evidence_bundles VALUES (?, ?, ?, ?)",
                [
                    (
                        row["task_id"],
                        row["risk_class"],
                        row["command_count"],
                        row["known_gap_count"],
                    )
                    for row in rows
                ],
            )

        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS rows,
                COALESCE(SUM(command_count), 0) AS commands,
                COALESCE(SUM(known_gap_count), 0) AS known_gaps
            FROM evidence_bundles
            """
        ).fetchone()
        by_risk = conn.execute(
            """
            SELECT risk_class, COUNT(*) AS rows
            FROM evidence_bundles
            GROUP BY risk_class
            ORDER BY risk_class
            """
        ).fetchall()

        return {
            "ok": True,
            "topic": "evidence",
            "rows": int(totals[0]),
            "summary": {
                "commands": int(totals[1]),
                "known_gaps": int(totals[2]),
                "by_risk_class": {
                    str(risk_class): int(count) for risk_class, count in by_risk
                },
            },
        }

    def _load_eval_suites(self) -> List[Dict[str, Any]]:
        evals_dir = Path(__file__).resolve().parent.parent / "toolkit" / "evals"
        rows: List[Dict[str, Any]] = []
        if not evals_dir.is_dir():
            return rows

        for suite_dir in sorted(path for path in evals_dir.iterdir() if path.is_dir()):
            config = self._read_json_object(suite_dir / "config.json") or {}
            rows.append(
                {
                    "name": suite_dir.name,
                    "kind": str(config.get("kind", "")),
                    "case_count": self._count_jsonl_cases(suite_dir / "cases.jsonl"),
                    "pass_threshold": self._safe_float(
                        config.get("pass_threshold"),
                        default=0.0,
                    ),
                    "description": str(config.get("description", "")),
                }
            )
        return rows

    def _load_telemetry_rows(self) -> List[Dict[str, Any]]:
        db_path = self.config.db_path
        if not db_path.exists():
            return []

        rows: List[Dict[str, Any]] = []
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                if self._sqlite_table_exists(conn, "memory_os_telemetry"):
                    for row in conn.execute(
                        """
                        SELECT
                            prompt_name,
                            status,
                            input_tokens,
                            output_tokens,
                            cached_tokens,
                            latency_ms,
                            cost
                        FROM memory_os_telemetry
                        """
                    ):
                        rows.append(
                            {
                                "kind": "telemetry",
                                "name": row["prompt_name"],
                                "status": row["status"],
                                "tokens": (
                                    int(row["input_tokens"] or 0)
                                    + int(row["output_tokens"] or 0)
                                    + int(row["cached_tokens"] or 0)
                                ),
                                "latency_ms": self._optional_float(
                                    row["latency_ms"]
                                ),
                                "cost": self._safe_float(row["cost"]),
                                "duration_ms": None,
                            }
                        )
                if self._sqlite_table_exists(conn, "memory_os_performance"):
                    for row in conn.execute(
                        """
                        SELECT algorithm_name, duration_ms
                        FROM memory_os_performance
                        """
                    ):
                        rows.append(
                            {
                                "kind": "performance",
                                "name": row["algorithm_name"],
                                "status": "recorded",
                                "tokens": 0,
                                "latency_ms": None,
                                "cost": 0.0,
                                "duration_ms": self._optional_float(
                                    row["duration_ms"]
                                ),
                            }
                        )
            finally:
                conn.close()
        except sqlite3.Error:
            return []
        return rows

    def _load_evidence_bundles(self) -> List[Dict[str, Any]]:
        evidence_dir = self.config.root_dir / "agent_context" / "evidence"
        rows: List[Dict[str, Any]] = []
        if not evidence_dir.is_dir():
            return rows

        for bundle_path in sorted(evidence_dir.glob("*/bundle.json")):
            bundle = self._read_json_object(bundle_path)
            if not bundle:
                continue
            rows.append(
                {
                    "task_id": str(bundle.get("task_id", "")),
                    "risk_class": str(bundle.get("risk_class", "")),
                    "command_count": self._count_items(bundle.get("commands")),
                    "known_gap_count": self._count_items(bundle.get("known_gaps")),
                }
            )
        return rows

    def _export_inventory_rows(self) -> List[Dict[str, str]]:
        eval_rows = self._load_eval_suites()
        telemetry_rows = self._load_telemetry_rows()
        evidence_rows = self._load_evidence_bundles()
        return [
            {
                "topic": "evals",
                "name": "suites",
                "metric": "count",
                "value": str(len(eval_rows)),
            },
            {
                "topic": "evals",
                "name": "cases",
                "metric": "count",
                "value": str(sum(row["case_count"] for row in eval_rows)),
            },
            {
                "topic": "telemetry",
                "name": "events",
                "metric": "count",
                "value": str(len(telemetry_rows)),
            },
            {
                "topic": "evidence",
                "name": "bundles",
                "metric": "count",
                "value": str(len(evidence_rows)),
            },
        ]

    def _create_export_table(self, conn: Any) -> None:
        conn.execute(
            """
            CREATE TABLE analytics_export (
                topic VARCHAR,
                name VARCHAR,
                metric VARCHAR,
                value VARCHAR
            )
            """
        )

    def _count_jsonl_cases(self, path: Path) -> int:
        if not path.exists():
            return 0
        count = 0
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    count += 1
        except OSError:
            return 0
        return count

    def _read_json_object(self, path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        if isinstance(data, dict):
            return data
        return None

    def _sqlite_table_exists(self, conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    def _count_items(self, value: Any) -> int:
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return len(value)
        if value:
            return 1
        return 0

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _optional_float(self, value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None
