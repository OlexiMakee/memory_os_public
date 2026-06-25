"""
Evidence bundles — make "done" mean verified, not just generated.

A bundle is a plain JSON file under agent_context/evidence/<task_id>/bundle.json
tracking exact commands run, their exit codes, a bounded+redacted output
summary, changed files (from git), manual checks, known gaps, risk class, and
reviewer notes. No LLM call. See DEV_STRATEGY.md Stage 5.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from memory_os.core.config import MemoryOSConfig
from memory_os.core.safe_id import validate_safe_id
from memory_os.core.write_budget import ArtifactWriteBudget
from memory_os.modules.context import ContextRegistry

MAX_OUTPUT_CHARS = 4000
TRUNCATION_NOTE = "\n...[truncated, bounded evidence output]"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _bound_and_redact(text: str) -> str:
    redacted = ContextRegistry.redact(text)
    if len(redacted) > MAX_OUTPUT_CHARS:
        return redacted[:MAX_OUTPUT_CHARS] + TRUNCATION_NOTE
    return redacted


class EvidenceStore:
    """Reads/writes plain-file evidence bundles. Knows nothing about LLM providers or UI."""

    def __init__(self, config: MemoryOSConfig):
        self.config = config
        self.evidence_dir = config.root_dir / "agent_context" / "evidence"

    def bundle_path(self, task_id: str) -> Path:
        validate_safe_id(task_id, "task_id")
        return self.evidence_dir / task_id / "bundle.json"

    def load(self, task_id: str) -> Dict[str, Any]:
        path = self.bundle_path(task_id)
        if not path.exists():
            raise FileNotFoundError(f"No evidence bundle for task '{task_id}'. Run 'memory_os evidence init --task {task_id}' first.")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, bundle: Dict[str, Any]) -> None:
        path = self.bundle_path(bundle["task_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.parent.chmod(0o700)
        except OSError:
            pass
        bundle["updated_at"] = _now()
        ArtifactWriteBudget(self.config).write_text(path, json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def init(self, task_id: str, risk_class: Optional[str] = None, force: bool = False, dry_run: bool = False) -> Dict[str, Any]:
        path = self.bundle_path(task_id)
        if path.exists() and not force:
            raise FileExistsError(f"Evidence bundle already exists for task '{task_id}' (use --force to overwrite)")
        bundle = {
            "task_id": task_id,
            "risk_class": risk_class,
            "created_at": _now(),
            "updated_at": _now(),
            "changed_files": [],
            "commands": [],
            "manual_checks": [],
            "known_gaps": [],
            "reviewer_notes": [],
        }
        if not dry_run:
            self._save(bundle)
        return bundle

    def changed_files(self) -> List[str]:
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                cwd=str(self.config.root_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        files = []
        records = result.stdout.split("\0")
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record or len(record) <= 3:
                continue

            status = record[:2]
            path = record[3:]
            if (status[0] in {"R", "C"} or status[1] in {"R", "C"}) and index < len(records):
                paired_path = records[index]
                index += 1
                if not (self.config.root_dir / path).exists() and (self.config.root_dir / paired_path).exists():
                    path = paired_path
            files.append(path)
        return sorted(set(files))

    def add_command(self, task_id: str, command: Sequence[str], dry_run: bool = False) -> Dict[str, Any]:
        bundle = self.load(task_id)
        command_str = " ".join(command)
        try:
            result = subprocess.run(
                list(command),
                cwd=str(self.config.root_dir),
                capture_output=True,
                text=True,
                timeout=600,
            )
            exit_code = result.returncode
            raw_output = (result.stdout or "") + (result.stderr or "")
        except (OSError, subprocess.SubprocessError) as exc:
            exit_code = 127
            raw_output = f"failed to run command: {exc}"

        entry = {
            "command": command_str,
            "exit_code": exit_code,
            "output_summary": _bound_and_redact(raw_output),
            "ran_at": _now(),
        }
        if not dry_run:
            bundle["commands"].append(entry)
            self._save(bundle)
        else:
            bundle = dict(bundle)
            bundle["commands"] = bundle["commands"] + [entry]
        bundle["_last_command"] = entry
        return bundle

    def summarize(
        self,
        task_id: str,
        manual_checks: Optional[List[str]] = None,
        known_gaps: Optional[List[str]] = None,
        reviewer_notes: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        bundle = self.load(task_id)
        for key, new_items in (
            ("manual_checks", manual_checks),
            ("known_gaps", known_gaps),
            ("reviewer_notes", reviewer_notes),
        ):
            for item in new_items or []:
                if item not in bundle[key]:
                    bundle[key].append(item)
        bundle["changed_files"] = self.changed_files()
        if not dry_run:
            self._save(bundle)

        commands = bundle["commands"]
        passed = sum(1 for c in commands if c["exit_code"] == 0)
        bundle["summary"] = {
            "total_commands": len(commands),
            "passed": passed,
            "failed": len(commands) - passed,
            "changed_file_count": len(bundle["changed_files"]),
            "known_gap_count": len(bundle["known_gaps"]),
        }
        return bundle

    def verify(self, task_id: str) -> Dict[str, Any]:
        bundle = self.load(task_id)
        commands = bundle["commands"]
        failed = [c for c in commands if c["exit_code"] != 0]
        reasons = []
        if not commands:
            reasons.append("no commands have been recorded — nothing has actually been verified")
        if failed:
            reasons.append(f"{len(failed)} recorded command(s) exited non-zero")
        if not bundle.get("risk_class"):
            reasons.append("risk_class is not set")
        return {
            "task_id": task_id,
            "ok": not reasons,
            "reasons": reasons,
            "failed_commands": [c["command"] for c in failed],
        }


def bundle_to_markdown(bundle: Dict[str, Any]) -> str:
    def bullets(items: List[str]) -> List[str]:
        return [f"- {item}" for item in items] if items else ["- (none)"]

    summary = bundle.get("summary", {})
    lines = [
        f"# Evidence: {bundle['task_id']}",
        "",
        f"Risk class: {bundle.get('risk_class') or '(unset)'}",
        f"Created: {bundle.get('created_at', '-')}  |  Updated: {bundle.get('updated_at', '-')}",
        "",
        "## Changed Files",
        "",
        *bullets(bundle.get("changed_files", [])),
        "",
        "## Commands Run",
        "",
    ]
    if bundle.get("commands"):
        for c in bundle["commands"]:
            lines.append(f"- `{c['command']}` -> exit {c['exit_code']} ({c['ran_at']})")
    else:
        lines.append("- (none)")
    lines += [
        "",
        "## Manual Checks",
        "",
        *bullets(bundle.get("manual_checks", [])),
        "",
        "## Known Gaps",
        "",
        *bullets(bundle.get("known_gaps", [])),
        "",
        "## Reviewer Notes",
        "",
        *bullets(bundle.get("reviewer_notes", [])),
        "",
    ]
    if summary:
        lines += [
            "## Summary",
            "",
            f"- Commands: {summary['total_commands']} total, {summary['passed']} passed, {summary['failed']} failed",
            f"- Changed files: {summary['changed_file_count']}",
            f"- Known gaps: {summary['known_gap_count']}",
            "",
        ]
    return "\n".join(lines)
