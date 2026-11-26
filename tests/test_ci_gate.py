"""Unit tests for SARIF 2.1.0 security export and CI/PR Verification Gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from memory_os.core.config import MemoryOSConfig
from memory_os.core.evidence import EvidenceStore
from memory_os.core.licensing import LicenseConfig, LicenseManager
from memory_os.core.security_scan import SecurityScanner, to_sarif
from memory_os.toolkit.ci_gate import CIGateOptions, CIGateRunner, render_pr_comment


def _make_repo(tmp_path: Path) -> MemoryOSConfig:
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "memory" / "nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "edges.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "events.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "agent_context" / "task_capsules.jsonl").write_text("", encoding="utf-8")
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(
        json.dumps({"memory_dir": "memory", "db_path": "memory/memory_os.db"}),
        encoding="utf-8",
    )
    return MemoryOSConfig(str(cfg_path))


def _record_passing_evidence(config: MemoryOSConfig, task_id: str = "pr-42") -> None:
    store = EvidenceStore(config)
    store.init(task_id=task_id, risk_class="low")
    store.add_command(task_id=task_id, command=[sys.executable, "-c", "print('ok')"])


def test_security_scan_to_sarif_schema(tmp_path: Path):
    config = _make_repo(tmp_path)
    (tmp_path / "memory" / "nodes.jsonl").write_text(
        '{"id":"n1","summary":"leaked key AKIAIOSFODNN7EXAMPLE"}\n',
        encoding="utf-8",
    )

    scan = SecurityScanner(config).scan(profile="default")
    sarif = to_sarif(scan)

    assert sarif["version"] == "2.1.0"
    assert len(sarif["runs"]) == 1
    results = sarif["runs"][0]["results"]
    assert len(results) >= 1
    assert results[0]["level"] == "error"
    assert results[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "memory/nodes.jsonl"


def test_ci_gate_blocks_when_evidence_missing(tmp_path: Path):
    config = _make_repo(tmp_path)
    mgr = LicenseManager(LicenseConfig(storage_path=tmp_path / "lic.json"))
    report = CIGateRunner(config, license_manager=mgr).run(CIGateOptions(require_evidence=True))

    assert report["ok"] is False
    assert report["verdict"] == "BLOCK"
    ev = next(c for c in report["checks"] if c["name"] == "evidence-verify")
    assert ev["ok"] is False


def test_ci_gate_passes_core_and_gates_pro_team_artifacts(tmp_path: Path):
    config = _make_repo(tmp_path)
    _record_passing_evidence(config, "pr-101")
    mgr = LicenseManager(LicenseConfig(storage_path=tmp_path / "lic.json"))

    sarif_path = tmp_path / "out" / "security.sarif"
    comment_path = tmp_path / "out" / "pr_comment.md"
    report = CIGateRunner(config, license_manager=mgr).run(
        CIGateOptions(
            task_id="pr-101",
            sarif_out=sarif_path,
            pr_comment_out=comment_path,
        )
    )

    assert report["ok"] is True
    assert report["verdict"] == "PASS"
    assert not sarif_path.exists()
    assert not comment_path.exists()
    assert any("sarif_export" in g for g in report["gated_features"])
    assert any("pr_comment" in g for g in report["gated_features"])


def test_ci_gate_team_license_writes_sarif_and_pr_comment(tmp_path: Path):
    config = _make_repo(tmp_path)
    _record_passing_evidence(config, "pr-202")
    lic_cfg = LicenseConfig(storage_path=tmp_path / "lic.json", sandbox=True)
    mgr = LicenseManager(lic_cfg)
    assert mgr.activate("SANDBOX-TEAM-999").valid is True

    sarif_path = tmp_path / "out" / "security.sarif"
    comment_path = tmp_path / "out" / "pr_comment.md"
    report = CIGateRunner(config, license_manager=mgr).run(
        CIGateOptions(
            task_id="pr-202",
            sarif_out=sarif_path,
            pr_comment_out=comment_path,
        )
    )

    assert report["ok"] is True
    assert sarif_path.is_file()
    assert comment_path.is_file()
    sarif_data = json.loads(sarif_path.read_text(encoding="utf-8"))
    assert sarif_data["version"] == "2.1.0"
    comment_text = comment_path.read_text(encoding="utf-8")
    assert "Memory OS Verification Gate: **PASS**" in comment_text
    assert "`pr-202`" in comment_text
    assert render_pr_comment(report) == comment_text


def test_ci_gate_cli_main_executes_cleanly(tmp_path: Path, capsys):
    from memory_os.toolkit.ci_gate import main as ci_gate_main

    config = _make_repo(tmp_path)
    _record_passing_evidence(config, "pr-cli-1")

    rc = ci_gate_main(["--root", str(tmp_path), "--task-id", "pr-cli-1", "--format", "json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["verdict"] == "PASS"
