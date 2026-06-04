#!/usr/bin/env python3
"""Audit Memory OS workflow state and emit a compact report."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_task_capsules import validate_rows
from memory_os.toolkit.workflow_validator import build_report as build_workflow_report
from memory_os.toolkit.memory_validator import validate_proposals_file
from memory_os.core.config import MemoryOSConfig

STEP_NAMES = {
    1: "nano",
    2: "micro",
    3: "tiny",
    4: "little",
    5: "pretty little",
    6: "light mid",
    7: "mid",
    8: "high mid",
    9: "mid high",
    10: "big",
    11: "large",
    12: "giant",
}


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def load_jsonl(path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    if not path.exists():
        return rows, [f"{path}: file not found"]
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: invalid JSON: {exc.msg}")
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            errors.append(f"line {line_number}: row must be a JSON object")
    return rows, errors


def parse_handshake(text: str) -> Dict[str, Any]:
    active_agent = _first_match(text, r"^- Active Agent:\s*(.+)$")
    budget_tier = _first_match(text, r"^- Budget Tier applied:\s*(.+)$")
    target = _first_match(text, r"^- Target:\s*(.+)$")
    target_command = _first_match(text, r"^- Target Command:\s*(.+)$")
    completed = re.findall(r"^- \[x\]\s+(.+)$", text, flags=re.MULTILINE)
    pending = re.findall(r"^- \[ \]\s+(.+)$", text, flags=re.MULTILINE)
    return {
        "active_agent": active_agent,
        "budget_tier": budget_tier,
        "target": target,
        "target_command": target_command,
        "completed_count": len(completed),
        "pending": pending,
    }


def _first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def summarize_capsules(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(rows)
    workflow_counts = Counter(str(row.get("workflow", "legacy")) for row in rows)
    step_counts = Counter(str(row.get("step_name", "legacy")) for row in rows)
    missing_metadata = [
        row.get("task", "<untitled>")
        for row in rows
        if not all(key in row for key in ("workflow", "step_score", "step_name"))
    ]
    latest = rows[-1] if rows else {}
    return {
        "total": len(rows),
        "workflow_counts": dict(workflow_counts),
        "step_counts": dict(step_counts),
        "missing_metadata_count": len(missing_metadata),
        "latest_task": latest.get("task", ""),
        "latest_workflow": latest.get("workflow", "legacy") if latest else "",
        "latest_step": latest.get("step_name", "legacy") if latest else "",
    }


def inspect_memory_lifecycle(root: Path) -> Dict[str, Any]:
    config_candidate = root / "memory_os.config.json"
    config = MemoryOSConfig(config_path=str(config_candidate) if config_candidate.exists() else None)
    if root != config.root_dir:
        config.root_dir = root
    memory_dir = config.memory_dir
    files = {
        "nodes": memory_dir / "nodes.jsonl",
        "edges": memory_dir / "edges.jsonl",
        "events": memory_dir / "events.jsonl",
        "schema": memory_dir / "schema.json",
    }
    result = {}
    for name, path in files.items():
        if path.suffix == ".jsonl":
            rows, errors = load_jsonl(path)
            result[name] = {
                "exists": path.exists(),
                "rows": len(rows),
                "errors": errors[:5],
            }
        else:
            result[name] = {
                "exists": path.exists(),
                "bytes": path.stat().st_size if path.exists() else 0,
            }
    return result


def roadmap_system_status(text: str) -> Dict[str, Any]:
    items = re.findall(r"^- \[(x| )\]\s+\*\*(.+?)\*\*", text, flags=re.MULTILINE)
    memory_os_items = [
        {"done": status == "x", "title": title}
        for status, title in items
        if _looks_like_memory_os_item(title)
    ]
    return {
        "items": memory_os_items,
        "done": sum(1 for item in memory_os_items if item["done"]),
        "open": [item["title"] for item in memory_os_items if not item["done"]],
    }


def _looks_like_memory_os_item(title: str) -> bool:
    lowered = title.lower()
    return any(term in lowered for term in ("memory", "retrieval", "task experience", "method log", "root index"))


def build_recommendations(report: Dict[str, Any]) -> List[str]:
    recommendations = []
    if report["capsules"]["missing_metadata_count"]:
        recommendations.append("Keep old capsules intact, but require workflow/step metadata for all new rows.")
    if report["capsule_validation_errors"]:
        recommendations.append("Fix task capsule validation errors before adding new memory_os automation.")
    if report.get("proposal_validation_errors"):
        recommendations.append("Fix proposal inbox validation errors to ensure consistent metadata.")
    if report["roadmap"]["open"]:
        recommendations.append(f"Next memory_os work: {report['roadmap']['open'][0]}.")
    if not report.get("workflow_manifest", {}).get("ok", False):
        recommendations.append("Fix workflow manifest validation before relying on task quantization.")
    if not report["memory_lifecycle"].get("events", {}).get("rows"):
        recommendations.append("Record lifecycle events for Memory OS state transitions before relying on automation.")
    if not recommendations:
        recommendations.append("Memory OS control plane is structurally ready for the next planned memory_os implementation.")
    return recommendations


def auto_transition_proposals(root: Path) -> List[str]:
    import subprocess
    config_candidate = root / "memory_os.config.json"
    config = MemoryOSConfig(config_path=str(config_candidate) if config_candidate.exists() else None)
    if root != config.root_dir:
        config.root_dir = root
    nodes_file = config.memory_dir / "nodes.jsonl"
    proposals_file = config.proposals_file
    events_file = config.memory_dir / "events.jsonl"
    
    if not nodes_file.exists() or not proposals_file.exists():
        return []
        
    # 1. Load verified proposal nodes
    verified_proposal_ids = {}
    nodes, _ = load_jsonl(nodes_file)
    for node in nodes:
        node_id = str(node.get("id", ""))
        if node_id.startswith("proposal.") and node.get("status") == "verified":
            parts = node_id.split(".")
            if len(parts) >= 2 and parts[1].isdigit():
                proposal_id = int(parts[1])
                verified_proposal_ids[proposal_id] = node
                
    if not verified_proposal_ids:
        return []
        
    # 2. Read proposals
    proposals, _ = load_jsonl(proposals_file)
    modified = False
    messages = []
    
    for prop in proposals:
        prop_id = prop.get("id")
        if prop_id in verified_proposal_ids and prop.get("status") == "active":
            # Verification: run any tests in the evidence list
            node = verified_proposal_ids[prop_id]
            evidence = node.get("evidence", [])
            test_files = [ev for ev in evidence if ev.endswith(".py") and (ev.startswith("scratch/") or ev.startswith("tests/"))]
            
            tests_passed = True
            for test_file in test_files:
                test_path = root / test_file
                if test_path.exists():
                    # Run unittest on the file
                    cmd = [sys.executable, "-m", "unittest", test_file]
                    res = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
                    if res.returncode != 0:
                        tests_passed = False
                        messages.append(f"Verification failed for proposal {prop_id}: test {test_file} failed.")
                        break
            
            if tests_passed:
                # Transition status to done
                prop["status"] = "done"
                modified = True
                messages.append(f"Auto-transitioned proposal {prop_id} to done (verified by node {node['id']}).")
                
                # Append event
                new_event = {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "event": "memory.proposal.completed",
                    "node_id": node["id"],
                    "claim": f"Proposal {prop_id} completed and verified by tests: {', '.join(test_files) if test_files else 'no python tests'}",
                    "evidence": evidence,
                    "validator": "memory_os_audit_auto_proposals",
                    "status": "accepted"
                }
                
                # Write event to file
                with open(events_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(new_event) + "\n")
                    
    if modified:
        # Write proposals back
        with open(proposals_file, "w", encoding="utf-8") as f:
            for prop in proposals:
                f.write(json.dumps(prop, ensure_ascii=False, separators=(",", ":")) + "\n")
                
        # Update manifest
        try:
            from memory_os.modules.lifecycle import LifecycleManager
            LifecycleManager(config).manifest()
        except Exception:
            pass
            
    return messages


def audit(root: Path = ROOT) -> Dict[str, Any]:
    config_candidate = root / "memory_os.config.json"
    config = MemoryOSConfig(config_path=str(config_candidate) if config_candidate.exists() else None)
    if root != config.root_dir:
        config.root_dir = root
        
    capsules_path = config.capsules_file
    capsule_lines = read_text(capsules_path).splitlines()
    rows, jsonl_errors = load_jsonl(capsules_path)
    validation_errors = validate_rows(capsule_lines)
    
    auto_messages = auto_transition_proposals(root)
    
    report = {
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "root": str(root),
        "handshake": parse_handshake(read_text(config.root_dir / "agent_context" / "HANDSHAKE.md")),
        "workflows_contract_exists": (config.root_dir / "agent_context" / "WORKFLOWS.md").exists(),
        "capsules": summarize_capsules(rows),
        "capsule_jsonl_errors": jsonl_errors,
        "capsule_validation_errors": validation_errors,
        "proposal_validation_errors": validate_proposals_file(config.proposals_file),
        "memory_lifecycle": inspect_memory_lifecycle(root),
        "workflow_manifest": build_workflow_report(root),
        "roadmap": roadmap_system_status(read_text(config.root_dir / "agent_context" / "GLOBAL_ROADMAP.md")),
        "proposal_auto_transitions": auto_messages,
    }
    report["recommendations"] = build_recommendations(report)
    return report


def to_markdown(report: Dict[str, Any]) -> str:
    handshake = report["handshake"]
    capsules = report["capsules"]
    lines = [
        "# Memory OS Audit",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Active agent: {handshake.get('active_agent') or '-'}",
        f"- Budget tier: {handshake.get('budget_tier') or '-'}",
        f"- Target command: {handshake.get('target_command') or '-'}",
        f"- Capsules: {capsules['total']} total, {capsules['missing_metadata_count']} legacy/missing workflow metadata",
        f"- Latest capsule: {capsules['latest_task']} ({capsules['latest_workflow']} / {capsules['latest_step']})",
        f"- Capsule validation errors: {len(report['capsule_validation_errors'])}",
        f"- Proposal validation errors: {len(report.get('proposal_validation_errors', []))}",
        f"- Workflow manifest ok: {str(report.get('workflow_manifest', {}).get('ok', False)).lower()}",
        f"- Roadmap memory_os open items: {len(report['roadmap']['open'])}",
        "",
        "## Recommendations",
    ]
    lines.extend(f"- {item}" for item in report["recommendations"])
    
    if report.get("proposal_auto_transitions"):
        lines.append("")
        lines.append("## Proposal Auto-Transitions")
        lines.extend(f"- {msg}" for msg in report["proposal_auto_transitions"])
        
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Memory OS workflow and capsule state.")
    parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    parser.add_argument("--root", default=str(ROOT), help="Project root")
    args = parser.parse_args()

    report = audit(Path(args.root).resolve())
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(to_markdown(report))
    return 1 if report["capsule_validation_errors"] or report["capsule_jsonl_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
