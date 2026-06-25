"""MLflow Run-Tracking Exporter for Memory OS.

Exports existing evidence bundles as MLflow-style "runs" (one run per task_id,
exit codes/counts as metrics, risk_class/task_id as tags).
This is an export path only and does not act as primary storage.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_os.core.config import MemoryOSConfig


def is_available() -> bool:
    """True iff importlib.util.find_spec("mlflow") is not None."""
    try:
        return importlib.util.find_spec("mlflow") is not None
    except Exception:
        return False


class MLflowExporter:
    """Exporter that reads Memory OS evidence bundles and logs them to MLflow."""

    def __init__(self, config: MemoryOSConfig):
        self.config = config

    def audit(self) -> Dict[str, Any]:
        """Instant check to determine if MLflow is available."""
        return {"available": is_available()}

    def export(self, dry_run: bool = True) -> Dict[str, Any]:
        """Reads every agent_context/evidence/*/bundle.json and exports to MLflow."""
        try:
            evidence_dir = self.config.root_dir / "agent_context" / "evidence"
            bundles = []

            if evidence_dir.exists() and evidence_dir.is_dir():
                for path in evidence_dir.glob("*/bundle.json"):
                    try:
                        if path.is_file():
                            with open(path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                                if isinstance(data, dict) and "task_id" in data:
                                    bundles.append(data)
                    except Exception:
                        # skip gracefully if the directory or files don't exist or fail to parse
                        continue

            would_export_count = len(bundles)

            if dry_run:
                return {
                    "ok": True,
                    "dry_run": True,
                    "would_export_count": would_export_count,
                    "available": is_available(),
                }

            # If not dry_run, check availability
            if not is_available():
                return {
                    "ok": False,
                    "detail": "mlflow package not installed",
                    "would_export_count": would_export_count,
                }

            # Lazily import mlflow inside try/except ImportError
            try:
                import mlflow
            except ImportError as exc:
                return {
                    "ok": False,
                    "detail": f"mlflow package not installed: {exc}",
                    "would_export_count": would_export_count,
                }

            # Export each bundle to MLflow
            for bundle in bundles:
                task_id = bundle.get("task_id")
                risk_class = bundle.get("risk_class") or "unset"
                commands = bundle.get("commands", [])

                # Calculate metrics
                commands_total = len(commands)
                commands_failed = sum(1 for c in commands if c.get("exit_code", 0) != 0)

                # Attempt to start/log/end an MLflow run
                with mlflow.start_run(run_name=str(task_id)) as run:
                    # Log tags
                    mlflow.set_tag("risk_class", str(risk_class))
                    mlflow.set_tag("task_id", str(task_id))

                    # Log metrics
                    mlflow.log_metric("commands_total", float(commands_total))
                    mlflow.log_metric("commands_failed", float(commands_failed))

                    # Log parameters
                    mlflow.log_param("created_at", str(bundle.get("created_at", "")))
                    mlflow.log_param("updated_at", str(bundle.get("updated_at", "")))

                    # Log changed files count
                    changed_files = bundle.get("changed_files", [])
                    mlflow.log_metric("changed_files_count", float(len(changed_files)))

                    # Try to log the original bundle JSON content as an artifact
                    try:
                        mlflow.log_text(json.dumps(bundle, indent=2), "bundle.json")
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
