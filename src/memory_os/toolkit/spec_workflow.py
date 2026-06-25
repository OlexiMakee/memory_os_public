#!/usr/bin/env python3
"""Spec-driven development workflow helpers.

This module adapts useful spec-kit ideas to Memory OS without depending on the
external specify CLI. It intentionally uses plain files and small operations so
the workflow remains inspectable, scriptable, and project-local.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from memory_os.core.safe_id import validate_safe_id


SPEC_TEMPLATE = """# Spec: {title}

Status: draft
Created: {date}
Feature: {feature_id}

## Goal

{description}

## User Stories

### User Story 1

As a <user or agent>, I want <capability>, so that <outcome>.

#### Acceptance Scenarios

- SC-001: Given <context>, when <action>, then <observable result>.

## Functional Requirements

- FR-001: The system MUST <required behavior>.

## Non-Functional Requirements

- NFR-001: The implementation MUST preserve existing public CLI behavior unless this spec explicitly changes it.
- NFR-002: The implementation MUST avoid new runtime dependencies unless justified in the plan.

## Edge Cases

- EC-001: <edge case and expected behavior>.

## Out Of Scope

- <explicitly excluded work>.

## Open Questions

- [NEEDS CLARIFICATION: Replace this with a concrete question, or delete this section when resolved.]
"""


PLAN_TEMPLATE = """# Plan: {title}

Status: draft
Feature: {feature_id}

## Technical Context

- Runtime:
- Data touched:
- Interfaces:
- Dependencies:

## Constitution Check

- [ ] Single responsibility: each changed module has one reason to change.
- [ ] Open/closed: extension points are used before changing stable contracts.
- [ ] Liskov/interface safety: existing callers keep working.
- [ ] Interface segregation: commands and helpers expose narrow responsibilities.
- [ ] Dependency inversion: high-level workflow code does not depend on concrete external tools.
- [ ] Unix fit: files are plain text, commands are composable, and structured output is available where useful.

## Architecture

Describe the minimal design. Prefer small modules, file-backed contracts, and
clear boundaries over broad rewrites.

## Verification Plan

- Command:
- Expected result:

## Migration And Compatibility

- Existing behavior preserved:
- Backward-compatible data changes:
- Rollback path:

## Complexity Ledger

List every added abstraction or dependency and why it is justified.
"""


TASKS_TEMPLATE = """# Tasks: {title}

Status: draft
Feature: {feature_id}

## Tasks

- [ ] T001 [P] Write or update focused tests for FR-001.
- [ ] T002 Implement the smallest code path for FR-001.
- [ ] T003 Run the verification plan and record evidence.

## Traceability

| Requirement | Tasks | Evidence |
| --- | --- | --- |
| FR-001 | T001, T002, T003 | pending |
"""


CHECKLIST_TEMPLATE = """# Checklist: {title}

Status: draft
Feature: {feature_id}

## Quality Gates

- [ ] Spec has no `[NEEDS CLARIFICATION: ...]` markers.
- [ ] Functional requirements are numbered as `FR-001`, `FR-002`, ...
- [ ] Acceptance scenarios are numbered as `SC-001`, `SC-002`, ...
- [ ] Plan includes a constitution check.
- [ ] Tasks reference requirements and are independently verifiable.
- [ ] Verification commands are recorded before implementation is called done.
- [ ] No secrets, tokens, raw logs, or credential values are stored in the spec.
"""


CONSTITUTION_TEMPLATE = """# Memory OS Development Constitution

Status: mandatory.

## Principles

1. Toolkit, not only memory.
   Memory OS exists to improve development quality: planning, context, review,
   verification, retrieval, and repeatable agent workflows.

2. Plain files first.
   Durable control-plane state should be inspectable text where possible:
   markdown, JSON, JSONL, TOML. Opaque stores are indexes or caches, not the
   source of truth.

3. SOLID boundaries.
   Keep orchestration, storage, validation, UI, and provider integrations in
   separate modules. Add interfaces before binding core code to a concrete
   external tool.

4. Unix-shaped commands.
   Commands should do one thing, support dry-run for writes when meaningful,
   and expose structured output for automation.

5. Verification before confidence.
   Specs, plans, tasks, tests, and evidence must trace to each other. Checked
   handoff items are not trusted until artifacts are verified.

6. Backward compatibility by default.
   CLI flags, JSONL schemas, and public file layouts should keep old callers
   working. New schema fields require defaults.

7. No secret capture.
   Specs, memory nodes, telemetry, and handoffs must not store raw secrets,
   tokens, credential values, or secret-bearing logs.
"""


@dataclass(frozen=True)
class SpecPaths:
    feature_id: str
    root: Path
    spec: Path
    plan: Path
    tasks: Path
    checklist: Path

    def to_dict(self, base: Path) -> Dict[str, str]:
        return {
            "feature_id": self.feature_id,
            "root": str(self.root.relative_to(base)),
            "spec": str(self.spec.relative_to(base)),
            "plan": str(self.plan.relative_to(base)),
            "tasks": str(self.tasks.relative_to(base)),
            "checklist": str(self.checklist.relative_to(base)),
        }


class SpecManager:
    """Manage project-local spec workflow files."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.specs_dir = self.root / "specs"
        self.constitution_path = self.root / "agent_context" / "CONSTITUTION.md"

    def init_feature(
        self,
        title: str,
        description: str = "",
        feature_id: Optional[str] = None,
        force: bool = False,
    ) -> SpecPaths:
        feature_id = validate_safe_id(feature_id or self._next_feature_id(title), "feature id")
        feature_root = self.specs_dir / feature_id
        if feature_root.exists() and not force:
            raise FileExistsError(f"{feature_root.relative_to(self.root)} already exists")
        feature_root.mkdir(parents=True, exist_ok=True)

        context = {
            "title": title.strip(),
            "description": description.strip() or "[NEEDS CLARIFICATION: Describe the user-visible goal.]",
            "date": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "feature_id": feature_id,
        }
        paths = self._paths(feature_root)
        self._write_template(paths.spec, SPEC_TEMPLATE, context, force)
        self._write_template(paths.plan, PLAN_TEMPLATE, context, force)
        self._write_template(paths.tasks, TASKS_TEMPLATE, context, force)
        self._write_template(paths.checklist, CHECKLIST_TEMPLATE, context, force)
        return paths

    def ensure_constitution(self, force: bool = False) -> Path:
        if self.constitution_path.exists() and not force:
            return self.constitution_path
        self.constitution_path.parent.mkdir(parents=True, exist_ok=True)
        self.constitution_path.write_text(CONSTITUTION_TEMPLATE, encoding="utf-8")
        return self.constitution_path

    def list_features(self) -> List[Dict[str, str]]:
        if not self.specs_dir.exists():
            return []
        items = []
        for path in sorted(p for p in self.specs_dir.iterdir() if p.is_dir()):
            items.append({"feature_id": path.name, "path": str(path.relative_to(self.root))})
        return items

    def analyze(self, feature: Optional[str] = None) -> Dict[str, Any]:
        feature_root = self._resolve_feature(feature)
        errors: List[str] = []
        warnings: List[str] = []
        files: Dict[str, str] = {}

        if feature_root is None:
            errors.append("No specs found. Run `memory_os spec init \"<title>\"` first.")
            return self._report(None, files, errors, warnings, [], [], [])

        paths = self._paths(feature_root)
        for name, path in {
            "spec": paths.spec,
            "plan": paths.plan,
            "tasks": paths.tasks,
            "checklist": paths.checklist,
        }.items():
            files[name] = str(path.relative_to(self.root))
            if not path.exists():
                errors.append(f"{files[name]} is missing")

        if not self.constitution_path.exists():
            warnings.append("agent_context/CONSTITUTION.md is missing; run `memory_os spec constitution`.")

        spec_text = self._read(paths.spec)
        plan_text = self._read(paths.plan)
        tasks_text = self._read(paths.tasks)
        checklist_text = self._read(paths.checklist)

        blockers = self._clarification_markers(spec_text + plan_text + tasks_text)
        errors.extend(f"Unresolved clarification marker: {marker}" for marker in blockers)

        requirements = sorted(set(re.findall(r"\bFR-\d{3}\b", spec_text)))
        scenarios = sorted(set(re.findall(r"\bSC-\d{3}\b", spec_text)))
        task_ids = sorted(set(re.findall(r"\bT\d{3}\b", tasks_text)))

        if not requirements:
            errors.append("spec.md has no functional requirements like FR-001")
        if not scenarios:
            errors.append("spec.md has no acceptance scenarios like SC-001")
        if "## User Stories" not in spec_text:
            errors.append("spec.md is missing a User Stories section")
        if "## Edge Cases" not in spec_text:
            warnings.append("spec.md is missing an Edge Cases section")

        for heading in ("## Constitution Check", "## Technical Context", "## Verification Plan", "## Complexity Ledger"):
            if heading not in plan_text:
                errors.append(f"plan.md is missing {heading}")

        if not task_ids:
            errors.append("tasks.md has no task IDs like T001")
        if not re.search(r"^- \[[ xX]\] T\d{3}", tasks_text, flags=re.MULTILINE):
            errors.append("tasks.md tasks must use checklist rows like `- [ ] T001 ...`")

        for req in requirements:
            if req not in tasks_text:
                warnings.append(f"{req} is not referenced in tasks.md")

        if "- [ ]" not in checklist_text and "- [x]" not in checklist_text.lower():
            errors.append("checklist.md has no checklist items")

        return self._report(paths, files, errors, warnings, requirements, scenarios, task_ids)

    def _paths(self, feature_root: Path) -> SpecPaths:
        return SpecPaths(
            feature_id=feature_root.name,
            root=feature_root,
            spec=feature_root / "spec.md",
            plan=feature_root / "plan.md",
            tasks=feature_root / "tasks.md",
            checklist=feature_root / "checklist.md",
        )

    def _next_feature_id(self, title: str) -> str:
        self.specs_dir.mkdir(parents=True, exist_ok=True)
        numbers = []
        for path in self.specs_dir.iterdir():
            if path.is_dir():
                match = re.match(r"^(\d{3})-", path.name)
                if match:
                    numbers.append(int(match.group(1)))
        return f"{(max(numbers) + 1 if numbers else 1):03d}-{self._slug(title)}"

    def _resolve_feature(self, feature: Optional[str]) -> Optional[Path]:
        if not self.specs_dir.exists():
            return None
        dirs = sorted((p for p in self.specs_dir.iterdir() if p.is_dir()), reverse=True)
        if not dirs:
            return None
        if not feature:
            return dirs[0]
        validate_safe_id(feature, "feature selector")
        exact = self.specs_dir / feature
        if exact.is_dir():
            return exact
        matches = [p for p in dirs if p.name.startswith(feature)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"Feature selector '{feature}' is ambiguous")
        raise FileNotFoundError(f"No spec matches '{feature}'")

    def build_contract(self, feature: Optional[str] = None, risk_class: Optional[str] = None) -> Dict[str, Any]:
        """Derive a machine-readable contract from existing spec/plan artifacts. No LLM call."""
        feature_root = self._resolve_feature(feature)
        if feature_root is None:
            raise FileNotFoundError("No specs found. Run `memory_os spec init \"<title>\"` first.")
        paths = self._paths(feature_root)
        spec_text = self._read(paths.spec)
        plan_text = self._read(paths.plan)

        title_match = re.search(r"^# Spec:[ \t]*(.*)$", spec_text, flags=re.MULTILINE)
        title = title_match.group(1).strip() if title_match and title_match.group(1).strip() else paths.feature_id

        rollback = self._section_field(plan_text, "Rollback path")
        complexity_items = self._section_bullets(plan_text, "## Complexity Ledger")

        return {
            "feature_id": paths.feature_id,
            "title": title,
            "risk_class": risk_class or self._infer_risk_class(rollback, complexity_items),
            "objective": self._section_body(spec_text, "## Goal"),
            "non_goals": self._section_bullets(spec_text, "## Out Of Scope"),
            "inputs_and_outputs": self._section_bullets(spec_text, "## Functional Requirements"),
            "constraints": self._section_bullets(spec_text, "## Non-Functional Requirements"),
            "acceptance_criteria": self._section_bullets(spec_text, "#### Acceptance Scenarios"),
            "required_verification": self._section_body(plan_text, "## Verification Plan"),
            "required_context_sources": [
                str(p.relative_to(self.root))
                for p in (paths.spec, paths.plan, paths.tasks, paths.checklist, self.constitution_path)
                if p.exists()
            ],
            "rollback_plan": rollback or "[NOT FOUND: plan.md Migration And Compatibility / Rollback path is empty]",
        }

    def write_contract(
        self,
        feature: Optional[str] = None,
        risk_class: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        contract = self.build_contract(feature, risk_class)
        feature_root = self.specs_dir / contract["feature_id"]
        json_path = feature_root / "contract.json"
        md_path = feature_root / "contract.md"

        if force or not json_path.exists():
            json_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
        if force or not md_path.exists():
            md_path.write_text(contract_to_markdown(contract), encoding="utf-8")

        contract["contract_json"] = str(json_path.relative_to(self.root))
        contract["contract_md"] = str(md_path.relative_to(self.root))
        return contract

    @staticmethod
    def _infer_risk_class(rollback: str, complexity_items: List[str]) -> str:
        """Deterministic heuristic — no LLM call. Callers can always override explicitly."""
        if rollback and "[NOT FOUND" not in rollback:
            return "migration-risk"
        if complexity_items:
            return "moderate"
        return "low"

    @staticmethod
    def _section_body(text: str, heading: str) -> str:
        """Return the body text directly under `heading` up to the next heading of equal-or-higher level."""
        level = len(heading) - len(heading.lstrip("#"))
        pattern = re.compile(
            rf"^{re.escape(heading)}\s*$\n(.*?)(?=^#{{1,{level}}}\s|\Z)",
            flags=re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _section_bullets(text: str, heading: str) -> List[str]:
        """Return top-level '- ' bullet lines directly under `heading`."""
        body = SpecManager._section_body(text, heading)
        return [line[2:].strip() for line in body.splitlines() if line.strip().startswith("- ")]

    @staticmethod
    def _section_field(text: str, label: str) -> str:
        """Return the value after a '- {label}:' line anywhere in the document."""
        # [ \t]* (not \s*) so this never crosses a newline into the next line/heading
        # when the field is left blank in the template.
        match = re.search(rf"^-[ \t]*{re.escape(label)}:[ \t]*(.*)$", text, flags=re.MULTILINE)
        return match.group(1).strip() if match else ""

    def _write_template(self, path: Path, template: str, context: Dict[str, str], force: bool) -> None:
        if path.exists() and not force:
            return
        path.write_text(template.format(**context), encoding="utf-8")

    def _read(self, path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")

    def _clarification_markers(self, text: str) -> List[str]:
        return re.findall(r"\[NEEDS CLARIFICATION:[^\]]+\]", text)

    def _slug(self, title: str) -> str:
        parts = re.findall(r"[A-Za-z0-9]+", title.lower())
        return "-".join(parts[:8]) or "feature"

    def _report(
        self,
        paths: Optional[SpecPaths],
        files: Dict[str, str],
        errors: List[str],
        warnings: List[str],
        requirements: List[str],
        scenarios: List[str],
        tasks: List[str],
    ) -> Dict[str, Any]:
        return {
            "ok": not errors,
            "feature_id": paths.feature_id if paths else None,
            "files": files,
            "requirements": requirements,
            "scenarios": scenarios,
            "tasks": tasks,
            "errors": errors,
            "warnings": warnings,
        }


def report_to_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Spec Analysis",
        "",
        f"- OK: {str(report['ok']).lower()}",
        f"- Feature: {report.get('feature_id') or '-'}",
        f"- Requirements: {', '.join(report.get('requirements') or []) or '-'}",
        f"- Scenarios: {', '.join(report.get('scenarios') or []) or '-'}",
        f"- Tasks: {', '.join(report.get('tasks') or []) or '-'}",
    ]
    if report.get("warnings"):
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in report["warnings"])
    if report.get("errors"):
        lines.extend(["", "## Errors"])
        lines.extend(f"- {error}" for error in report["errors"])
    return "\n".join(lines)


def contract_to_markdown(contract: Dict[str, Any]) -> str:
    def bullets(items: Iterable[str]) -> List[str]:
        items = list(items)
        return [f"- {item}" for item in items] if items else ["- (none found)"]

    lines = [
        f"# Contract: {contract['title']}",
        "",
        "Status: generated from existing spec/plan artifacts. No LLM call required.",
        f"Feature: {contract['feature_id']}",
        f"Risk class: {contract['risk_class']}",
        "",
        "## Objective",
        "",
        contract["objective"] or "[NOT FOUND: spec.md Goal section is empty]",
        "",
        "## Non-Goals",
        "",
        *bullets(contract["non_goals"]),
        "",
        "## Inputs And Outputs",
        "",
        "Derived from Functional Requirements (spec.md):",
        "",
        *bullets(contract["inputs_and_outputs"]),
        "",
        "## Constraints",
        "",
        "Derived from Non-Functional Requirements (spec.md):",
        "",
        *bullets(contract["constraints"]),
        "",
        "## Acceptance Criteria",
        "",
        "Derived from Acceptance Scenarios (spec.md):",
        "",
        *bullets(contract["acceptance_criteria"]),
        "",
        "## Required Verification",
        "",
        "Derived from the Verification Plan (plan.md):",
        "",
        contract["required_verification"] or "[NOT FOUND: plan.md Verification Plan section is empty]",
        "",
        "## Required Context Sources",
        "",
        *bullets(contract["required_context_sources"]),
        "",
        "## Rollback Plan",
        "",
        "Derived from Migration And Compatibility (plan.md):",
        "",
        contract["rollback_plan"],
        "",
    ]
    return "\n".join(lines)
