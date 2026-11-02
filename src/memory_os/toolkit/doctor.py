"""Structured diagnostics backend for the Memory OS doctor command."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from memory_os.core.config import MemoryOSConfig


class DoctorService:
    def __init__(self, config: MemoryOSConfig):
        self.config = config
        self.root = config.root_dir

    def run(self) -> Dict[str, Any]:
        config_file = self.root / "memory_os.config.json"
        directories = [
            {"name": name, "exists": (self.root / name).is_dir()}
            for name in ("memory", "agent_context", "workflows")
        ]
        files = [
            self._file_report("nodes.jsonl", self.config.memory_dir / "nodes.jsonl"),
            self._file_report("edges.jsonl", self.config.memory_dir / "edges.jsonl"),
            self._file_report("events.jsonl", self.config.memory_dir / "events.jsonl"),
            self._file_report("task_capsules.jsonl", self.config.capsules_file),
        ]
        database = self._database_report()

        from memory_os.core.llm_service import _discover_ollama_model

        ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        llm = {
            "ollama_host": ollama_host,
            "ollama_model": _discover_ollama_model(ollama_host),
            "api_keys": [
                key
                for key in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY")
                if os.environ.get(key)
            ],
        }

        from memory_os.core.disk_guard import DiskGuard

        disk = DiskGuard(self.config).snapshot().to_dict()
        evidence = self._evidence_report()
        daemon = self._daemon_report()

        try:
            from memory_os.toolkit.workspace_runtime import WorkspaceSpec, workspace_runtime_diagnostics

            spec = WorkspaceSpec(
                root=self.root,
                session_name=self.config.tmux_session_name,
                panes=[],
            )
            workspace = workspace_runtime_diagnostics(spec)
        except Exception as exc:
            workspace = {"error": str(exc), "runtimes": {}, "zellij_exited_sessions": []}

        ok = (
            all(item["exists"] for item in directories)
            and all(item["exists"] for item in files)
            and database["exists"]
            and not database.get("error")
        )
        return {
            "ok": ok,
            "config": {
                "exists": config_file.exists(),
                "path": str(config_file),
                "relative_path": str(config_file.relative_to(self.root)),
            },
            "directories": directories,
            "files": files,
            "database": database,
            "llm": llm,
            "disk": disk,
            "evidence": evidence,
            "daemon": daemon,
            "workspace": workspace,
        }

    @staticmethod
    def _file_report(name: str, path: Path) -> Dict[str, Any]:
        exists = path.exists()
        return {
            "name": name,
            "path": str(path),
            "exists": exists,
            "size_bytes": path.stat().st_size if exists else 0,
        }

    def _database_report(self) -> Dict[str, Any]:
        path = self.config.db_path
        report: Dict[str, Any] = {
            "exists": path.exists(),
            "path": str(path),
            "relative_path": str(path.relative_to(self.root)),
            "active_nodes": None,
            "telemetry_records": None,
            "telemetry": {},
            "error": "",
        }
        if not path.exists():
            return report

        connection = None
        try:
            connection = sqlite3.connect(str(path))
            report["active_nodes"] = connection.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE valid_to IS NULL"
            ).fetchone()[0]
            report["telemetry_records"] = connection.execute(
                "SELECT COUNT(*) FROM memory_os_telemetry"
            ).fetchone()[0]

            from memory_os.core.telemetry_policy import TelemetryPolicy

            report["telemetry"] = TelemetryPolicy(self.config, db_path=path).audit(connection)
        except Exception as exc:
            report["error"] = str(exc)
        finally:
            if connection is not None:
                connection.close()
        return report

    def _evidence_report(self) -> Dict[str, Any]:
        evidence_dir = self.root / "agent_context" / "evidence"
        bundles = (
            sorted(evidence_dir.glob("*/bundle.json"), key=lambda path: path.stat().st_mtime)
            if evidence_dir.is_dir()
            else []
        )
        if not bundles:
            return {"recorded": False}

        from memory_os.core.evidence import EvidenceStore

        task_id = bundles[-1].parent.name
        verification = EvidenceStore(self.config).verify(task_id)
        return {
            "recorded": True,
            "task_id": task_id,
            "ok": verification["ok"],
            "reasons": verification["reasons"],
        }

    def _daemon_report(self) -> Dict[str, Any]:
        pid_file = self.root / "data" / "daemon.pid"
        if not pid_file.exists():
            return {"state": "stopped", "pid": None, "error": ""}
        try:
            pid = int(pid_file.read_text().strip())
            try:
                os.kill(pid, 0)
                return {"state": "running", "pid": pid, "error": ""}
            except OSError:
                return {"state": "dead", "pid": pid, "error": ""}
        except Exception as exc:
            return {"state": "error", "pid": None, "error": str(exc)}


def workspace_diagnostic_lines(report: Dict[str, Any]) -> List[str]:
    if report.get("error"):
        return [f"  [!] Workspace runtime diagnostics failed: {report['error']}"]
    lines = []
    for runtime_name, status in report.get("runtimes", {}).items():
        state = status.get("state")
        if status.get("available"):
            suffix = f"state={state}" if state else "available"
            lines.append(f"  [✓] Workspace runtime {runtime_name}: {suffix}")
        else:
            lines.append(f"  [!] Workspace runtime {runtime_name}: {state or 'unavailable'}")
        if status.get("detail"):
            lines.append(f"      - {status['detail']}")
    exited = report.get("zellij_exited_sessions", [])
    if exited:
        lines.append(
            f"  [!] Zellij exited sessions: {', '.join(exited)} — "
            "run 'memory_os workspace clean-exited --runtime zellij --apply'"
        )
    return lines


def render_doctor_text(report: Dict[str, Any]) -> str:
    lines = ["=== Memory OS Diagnostics (doctor) ===", ""]
    config = report["config"]
    if config["exists"]:
        lines.append(f"  [✓] Config file: Found at {config['relative_path']}")
    else:
        lines.append("  [!] Config file: Missing! Using default developer profile.")

    for directory in report["directories"]:
        marker = "✓" if directory["exists"] else "✗"
        state = "Exists" if directory["exists"] else "Missing!"
        lines.append(f"  [{marker}] Directory '{directory['name']}': {state}")
    for file_report in report["files"]:
        if file_report["exists"]:
            lines.append(
                f"  [✓] File '{file_report['name']}': Exists ({file_report['size_bytes']} bytes)"
            )
        else:
            lines.append(f"  [✗] File '{file_report['name']}': Missing!")

    database = report["database"]
    if database["exists"]:
        lines.append(f"  [✓] SQLite DB: Found at {database['relative_path']}")
        if database["error"]:
            lines.append(f"  [✗] SQLite DB connection error: {database['error']}")
        else:
            lines.append(f"      - Active nodes in SQLite: {database['active_nodes']}")
            lines.append(f"      - Telemetry records: {database['telemetry_records']}")
            telemetry = database["telemetry"]
            if telemetry["db_over_cap"]:
                lines.append(
                    f"  [!] Telemetry: DB size {telemetry['db_mb']} MB exceeds max_db_mb cap "
                    f"({telemetry['max_db_mb']} MB) — run 'memory_os telemetry prune'"
                )
            elif telemetry["db_warn_cap"]:
                lines.append(
                    f"  [!] Telemetry: DB size {telemetry['db_mb']} MB approaching max_db_mb cap "
                    f"({telemetry['max_db_mb']} MB)"
                )
            for table in telemetry["tables"]:
                if table["over_cap"]:
                    lines.append(
                        f"  [!] Telemetry: '{table['table']}' has {table['row_count']} rows, exceeds "
                        f"max_rows_per_table cap ({table['max_rows']}) — run 'memory_os telemetry prune'"
                    )
                elif table["warn_cap"]:
                    lines.append(
                        f"  [!] Telemetry: '{table['table']}' has {table['row_count']} rows, approaching "
                        f"max_rows_per_table cap ({table['max_rows']})"
                    )
    else:
        lines.append("  [✗] SQLite DB: Missing!")

    llm = report["llm"]
    if llm["ollama_model"]:
        lines.append(
            f"  [✓] Local Ollama reachable at {llm['ollama_host']} ({llm['ollama_model']}) — "
            "tried first, no key needed"
        )
    if llm["api_keys"]:
        lines.append(f"  [✓] LLM API Keys configured: {', '.join(llm['api_keys'])}")
    elif not llm["ollama_model"]:
        lines.append(
            "  [!] LLM API Keys: None found, and no local Ollama model reachable "
            "(Background calls will fail)"
        )

    disk = report["disk"]
    if disk["low_disk"]:
        lines.append(
            f"  [!] Disk: {disk['free_disk_mb']:,.1f} MB free — below min_free_disk_mb threshold"
        )
    else:
        lines.append(f"  [✓] Disk: {disk['free_disk_mb']:,.1f} MB free")
    sqlite_health = disk["sqlite"]
    if sqlite_health["exceeds_max_wal"]:
        lines.append(
            f"  [!] SQLite WAL: {sqlite_health['wal_mb']} MB — exceeds max_sqlite_wal_mb cap"
        )
    elif sqlite_health["wal_mb"]:
        lines.append(f"      - SQLite WAL: {sqlite_health['wal_mb']} MB")

    evidence = report["evidence"]
    if evidence["recorded"]:
        status = "OK" if evidence["ok"] else "NOT VERIFIED"
        marker = "✓" if evidence["ok"] else "!"
        lines.append(
            f"  [{marker}] Last evidence bundle: task '{evidence['task_id']}' — {status}"
        )
        lines.extend(f"      - {reason}" for reason in evidence["reasons"])
    else:
        lines.append("  [ ] Last evidence bundle: none recorded yet")

    daemon = report["daemon"]
    if daemon["state"] == "running":
        lines.append(f"  [✓] Background Daemon: RUNNING (PID {daemon['pid']})")
    elif daemon["state"] == "dead":
        lines.append(
            f"  [!] Background Daemon: PID file exists ({daemon['pid']}) but process is dead."
        )
    elif daemon["state"] == "error":
        lines.append(f"  [!] Background Daemon: Error checking PID file: {daemon['error']}")
    else:
        lines.append("  [ ] Background Daemon: STOPPED")

    lines.extend(workspace_diagnostic_lines(report["workspace"]))
    lines.append("")
    lines.append(
        "Doctor diagnostics: ALL CRITICAL PATHS OK"
        if report["ok"]
        else "Doctor diagnostics: CRITICAL PATH ERRORS FOUND! Run 'memory_os init' to resolve."
    )
    return "\n".join(lines)
