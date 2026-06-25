"""
Review packs and small-batch discipline — reduce verification tax and reviewer
overload by assembling what already exists (contract, context pack, evidence
bundle) into one reviewer-facing document, plus advisory change-size warnings.
No LLM call. See DEV_STRATEGY.md Stage 7.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.evidence import EvidenceStore

MAX_FILES_WARNING = 20
RUNTIME_ARTIFACT_MARKERS = (
    "/data/",
    "/memory/",
    "agent_context/context_packs/",
    "agent_context/evidence/",
)
RUNTIME_ARTIFACT_SUFFIXES = (".db", ".db-wal", ".db-shm")


def _is_runtime_artifact(path: str) -> bool:
    if any(marker in f"/{path}" for marker in RUNTIME_ARTIFACT_MARKERS):
        return True
    return path.endswith(RUNTIME_ARTIFACT_SUFFIXES)


def small_batch_warnings(changed_files: List[str]) -> List[str]:
    warnings: List[str] = []
    if len(changed_files) > MAX_FILES_WARNING:
        warnings.append(f"touches {len(changed_files)} files (> {MAX_FILES_WARNING}) — consider splitting")

    source_files = [f for f in changed_files if f.startswith("src/") and not _is_runtime_artifact(f)]
    if source_files and "test_auto.py" not in changed_files:
        warnings.append(f"{len(source_files)} source file(s) under src/ changed but test_auto.py was not updated")

    runtime_files = [f for f in changed_files if _is_runtime_artifact(f)]
    non_runtime_files = [f for f in changed_files if not _is_runtime_artifact(f)]
    if runtime_files and non_runtime_files:
        warnings.append(
            f"mixes {len(non_runtime_files)} source/doc change(s) with {len(runtime_files)} "
            f"runtime/generated artifact change(s): {', '.join(runtime_files[:5])}"
            + (", ..." if len(runtime_files) > 5 else "")
        )
    return warnings


class ReviewPackBuilder:
    def __init__(self, config: MemoryOSConfig):
        self.config = config
        self.evidence = EvidenceStore(config)

    def _find_contract(self, task_id: str) -> Optional[Dict[str, Any]]:
        path = self.config.root_dir / "specs" / task_id / "contract.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _find_context_pack(self, task_id: str) -> Optional[Dict[str, Any]]:
        path = self.config.root_dir / "agent_context" / "context_packs" / task_id / "pack.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def build(self, task_id: str) -> Dict[str, Any]:
        bundle = self.evidence.load(task_id)  # raises FileNotFoundError if missing — review needs evidence
        contract = self._find_contract(task_id)
        context_pack = self._find_context_pack(task_id)
        changed_files = self.evidence.changed_files()

        risk_class = (contract or {}).get("risk_class") or bundle.get("risk_class")
        verify_result = self.evidence.verify(task_id)

        not_verified: List[str] = list(bundle.get("known_gaps", []))
        if contract is None:
            not_verified.append(f"no contract found at specs/{task_id}/contract.json")
        if context_pack is None:
            not_verified.append(f"no context pack found at agent_context/context_packs/{task_id}/pack.json")
        if not verify_result["ok"]:
            not_verified.extend(verify_result["reasons"])

        reviewer_focus = small_batch_warnings(changed_files)
        if risk_class:
            reviewer_focus.append(f"risk class: {risk_class}")
        if not verify_result["ok"]:
            reviewer_focus.append("evidence verify is currently failing — see 'Not Verified' section")

        return {
            "task_id": task_id,
            "risk_class": risk_class,
            "contract": contract,
            "context_pack_summary": (
                {
                    "task_summary": context_pack.get("task_summary"),
                    "relevant_file_count": len(context_pack.get("relevant_files", [])),
                }
                if context_pack
                else None
            ),
            "evidence_summary": {
                "commands_total": len(bundle.get("commands", [])),
                "commands_failed": len(verify_result["failed_commands"]),
                "manual_checks": bundle.get("manual_checks", []),
                "reviewer_notes": bundle.get("reviewer_notes", []),
            },
            "files_changed": changed_files,
            "reviewer_focus": reviewer_focus,
            "not_verified": not_verified,
        }


def review_pack_to_markdown(pack: Dict[str, Any]) -> str:
    def bullets(items: List[str]) -> List[str]:
        return [f"- {item}" for item in items] if items else ["- (none)"]

    lines = [
        f"# Review Pack: {pack['task_id']}",
        "",
        f"Risk class: {pack.get('risk_class') or '(unset)'}",
        "",
        "## Files Changed",
        "",
        *bullets(pack["files_changed"]),
        "",
        "## Contract",
        "",
        (f"specs/{pack['task_id']}/contract.json found — objective: {pack['contract'].get('objective', '')}"
         if pack.get("contract") else "(no contract found)"),
        "",
        "## Context Pack",
        "",
        (f"task_summary: {pack['context_pack_summary']['task_summary']} "
         f"({pack['context_pack_summary']['relevant_file_count']} relevant file(s))"
         if pack.get("context_pack_summary") else "(no context pack found)"),
        "",
        "## Evidence Summary",
        "",
        f"- Commands: {pack['evidence_summary']['commands_total']} total, "
        f"{pack['evidence_summary']['commands_failed']} failed",
        *bullets(pack["evidence_summary"]["manual_checks"]),
        "",
        "## Suggested Reviewer Focus",
        "",
        *bullets(pack["reviewer_focus"]),
        "",
        "## Not Verified",
        "",
        *bullets(pack["not_verified"]),
        "",
    ]
    return "\n".join(lines)


def change_size_report(config: MemoryOSConfig) -> Dict[str, Any]:
    changed_files = EvidenceStore(config).changed_files()
    return {
        "file_count": len(changed_files),
        "files": changed_files,
        "warnings": small_batch_warnings(changed_files),
    }
