"""Deterministic CI/PR Verification Gate for AI-assisted Pull Requests.

Runs 100% locally inside the caller's CI runner (zero source code leaves the
repository). Verifies command evidence, secret/injection hygiene (with optional
SARIF 2.1.0 export), and diff blast radius, then emits a merge-blocking verdict
and optional Markdown PR summary.

Usage:
    python -m memory_os.toolkit.ci_gate --root . --task-id <id> [--sarif-out report.sarif]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.evidence import EvidenceStore
from memory_os.core.licensing import LicenseConfig, LicenseManager, LicenseStatus
from memory_os.core.security_scan import SecurityScanner, to_sarif
from memory_os.toolkit.review_pack import change_size_report


@dataclass
class GateCheck:
    name: str
    ok: bool
    detail: str
    blocking: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "blocking": self.blocking,
        }


@dataclass
class CIGateOptions:
    task_id: Optional[str] = None
    require_evidence: bool = True
    security_profile: str = "default"
    max_changed_files: Optional[int] = None
    sarif_out: Optional[Path] = None
    pr_comment_out: Optional[Path] = None
    fail_on_warnings: bool = False


class CIGateRunner:
    """Runs deterministic verification gates for CI/CD pull requests."""

    def __init__(
        self,
        config: MemoryOSConfig,
        license_manager: Optional[LicenseManager] = None,
    ):
        self.config = config
        self.license_manager = license_manager or LicenseManager(LicenseConfig(product_slug="memory_os"))

    def run(self, options: Optional[CIGateOptions] = None) -> Dict[str, Any]:
        opts = options or CIGateOptions()
        lic_status = self.license_manager.verify()
        checks: List[GateCheck] = []
        artifacts_written: List[str] = []
        gated_features: List[str] = []

        # 1. Deterministic Evidence Verification
        evidence_check, resolved_task_id = self._run_evidence_check(
            task_id=opts.task_id,
            require_evidence=opts.require_evidence,
        )
        checks.append(evidence_check)

        # 2. Offline Security Scan (+ optional SARIF 2.1.0 export for Pro/Team)
        scan_result = SecurityScanner(self.config).scan(profile=opts.security_profile)
        finding_count = len(scan_result.get("findings", []))
        checks.append(
            GateCheck(
                name="security-scan",
                ok=finding_count == 0,
                detail=(
                    f"0 findings across {len(scan_result.get('scanned_files', []))} file(s) "
                    f"(profile={opts.security_profile})"
                    if finding_count == 0
                    else (
                        f"{finding_count} finding(s): {scan_result.get('secret_count', 0)} secret(s), "
                        f"{scan_result.get('injection_marker_count', 0)} prompt-injection marker(s)"
                    )
                ),
                blocking=True,
            )
        )

        if opts.sarif_out is not None:
            if lic_status.has_feature("sarif_export"):
                sarif_doc = to_sarif(scan_result)
                out_path = Path(opts.sarif_out)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(sarif_doc, indent=2) + "\n", encoding="utf-8")
                artifacts_written.append(str(out_path))
            else:
                gated_features.append("sarif_export (requires Pro/Team license)")

        # 3. Blast-Radius / Change-Size Guard
        size_info = change_size_report(self.config)
        changed_count = int(size_info.get("changed_file_count", 0))
        size_warnings = list(size_info.get("warnings", []))
        if opts.max_changed_files is not None and changed_count > opts.max_changed_files:
            checks.append(
                GateCheck(
                    name="change-size-limit",
                    ok=False,
                    detail=f"{changed_count} changed file(s) exceeds max_changed_files={opts.max_changed_files}",
                    blocking=True,
                )
            )
        else:
            checks.append(
                GateCheck(
                    name="change-size",
                    ok=not size_warnings,
                    detail=(
                        f"{changed_count} changed file(s) within batch limits"
                        if not size_warnings
                        else f"{changed_count} changed file(s): " + "; ".join(size_warnings[:3])
                    ),
                    blocking=opts.fail_on_warnings,
                )
            )

        blocking_failures = [c for c in checks if not c.ok and c.blocking]
        warnings = [c for c in checks if not c.ok and not c.blocking]
        passed = not blocking_failures

        report: Dict[str, Any] = {
            "ok": passed,
            "verdict": "PASS" if passed else "BLOCK",
            "task_id": resolved_task_id,
            "license": {
                "tier": lic_status.tier,
                "provider": lic_status.provider,
                "valid": lic_status.valid,
            },
            "blocking_failures": len(blocking_failures),
            "warnings": len(warnings),
            "checks": [c.to_dict() for c in checks],
            "artifacts_written": artifacts_written,
            "gated_features": gated_features,
        }

        if opts.pr_comment_out is not None:
            if lic_status.has_feature("pr_comment"):
                md = render_pr_comment(report)
                comment_path = Path(opts.pr_comment_out)
                comment_path.parent.mkdir(parents=True, exist_ok=True)
                comment_path.write_text(md, encoding="utf-8")
                artifacts_written.append(str(comment_path))
            else:
                gated_features.append("pr_comment (requires Team license)")

        return report

    def _run_evidence_check(
        self,
        *,
        task_id: Optional[str],
        require_evidence: bool,
    ) -> tuple[GateCheck, Optional[str]]:
        store = EvidenceStore(self.config)
        resolved = task_id or self._discover_latest_task_id()

        if not resolved:
            if require_evidence:
                return (
                    GateCheck(
                        name="evidence-verify",
                        ok=False,
                        detail="no evidence bundle found — AI/PR changes cannot be marked done without verified command evidence",
                        blocking=True,
                    ),
                    None,
                )
            return (
                GateCheck(
                    name="evidence-verify",
                    ok=True,
                    detail="evidence check skipped (require_evidence=False and no bundle present)",
                    blocking=False,
                ),
                None,
            )

        try:
            verdict = store.verify(resolved)
        except FileNotFoundError:
            return (
                GateCheck(
                    name="evidence-verify",
                    ok=not require_evidence,
                    detail=f"evidence bundle not found for task '{resolved}'",
                    blocking=require_evidence,
                ),
                resolved,
            )

        ok = bool(verdict.get("ok", False))
        reasons = verdict.get("reasons", [])
        detail = (
            f"evidence verified for task '{resolved}'"
            if ok
            else f"task '{resolved}' failed evidence gate: " + "; ".join(reasons)
        )
        return GateCheck(name="evidence-verify", ok=ok, detail=detail, blocking=True), resolved

    def _discover_latest_task_id(self) -> Optional[str]:
        evidence_dir = self.config.root_dir / "agent_context" / "evidence"
        if not evidence_dir.is_dir():
            return None
        bundles = sorted(
            evidence_dir.glob("*/bundle.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return bundles[0].parent.name if bundles else None


def render_pr_comment(report: Dict[str, Any]) -> str:
    """Render a concise, zero-noise Markdown PR verification summary."""
    verdict = report.get("verdict", "BLOCK")
    badge = "PASS" if verdict == "PASS" else "BLOCKED"
    lines = [
        f"## Memory OS Verification Gate: **{badge}**",
        "",
        "| Check | Status | Detail |",
        "| :--- | :--- | :--- |",
    ]
    for chk in report.get("checks", []):
        status_label = "PASS" if chk["ok"] else ("FAIL (blocking)" if chk["blocking"] else "WARN")
        detail = str(chk["detail"]).replace("|", "\\|")
        lines.append(f"| `{chk['name']}` | **{status_label}** | {detail} |")

    lines.append("")
    if report.get("task_id"):
        lines.append(f"- **Evidence Task:** `{report['task_id']}`")
    lic = report.get("license", {})
    lines.append(f"- **Tier:** `{lic.get('tier', 'core')}` (100% local runner execution — zero source code uploaded)")
    if report.get("gated_features"):
        lines.append(f"- **Locked Features:** {', '.join(report['gated_features'])}")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Memory OS deterministic CI/PR verification gate.")
    parser.add_argument("--root", default=".", help="Repository root directory.")
    parser.add_argument("--config", default=None, help="Optional path to memory_os.config.json.")
    parser.add_argument("--task-id", default=None, help="Evidence task ID to verify (defaults to latest bundle).")
    parser.add_argument("--no-require-evidence", action="store_true", help="Allow passing when no evidence bundle exists.")
    parser.add_argument("--security-profile", default="default", choices=sorted(SecurityScanner.VALID_PROFILES))
    parser.add_argument("--max-changed-files", type=int, default=None, help="Block PR if changed files exceed this count.")
    parser.add_argument("--sarif-out", default=None, help="Write SARIF 2.1.0 report to this path (Pro/Team).")
    parser.add_argument("--pr-comment-out", default=None, help="Write Markdown PR comment to this path (Team).")
    parser.add_argument("--fail-on-warnings", action="store_true", help="Treat non-blocking warnings as failures.")
    parser.add_argument("--format", choices={"json", "markdown", "text"}, default="text")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    cfg_path = args.config or str(root / "memory_os.config.json")
    config = MemoryOSConfig(cfg_path)
    runner = CIGateRunner(config)
    report = runner.run(
        CIGateOptions(
            task_id=args.task_id,
            require_evidence=not args.no_require_evidence,
            security_profile=args.security_profile,
            max_changed_files=args.max_changed_files,
            sarif_out=Path(args.sarif_out) if args.sarif_out else None,
            pr_comment_out=Path(args.pr_comment_out) if args.pr_comment_out else None,
            fail_on_warnings=args.fail_on_warnings,
        )
    )

    if args.format == "json":
        print(json.dumps(report, indent=2))
    elif args.format == "markdown":
        print(render_pr_comment(report))
    else:
        print(f"Memory OS CI Gate: {report['verdict']} (failures={report['blocking_failures']}, warnings={report['warnings']})")
        for chk in report["checks"]:
            state = "OK" if chk["ok"] else ("FAIL" if chk["blocking"] else "WARN")
            print(f"  [{state}] {chk['name']}: {chk['detail']}")
        if report["gated_features"]:
            print("  [LOCKED] " + ", ".join(report["gated_features"]))

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
