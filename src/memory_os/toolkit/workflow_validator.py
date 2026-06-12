#!/usr/bin/env python3
"""Validate Memory OS workflow TOML specs against the 12-step contract."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_os import load_toml_file
from memory_os.toolkit.quantizer import LEVEL_SCALE


REQUIRED_FIELDS = {
    "id",
    "step_min",
    "step_max",
    "level_min",
    "level_max",
    "model_policy",
    "tools",
    "verification",
}
ALLOWED_MODEL_POLICIES = {"cheap_free", "codex", "strong_cloud", "large_reasoning"}


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def load_specs(root: Path = ROOT) -> Tuple[List[Dict[str, Any]], List[str]]:
    workflows_dir = root / "workflows"
    specs: List[Dict[str, Any]] = []
    errors: List[str] = []
    if not workflows_dir.exists():
        return specs, ["workflows/: directory not found"]

    for path in sorted(workflows_dir.glob("*.toml")):
        try:
            data = load_toml_file(str(path))
        except Exception as exc:
            errors.append(f"{path.relative_to(root)}: parse failed: {exc}")
            continue
        data["_path"] = str(path.relative_to(root))
        specs.append(data)
    if not specs:
        errors.append("workflows/: no .toml workflow specs found")
    return specs, errors


def validate_specs(specs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    specs = list(specs)
    errors: List[str] = []
    warnings: List[str] = []
    intervals = []

    # First pass: collect all valid IDs so escalation forward-references resolve correctly.
    all_ids: Dict[str, str] = {}
    for spec in specs:
        wid = str(spec.get("id") or "")
        path = spec.get("_path", "<unknown>")
        if wid:
            all_ids[wid] = path

    ids: Dict[str, str] = {}
    for spec in specs:
        path = spec.get("_path", "<unknown>")
        missing = sorted(REQUIRED_FIELDS - set(spec))
        for field in missing:
            errors.append(f"{path}: missing required field '{field}'")
        if missing:
            continue

        workflow_id = str(spec.get("id"))
        if workflow_id in ids:
            errors.append(f"{path}: duplicate workflow id '{workflow_id}' also in {ids[workflow_id]}")
        ids[workflow_id] = path

        step_min = _as_int(spec.get("step_min"))
        step_max = _as_int(spec.get("step_max"))
        level_min = _as_int(spec.get("level_min"))
        level_max = _as_int(spec.get("level_max"))
        if step_min is None or step_max is None:
            errors.append(f"{path}: step_min and step_max must be integers")
            continue
        if step_min < 0 or step_max > 13 or step_min > step_max:
            errors.append(f"{path}: step range must be inside 0..13 and min <= max")
        else:
            intervals.append((step_min, step_max, workflow_id, path))

        if level_min is None or level_max is None:
            errors.append(f"{path}: level_min and level_max must be integers")
        elif level_min < 1 or level_max > 100 or level_min > level_max:
            errors.append(f"{path}: level range must be inside 1..100 and min <= max")

        model_policy = str(spec.get("model_policy") or "")
        if model_policy not in ALLOWED_MODEL_POLICIES:
            errors.append(f"{path}: unsupported model_policy '{model_policy}'")

        if not isinstance(spec.get("tools"), list):
            errors.append(f"{path}: tools must be an array")
        if not isinstance(spec.get("verification"), list):
            errors.append(f"{path}: verification must be an array")

        target = ((spec.get("escalation") or {}).get("escalate_to") if isinstance(spec.get("escalation"), dict) else None)
        if target and target not in all_ids:
            warnings.append(f"{path}: escalation target '{target}' has no local spec")

    coverage = _coverage(intervals)
    missing_steps = [level for level in LEVEL_SCALE if level not in coverage]
    overlaps = [
        {"step": step, "workflow_ids": sorted(workflow_ids)}
        for step, workflow_ids in sorted(coverage.items())
        if len(workflow_ids) > 1
    ]
    if missing_steps:
        errors.append(f"workflow steps missing coverage: {missing_steps}")
    if overlaps:
        errors.append(f"workflow step overlaps: {overlaps}")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "coverage": {str(step): sorted(values) for step, values in sorted(coverage.items())},
        "missing_steps": missing_steps,
        "overlaps": overlaps,
    }


def build_report(root: Path = ROOT) -> Dict[str, Any]:
    specs, load_errors = load_specs(root)
    validation = validate_specs(specs)
    errors = load_errors + validation["errors"]
    workflows = [
        {
            "id": spec.get("id"),
            "path": spec.get("_path"),
            "step_min": spec.get("step_min"),
            "step_max": spec.get("step_max"),
            "level_min": spec.get("level_min"),
            "level_max": spec.get("level_max"),
            "model_policy": spec.get("model_policy"),
            "tools": spec.get("tools"),
            "verification": spec.get("verification"),
        }
        for spec in specs
    ]
    return {
        "generated_at": utc_now_iso(),
        "root": str(root),
        "ok": not errors,
        "step_scale": {str(score): name for score, name in LEVEL_SCALE.items()},
        "workflow_count": len(specs),
        "workflows": workflows,
        "coverage": validation["coverage"],
        "missing_steps": validation["missing_steps"],
        "overlaps": validation["overlaps"],
        "errors": errors,
        "warnings": validation["warnings"],
    }


def write_manifest(report: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def to_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Workflow Manifest",
        "",
        f"- Generated: {report['generated_at']}",
        f"- OK: {str(report['ok']).lower()}",
        f"- Workflows: {report['workflow_count']}",
        f"- Missing steps: {report['missing_steps'] or '-'}",
        f"- Overlaps: {report['overlaps'] or '-'}",
        "",
        "## Workflows",
    ]
    for workflow in report["workflows"]:
        lines.append(
            f"- {workflow['id']}: steps {workflow['step_min']}..{workflow['step_max']}, "
            f"levels {workflow['level_min']}..{workflow['level_max']}, policy {workflow['model_policy']}"
        )
    if report["warnings"]:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in report["warnings"])
    if report["errors"]:
        lines.extend(["", "## Errors"])
        lines.extend(f"- {error}" for error in report["errors"])
    return "\n".join(lines)


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coverage(intervals: Iterable[Tuple[int, int, str, str]]) -> Dict[int, set]:
    coverage: Dict[int, set] = {}
    for step_min, step_max, workflow_id, _path in intervals:
        for step in range(step_min, step_max + 1):
            coverage.setdefault(step, set()).add(workflow_id)
    return coverage


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Memory OS workflow TOML specs.")
    parser.add_argument("--root", default=str(ROOT), help="Project root")
    parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    parser.add_argument("--write-manifest", action="store_true", help="Write memory/workflow_manifest.json")
    parser.add_argument("--manifest-path", default="memory/workflow_manifest.json")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    report = build_report(root)
    if args.write_manifest:
        write_manifest(report, root / args.manifest_path)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(to_markdown(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
