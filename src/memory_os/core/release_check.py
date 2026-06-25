"""Local release gates for private and public Memory OS publishing."""

from __future__ import annotations

import json
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
            self._check_resources(),
            self._check_write_budget(),
            self._check_telemetry(),
        ]
        if target == "public":
            checks.extend([
                self._check_public_private_files(),
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

    def _check_public_security_profiles(self) -> ReleaseCheck:
        result = SecurityScanner(self.config).scan(profile="all")
        findings = len(result["findings"])
        return ReleaseCheck(
            "security-all",
            findings == 0,
            f"{findings} finding(s) in all profile",
            severity="warning",
        )
