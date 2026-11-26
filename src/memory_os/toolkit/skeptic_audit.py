"""Deterministic Skeptic / Adversarial Diff Auditor for AI-generated PRs.

Catches common 'First-Pass Illusion' failure modes produced by autonomous coding
agents with zero LLM calls and zero hallucinations:
  - silent-except: bare `except:` or `except Exception: pass` swallowing errors
  - empty-test: `test_*` functions lacking assertions or `pytest.raises`
  - risky-exec: `eval()`, `exec()`, or `subprocess(..., shell=True)`
  - stub-body: functions raising `NotImplementedError` or containing only `pass`/`...`
  - debug-leftover: `breakpoint()` or `pdb.set_trace()`
  - source-without-tests: changes under `src/` with no accompanying test file changes
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class SkepticFinding:
    rule: str
    severity: str  # "error" | "warning"
    file: str
    line: int
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "message": self.message,
        }


def _is_test_file(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/")
    name = Path(norm).name
    return (
        norm.startswith("tests/")
        or "/tests/" in norm
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.ts")
        or name.endswith(".spec.ts")
    )


def _is_noop_body(body: Sequence[ast.stmt]) -> bool:
    stmts = list(body)
    if stmts and isinstance(stmts[0], ast.Expr) and isinstance(stmts[0].value, ast.Constant) and isinstance(stmts[0].value.value, str):
        stmts = stmts[1:]
    if not stmts:
        return True
    if len(stmts) == 1:
        only = stmts[0]
        if isinstance(only, ast.Pass):
            return True
        if isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant) and only.value.value is Ellipsis:
            return True
    return False


def _test_func_has_assertion(func_node: ast.AST) -> bool:
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute):
                if fn.attr.startswith("assert") or fn.attr in {"raises", "warns", "fail", "xfail"}:
                    return True
            elif isinstance(fn, ast.Name) and fn.id in {"raises", "fail"}:
                return True
    return False


def audit_python_source(source: str, rel_path: str) -> List[SkepticFinding]:
    """Run deterministic AST skeptic checks on a single Python file."""
    findings: List[SkepticFinding] = []
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError as exc:
        findings.append(
            SkepticFinding(
                rule="syntax-error",
                severity="error",
                file=rel_path,
                line=int(exc.lineno or 1),
                message=f"Python syntax error: {exc.msg}",
            )
        )
        return findings

    is_test = _is_test_file(rel_path)

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                findings.append(
                    SkepticFinding(
                        rule="silent-except",
                        severity="error",
                        file=rel_path,
                        line=getattr(node, "lineno", 1),
                        message="bare 'except:' clause hides unexpected failures",
                    )
                )
            elif _is_noop_body(node.body):
                findings.append(
                    SkepticFinding(
                        rule="silent-except",
                        severity="warning",
                        file=rel_path,
                        line=getattr(node, "lineno", 1),
                        message="exception handler silently swallows errors with pass/ellipsis",
                    )
                )

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if is_test and node.name.startswith("test_"):
                if not _test_func_has_assertion(node):
                    findings.append(
                        SkepticFinding(
                            rule="empty-test",
                            severity="error",
                            file=rel_path,
                            line=getattr(node, "lineno", 1),
                            message=f"test '{node.name}' has no assertions or pytest.raises check",
                        )
                    )
            elif not is_test and not node.name.startswith("_"):
                if _is_noop_body(node.body):
                    findings.append(
                        SkepticFinding(
                            rule="stub-body",
                            severity="warning",
                            file=rel_path,
                            line=getattr(node, "lineno", 1),
                            message=f"public function '{node.name}' has an empty stub body",
                        )
                    )

        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in {"eval", "exec"}:
                findings.append(
                    SkepticFinding(
                        rule="risky-exec",
                        severity="error",
                        file=rel_path,
                        line=getattr(node, "lineno", 1),
                        message=f"dynamic code execution via '{fn.id}()'",
                    )
                )
            elif isinstance(fn, ast.Name) and fn.id == "breakpoint":
                findings.append(
                    SkepticFinding(
                        rule="debug-leftover",
                        severity="error",
                        file=rel_path,
                        line=getattr(node, "lineno", 1),
                        message="debug breakpoint() left in code",
                    )
                )
            elif isinstance(fn, ast.Attribute) and fn.attr == "set_trace":
                findings.append(
                    SkepticFinding(
                        rule="debug-leftover",
                        severity="error",
                        file=rel_path,
                        line=getattr(node, "lineno", 1),
                        message="pdb.set_trace() left in code",
                    )
                )
            elif isinstance(fn, ast.Attribute) and fn.attr in {"run", "Popen", "call", "check_call", "check_output"}:
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        findings.append(
                            SkepticFinding(
                                rule="risky-exec",
                                severity="error",
                                file=rel_path,
                                line=getattr(node, "lineno", 1),
                                message=f"subprocess.{fn.attr}(..., shell=True) introduces command injection risk",
                            )
                        )

    return findings


def run_skeptic_audit(root: Path, files: Iterable[str]) -> Dict[str, Any]:
    """Audit a batch of changed/target files and return a structured report."""
    root_resolved = Path(root).resolve()
    rel_files = sorted(set(str(f).replace("\\", "/") for f in files if str(f).strip()))
    findings: List[SkepticFinding] = []
    audited_python = 0

    for rel in rel_files:
        full_path = (root_resolved / rel).resolve()
        if not full_path.is_relative_to(root_resolved):
            findings.append(
                SkepticFinding(
                    rule="path-traversal",
                    severity="error",
                    file=rel,
                    line=1,
                    message="path escapes repository root",
                )
            )
            continue
        if not full_path.is_file() or full_path.suffix != ".py":
            continue
        audited_python += 1
        source = full_path.read_text(encoding="utf-8", errors="ignore")
        findings.extend(audit_python_source(source, rel))

    src_changes = [f for f in rel_files if f.startswith("src/") and f.endswith(".py") and not _is_test_file(f)]
    test_changes = [f for f in rel_files if _is_test_file(f)]
    if src_changes and not test_changes:
        findings.append(
            SkepticFinding(
                rule="source-without-tests",
                severity="warning",
                file=src_changes[0],
                line=1,
                message=f"{len(src_changes)} source file(s) modified under src/ without any test file updates",
            )
        )

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    return {
        "ok": not errors,
        "verdict": "PASS" if not errors else "BLOCK",
        "files_checked": len(rel_files),
        "python_files_audited": audited_python,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "findings": [f.to_dict() for f in findings],
    }


def skeptic_to_markdown(report: Dict[str, Any]) -> str:
    lines = [
        f"### Skeptic Adversarial Audit: **{report['verdict']}**",
        f"- Python files audited: `{report['python_files_audited']}` | Errors: `{report['error_count']}` | Warnings: `{report['warning_count']}`",
    ]
    if report["findings"]:
        lines.append("")
        lines.append("| Severity | Rule | Location | Detail |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for f in report["findings"]:
            lines.append(f"| `{f['severity']}` | `{f['rule']}` | `{f['file']}:{f['line']}` | {f['message']} |")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic Skeptic / Adversarial auditor for AI PRs.")
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument("files", nargs="+", help="Relative file paths to audit.")
    parser.add_argument("--format", choices={"text", "json", "markdown"}, default="text")
    args = parser.parse_args(argv)

    report = run_skeptic_audit(Path(args.root), args.files)
    if args.format == "json":
        print(json.dumps(report, indent=2))
    elif args.format == "markdown":
        print(skeptic_to_markdown(report))
    else:
        print(f"Skeptic Audit: {report['verdict']} (errors={report['error_count']}, warnings={report['warning_count']})")
        for f in report["findings"]:
            print(f"  [{f['severity'].upper()}] {f['rule']} {f['file']}:{f['line']} — {f['message']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
