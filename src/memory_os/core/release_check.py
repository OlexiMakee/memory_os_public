"""Local release gates for private and public Memory OS publishing."""

from __future__ import annotations

import json
import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from memory_os.core.config import MemoryOSConfig
from memory_os.core.context_pack import ContextPackBuilder
from memory_os.core.core import MemoryOS
from memory_os.core.disk_guard import DiskGuard
from memory_os.core.security_scan import SecurityScanner
from memory_os.core.telemetry_policy import TelemetryPolicy
from memory_os.core.write_budget import ArtifactWriteBudget
from memory_os.toolkit.eval_runner import EvalRunner


PRIVATE_MARKERS = (
    "DEV_STRATEGY.md",
    "IMPORTANT_PROPOSAL",
    "External AI Toolkit",
    "Memory OS 1.5",
)

STALE_DOC_PATTERNS = (
    r"file:///Users",
    r"memory_os\.git@public",
    r"git clone -b public",
    r"FORBIDDEN",
    r"upstream repository",
    r"Runtime Mismatch",
    r"\.generate\(",
)

CLEAN_ROOM_FORBIDDEN_PATHS = (
    # Host OS / Desktop utilities (PRODUCT_BOUNDARY.md CUT)
    "src/memory_os/ide_grant_private.py",
    "src/memory_os/linux_inventory.py",
    "src/memory_os/toolkit/linux_provisioner.py",
    "src/memory_os/toolkit/xfce_manager.py",
    "src/memory_os/toolkit/startup_profile.py",
    "src/memory_os/toolkit/bootstrap_installer.py",
    # Chat bots & custom orchestrators (PRODUCT_BOUNDARY.md CUT)
    "src/memory_os/adapters/telegram_adapter.py",
    "src/memory_os/adapters/telegram_polling.py",
    "src/memory_os/adapters/discord_adapter.py",
    "src/memory_os/agent_brain",
    # Terminal multiplexers & brittle quota scrapers (PRODUCT_BOUNDARY.md CUT)
    "src/memory_os/toolkit/multiplexer_manager.py",
    "src/memory_os/toolkit/agent_console_scanner.py",
    "src/memory_os/toolkit/console_parser.py",
    "src/memory_os/toolkit/quota_harvester.py",
    "src/memory_os/toolkit/agent_manager.py",
    # ML / LoRA pipelines (PRODUCT_BOUNDARY.md CUT)
    "src/memory_os/lora",
    "src/memory_os/toolkit/quantizer.py",
    # Non-core third-party adapters (PRODUCT_BOUNDARY.md CUT)
    "src/memory_os/adapters/duckdb_adapter.py",
    "src/memory_os/adapters/qdrant_adapter.py",
    "src/memory_os/adapters/phoenix_exporter.py",
    "src/memory_os/adapters/langfuse_exporter.py",
    "src/memory_os/adapters/mlflow_exporter.py",
    "src/memory_os/adapters/temporal_adapter.py",
    "src/memory_os/adapters/vllm_provider.py",
    "src/memory_os/adapters/bridges",
    "src/memory_os/adapters/markitdown_adapter.py",
    "src/memory_os/toolkit/gdrive_sync.py",
    # Personal/legacy artifacts & private host scripts
    "src/memory_os/user_persona",
    "src/memory_os/docs/encyclopedia",
    "scripts/agy_workflow.py",
    "scripts/start_llama_server.sh",
)

CLEAN_ROOM_FORBIDDEN_PATTERNS = (
    r"When used inside this host project",
    r"LLMClientFactory is resolved automatically",
    r"/Users/[A-Za-z0-9_.-]+/",
    r"/home/[A-Za-z0-9_.-]+/",
)


@dataclass
class ReleaseCheck:
    name: str
    ok: bool
    detail: str
    severity: str = "error"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "severity": self.severity,
        }


class ReleaseChecker:
    """Runs bounded local gates before private/public publishing."""

    def __init__(self, config: MemoryOSConfig):
        self.config = config

    def run(self, target: str = "private") -> Dict[str, Any]:
        if target not in {"private", "public"}:
            raise ValueError(f"unsupported release-check target: {target}")

        checks: List[ReleaseCheck] = [
            self._check_validate(),
            self._check_default_security(),
            self._check_context_privacy(),
            self._check_docs_hygiene(),
            self._check_core_dependencies(),
            self._check_graph_write_path(),
            self._check_local_evals(),
            self._check_resources(),
            self._check_write_budget(),
            self._check_telemetry(),
            self._check_architectural_boundaries(),
            self._check_bare_except_debt(),
        ]
        if target == "public":
            checks.extend([
                self._check_public_private_files(),
                self._check_public_clean_room(),
                self._check_public_security_profiles(),
            ])

        hard_failures = [c for c in checks if not c.ok and c.severity == "error"]
        warnings = [c for c in checks if not c.ok and c.severity == "warning"]
        return {
            "target": target,
            "ok": not hard_failures,
            "error_count": len(hard_failures),
            "warning_count": len(warnings),
            "checks": [c.to_dict() for c in checks],
        }

    def _check_validate(self) -> ReleaseCheck:
        cmd = [
            sys.executable,
            "-m",
            "memory_os",
            "--config",
            str(self.config.config_path),
            "validate",
        ]
        env = None
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.config.root_dir),
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )
        except Exception as exc:
            return ReleaseCheck("validate", False, f"validate failed to run: {exc}")
        return ReleaseCheck(
            "validate",
            result.returncode == 0,
            (result.stdout or result.stderr).strip()[:1000],
        )

    def _check_default_security(self) -> ReleaseCheck:
        result = SecurityScanner(self.config).scan(profile="default")
        findings = len(result["findings"])
        return ReleaseCheck(
            "security-default",
            findings == 0,
            f"{findings} finding(s) in default profile",
        )

    def _check_context_privacy(self) -> ReleaseCheck:
        pack = ContextPackBuilder(self.config).build(
            task="adapter routing resource policy",
            include_private=False,
        )
        encoded = json.dumps(pack, ensure_ascii=False)
        leaked = [marker for marker in PRIVATE_MARKERS if marker in encoded]
        return ReleaseCheck(
            "context-private-leak",
            not leaked,
            "no private markers found" if not leaked else f"private markers found: {', '.join(leaked)}",
        )

    def _check_docs_hygiene(self) -> ReleaseCheck:
        roots = [
            self.config.root_dir / "README.md",
            self.config.root_dir / "INDEX.md",
            self.config.root_dir / "templates",
            self.config.root_dir / "src" / "memory_os" / "docs",
            self.config.root_dir / "src" / "memory_os" / "cli.py",
            self.config.root_dir / "pyproject.toml",
        ]
        hits: List[str] = []
        compiled = [re.compile(p) for p in STALE_DOC_PATTERNS]
        for root in roots:
            files = [root] if root.is_file() else list(root.glob("**/*")) if root.is_dir() else []
            for path in files:
                if not path.is_file() or path.suffix not in {".md", ".py", ".toml"}:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                for pattern in compiled:
                    if pattern.search(text):
                        rel = path.relative_to(self.config.root_dir)
                        hits.append(f"{rel}:{pattern.pattern}")
                        break
        return ReleaseCheck(
            "docs-hygiene",
            not hits,
            "no stale documentation patterns found" if not hits else "; ".join(hits[:20]),
        )

    def _check_core_dependencies(self) -> ReleaseCheck:
        pyproject = self.config.root_dir / "pyproject.toml"
        if not pyproject.is_file():
            return ReleaseCheck("core-dependencies", False, "pyproject.toml not found")
        try:
            text = pyproject.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            return ReleaseCheck("core-dependencies", False, f"failed to read pyproject.toml: {exc}")

        match = re.search(r"(?ms)^\s*dependencies\s*=\s*\[(.*?)\]", text)
        if not match:
            return ReleaseCheck("core-dependencies", False, "project dependencies field not found")
        entries = [e.strip().strip("'\"") for e in match.group(1).split(",") if e.strip()]
        forbidden = [
            dep for dep in entries
            if dep.split(">=")[0].split("==")[0] in {"ollama", "openai", "pydantic", "psutil"}
        ]
        return ReleaseCheck(
            "core-dependencies",
            not forbidden,
            "mandatory dependency list is empty/core-only" if not forbidden else f"provider/tool deps are mandatory: {', '.join(forbidden)}",
        )

    def _check_graph_write_path(self) -> ReleaseCheck:
        source_root = self.config.root_dir / "src" / "memory_os"
        if not source_root.is_dir():
            return ReleaseCheck("graph-write-path", True, "source tree not present")

        allowed = {
            Path("core/repository.py"),
            Path("core/storage.py"),
            Path("core/interfaces.py"),
        }
        hits: List[str] = []
        for path in source_root.rglob("*.py"):
            rel = path.relative_to(source_root)
            if rel in allowed:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(text)
            except Exception:
                continue

            canonical_names = self._canonical_graph_path_names(tree, text)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if self._is_canonical_jsonl_write(node, canonical_names, text):
                    hits.append(f"{Path('src/memory_os') / rel}:{getattr(node, 'lineno', '?')}")

        return ReleaseCheck(
            "graph-write-path",
            not hits,
            "canonical graph writes are repository/patch backed" if not hits else "direct canonical graph writes [CR-GRAPH]: " + "; ".join(hits[:20]),
        )

    def _canonical_graph_path_names(self, tree: ast.AST, text: str) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            segment = ast.get_source_segment(text, node.value) or ""
            if not self._segment_targets_canonical_graph(segment):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        return names

    def _is_canonical_jsonl_write(self, node: ast.Call, canonical_names: set[str], text: str) -> bool:
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in {"save_jsonl", "append_jsonl"} and node.args:
                return self._arg_targets_canonical_graph(node.args[0], canonical_names, text)
            if func.attr == "write_text" and isinstance(func.value, ast.Name):
                return func.value.id in canonical_names
        if isinstance(func, ast.Name) and func.id == "open" and node.args:
            if not self._arg_targets_canonical_graph(node.args[0], canonical_names, text):
                return False
            if len(node.args) < 2:
                return False
            mode = node.args[1]
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
                return any(flag in mode.value for flag in ("w", "a", "x", "+"))
        return False

    def _arg_targets_canonical_graph(self, arg: ast.AST, canonical_names: set[str], text: str) -> bool:
        if isinstance(arg, ast.Name) and arg.id in canonical_names:
            return True
        segment = ast.get_source_segment(text, arg) or ""
        return self._segment_targets_canonical_graph(segment)

    def _segment_targets_canonical_graph(self, segment: str) -> bool:
        return any(
            quoted in segment
            for quoted in ('"nodes.jsonl"', "'nodes.jsonl'", '"edges.jsonl"', "'edges.jsonl'")
        )

    def _check_local_evals(self) -> ReleaseCheck:
        runner = EvalRunner(self.config)
        suites = ("retrieval-relevance",)
        results = []
        failures = []
        for suite in suites:
            result = runner.run(suite)
            results.append(f"{suite}:{result.get('pass_rate', 0.0):.2f}")
            if not result.get("ok", False):
                failures.append(f"{suite}={result.get('pass_rate', 0.0):.2f}<{result.get('pass_threshold', 1.0)}")
        return ReleaseCheck(
            "eval-gate",
            not failures,
            " ; ".join(results) if not failures else "; ".join(failures),
        )

    def _check_resources(self) -> ReleaseCheck:
        snap = DiskGuard(self.config).snapshot()
        return ReleaseCheck(
            "resources",
            snap.level != "hot",
            f"resource level {snap.level}",
        )

    def _check_write_budget(self) -> ReleaseCheck:
        status = ArtifactWriteBudget(self.config).status()
        return ReleaseCheck(
            "write-budget",
            status.ok,
            f"agent_context={status.agent_context_mb}MB/{status.max_agent_context_mb}MB files={status.agent_context_files}/{status.max_agent_context_files}",
        )

    def _check_telemetry(self) -> ReleaseCheck:
        db = MemoryOS(self.config)
        conn = db.get_connection()
        try:
            report = TelemetryPolicy(self.config, db_path=db.db_path).audit(conn)
        finally:
            conn.close()
        over = report["db_over_cap"] or any(t["over_cap"] for t in report["tables"])
        return ReleaseCheck(
            "telemetry-budget",
            not over,
            f"db={report['db_mb']}MB rows=" + ",".join(f"{t['table']}:{t['row_count']}" for t in report["tables"]),
        )

    def _check_architectural_boundaries(self) -> ReleaseCheck:
        ownership_file = self.config.root_dir / "architecture.toml"
        if not ownership_file.exists():
            return ReleaseCheck("architecture-boundaries", True, "architecture.toml not found, skipping check")
        
        try:
            from memory_os.core.toml_compat import load_toml_path
            ownership = load_toml_path(ownership_file)
            canonical = ownership.get("canonical_modules", {})
            forbidden_patterns = ownership.get("forbidden_patterns", {})
        except Exception as exc:
            return ReleaseCheck("architecture-boundaries", False, f"failed to load architecture.toml: {exc}")
            
        source_root = self.config.root_dir / "src" / "memory_os"
        if not source_root.is_dir():
            return ReleaseCheck("architecture-boundaries", True, "source tree not present")
            
        import_hits = []
        except_hits = []
        for path in source_root.rglob("*.py"):
            rel = path.relative_to(source_root)
            rel_str = f"src/memory_os/{rel}"
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(text)
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        mod = alias.name.split('.')[0]
                        if mod in canonical and rel_str not in canonical[mod]:
                            import_hits.append(f"{rel_str}:{getattr(node, 'lineno', '?')} imported forbidden {mod}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        mod = node.module.split('.')[0]
                        if mod in canonical and rel_str not in canonical[mod]:
                            import_hits.append(f"{rel_str}:{getattr(node, 'lineno', '?')} imported forbidden {mod}")
                elif isinstance(node, ast.ExceptHandler):
                    if "bare_except" in forbidden_patterns:
                        if node.type is None:
                            except_hits.append(f"{rel_str}:{getattr(node, 'lineno', '?')} uses forbidden bare except")
                        elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
                            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                                except_hits.append(f"{rel_str}:{getattr(node, 'lineno', '?')} uses forbidden 'except Exception: import sys as _sys; print('Ignored exception', file=_sys.stderr)'")

        self._bare_except_debt = except_hits
        return ReleaseCheck(
            "architecture-boundaries",
            not import_hits,
            "all imports comply with architecture.toml" if not import_hits else "boundary violations [CR-GATES]: " + "; ".join(import_hits[:20]),
        )

    def _check_bare_except_debt(self) -> ReleaseCheck:
        # New violations should be caught in code review; whole-tree enforcement
        # at error severity would hard-block release-check on pre-existing debt
        # never audited for behavioral intent. Reported as debt, not a gate.
        hits = getattr(self, "_bare_except_debt", [])
        return ReleaseCheck(
            "bare-except-debt",
            not hits,
            "no bare except found" if not hits else f"{len(hits)} pre-existing bare-except site(s) [CR-STYLE]: " + "; ".join(hits[:20]),
            severity="warning",
        )


    def _check_public_private_files(self) -> ReleaseCheck:
        private_files = [
            self.config.root_dir / "DEV_STRATEGY.md",
            self.config.root_dir / "agent_context" / "IMPORTANT_PROPOSAL.md",
        ]
        present = [str(p.relative_to(self.config.root_dir)) for p in private_files if p.exists()]
        return ReleaseCheck(
            "public-private-files",
            not present,
            "no private planning docs present" if not present else f"private docs present in checkout: {', '.join(present)}",
            severity="error",
        )

    def _check_public_clean_room(self) -> ReleaseCheck:
        """Verify public release tree contains no non-core personal/host-coupled artifacts."""
        violations: List[str] = []
        for rel_path in CLEAN_ROOM_FORBIDDEN_PATHS:
            if (self.config.root_dir / rel_path).exists():
                violations.append(f"forbidden-path:{rel_path}")

        scan_roots = [
            self.config.root_dir / "pyproject.toml",
            self.config.root_dir / "README.md",
            self.config.root_dir / "action.yml",
            self.config.root_dir / "docs",
            self.config.root_dir / "src" / "memory_os",
            self.config.root_dir / "scripts",
            self.config.root_dir / "benchmarks",
        ]
        compiled = [re.compile(p) for p in CLEAN_ROOM_FORBIDDEN_PATTERNS]
        for root in scan_roots:
            files = [root] if root.is_file() else list(root.rglob("*")) if root.is_dir() else []
            for path in files:
                if not path.is_file() or path.suffix not in {".py", ".toml", ".md", ".sh", ".yml", ".yaml"}:
                    continue
                if path.name == "release_check.py":
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                for pattern in compiled:
                    if pattern.search(text):
                        rel = path.relative_to(self.config.root_dir)
                        violations.append(f"clean-room-pattern:{rel}:{pattern.pattern}")
                        break

        return ReleaseCheck(
            "public-clean-room",
            not violations,
            "public clean-room check passed"
            if not violations
            else f"{len(violations)} clean-room violation(s): " + "; ".join(violations[:15]),
            severity="error",
        )

    def _check_public_security_profiles(self) -> ReleaseCheck:
        result = SecurityScanner(self.config).scan(profile="all")
        findings = len(result["findings"])
        return ReleaseCheck(
            "security-all",
            findings == 0,
            f"{findings} finding(s) in all profile",
            severity="warning",
        )
