"""Unit tests for deterministic Skeptic Adversarial Auditor and Proof Benchmark."""

from __future__ import annotations

from pathlib import Path

from memory_os.toolkit.skeptic_audit import (
    audit_python_source,
    run_skeptic_audit,
    skeptic_to_markdown,
)


def test_skeptic_flags_bare_except_and_silent_pass():
    code = """
def risky(x):
    try:
        return int(x)
    except:
        return 0

def swallowed(x):
    try:
        return int(x)
    except Exception:
        pass
"""
    findings = audit_python_source(code, "src/app.py")
    rules = [(f.rule, f.severity) for f in findings]
    assert ("silent-except", "error") in rules
    assert ("silent-except", "warning") in rules


def test_skeptic_flags_empty_test_and_passes_real_test():
    bad_test = """
def test_fake_illusion():
    x = 2 + 2
    return x
"""
    good_test = """
import pytest

def test_real_assertion():
    assert 2 + 2 == 4

def test_raises_check():
    with pytest.raises(ValueError):
        int("nope")
"""
    bad_findings = audit_python_source(bad_test, "tests/test_sample.py")
    assert any(f.rule == "empty-test" and f.severity == "error" for f in bad_findings)

    good_findings = audit_python_source(good_test, "tests/test_sample.py")
    assert good_findings == []


def test_skeptic_flags_risky_exec_and_debug_leftover():
    code = """
import subprocess

def run_cmd(cmd):
    breakpoint()
    return subprocess.run(cmd, shell=True)
"""
    findings = audit_python_source(code, "src/runner.py")
    rules = {f.rule for f in findings}
    assert "risky-exec" in rules
    assert "debug-leftover" in rules


def test_skeptic_warns_when_src_changed_without_tests(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "clean.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    report = run_skeptic_audit(tmp_path, ["src/clean.py"])
    assert report["ok"] is True
    assert report["warning_count"] == 1
    assert report["findings"][0]["rule"] == "source-without-tests"
    md = skeptic_to_markdown(report)
    assert "Skeptic Adversarial Audit: **PASS**" in md
