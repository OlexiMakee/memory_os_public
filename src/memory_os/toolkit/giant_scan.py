#!/usr/bin/env python3
"""
Giant Scan: Full-Context Audit Tool for Memory OS.

Collects the entire project source code and Memory OS graph state,
sends it to a large-context LLM for architectural audit, and outputs
structured proposals for graph corrections and code improvements.

This is an L13 tool — designed for periodic milestone reviews,
not daily operations.
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from memory_os.modules.context import ContextRegistry
from memory_os.core.config import MemoryOSConfig
from memory_os.core.llm_service import DefaultLlmProviderService
from memory_os.core.storage import FileSystemMemoryStorage


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHAR_BUDGET_WARNING = 500_000  # chars before --force is required

EXCLUDED_DIRS: Set[str] = {
    ".git", ".tmp.driveupload", ".venv", "venv", "venv_auto",
    "node_modules", "__pycache__", ".pytest_cache", "data",
    ".gemini", ".cursor",
}

SOURCE_SUFFIXES: Set[str] = {
    ".py", ".js", ".ts", ".css", ".html", ".sql",
    ".md", ".txt", ".json", ".jsonl",
    ".yml", ".yaml", ".toml",
}

GIANT_SCAN_SYSTEM_PROMPT = """\
You are the Memory OS Giant Scan Auditor.
Your task is a full-context architectural review of a software project.

You receive:
1. The COMPLETE source code of the project, with file boundaries marked.
2. The current Memory OS graph state (nodes, edges, events).

Your audit goals:
A. **Implicit State Coupling**: Find modules connected through shared DB fields,
   environment variables, file system paths, or global state — but NOT through
   direct imports. These hidden dependencies are invisible to AST-based indexing.
B. **Architectural Drift**: Identify patterns that have diverged across modules
   (e.g., duplicated logic, inconsistent error handling, naming mismatches,
   mixed conventions).
C. **Graph Inconsistencies**: Compare the Memory OS graph against the actual code.
   Flag nodes that reference deleted files, outdated summaries, or missing edges
   for real dependencies.
D. **Dead Code & Redundancy**: Spot unused functions, duplicate definitions,
   or stale imports.
E. **Security & Secrets**: Flag any hardcoded credentials, tokens, or unsafe
   patterns (but do NOT output the actual secret values).

Output format: Return ONLY valid JSON matching this schema:
{
  "findings": [
    {
      "id": "gs:<category>:<short_slug>",
      "category": "implicit_coupling|architectural_drift|graph_inconsistency|dead_code|security",
      "severity": "critical|high|medium|low",
      "title": "Short human-readable title",
      "description": "Detailed explanation with file paths and line references.",
      "affected_files": ["path/to/file1.py", "path/to/file2.py"],
      "recommendation": "What should be done to fix this."
    }
  ],
  "summary": "1-3 sentence overall health assessment."
}

Rules:
- Return 3 to 15 findings, prioritized by severity.
- Be specific: cite file paths and function names.
- Do NOT praise the code. Focus exclusively on problems.
- Do NOT output markdown fences around the JSON.
"""


# ---------------------------------------------------------------------------
# RepoCollector
# ---------------------------------------------------------------------------

class RepoCollector:
    """Collects all text source files into a single concatenated block."""

    def __init__(self, project_root: Path, target_dir: Optional[Path] = None):
        self.project_root = project_root
        self.scan_root = target_dir if target_dir else project_root

    def collect(self, max_file_bytes: int = 500_000) -> str:
        """Walk the project tree and concatenate all source files."""
        blocks: List[str] = []
        total_chars = 0

        for path in sorted(self.scan_root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SOURCE_SUFFIXES:
                continue

            # Check excluded dirs
            try:
                rel_parts = path.relative_to(self.project_root).parts
            except ValueError:
                continue
            if any(part in EXCLUDED_DIRS for part in rel_parts):
                continue

            # Skip oversized individual files
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > max_file_bytes:
                blocks.append(f"--- FILE: {'/'.join(rel_parts)} [SKIPPED: {size} bytes] ---\n")
                continue

            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            rel_str = "/".join(rel_parts)
            header = f"--- FILE: {rel_str} ---"
            blocks.append(f"{header}\n{text}\n")
            total_chars += len(text)

        return "".join(blocks), total_chars


# ---------------------------------------------------------------------------
# GraphCollector
# ---------------------------------------------------------------------------

class GraphCollector:
    """Collects the current Memory OS graph state."""

    def __init__(self, config: MemoryOSConfig):
        self.config = config
        self.storage = FileSystemMemoryStorage()

    def collect(self) -> str:
        """Load nodes, edges, events and format as a readable block."""
        sections: List[str] = []

        # Nodes
        nodes = self._load_safe(self.config.memory_dir / "nodes.jsonl")
        internal_nodes = self._load_safe(self.config.internal_memory_dir / "nodes.jsonl")
        all_nodes = nodes + internal_nodes
        if all_nodes:
            sections.append("=== MEMORY OS: NODES ===")
            for n in all_nodes:
                sections.append(json.dumps(n, ensure_ascii=False, separators=(",", ":")))

        # Edges
        edges = self._load_safe(self.config.memory_dir / "edges.jsonl")
        internal_edges = self._load_safe(self.config.internal_memory_dir / "edges.jsonl")
        all_edges = edges + internal_edges
        if all_edges:
            sections.append("\n=== MEMORY OS: EDGES ===")
            for e in all_edges:
                sections.append(json.dumps(e, ensure_ascii=False, separators=(",", ":")))

        # Events
        events_path = self.config.memory_dir / "events.jsonl"
        events = self._load_safe(events_path)
        if events:
            sections.append("\n=== MEMORY OS: EVENTS ===")
            for ev in events[-50:]:  # Last 50 events to save tokens
                sections.append(json.dumps(ev, ensure_ascii=False, separators=(",", ":")))

        if not sections:
            return "=== MEMORY OS: NO GRAPH DATA FOUND ==="

        return "\n".join(sections)

    def _load_safe(self, path: Path) -> List[Dict[str, Any]]:
        """Load JSONL without crashing on missing files."""
        try:
            return self.storage.load_jsonl(path)
        except Exception:
            return []


# ---------------------------------------------------------------------------
# GiantScanRunner
# ---------------------------------------------------------------------------

class GiantScanRunner:
    """Orchestrates the Giant Scan: collect → prompt → LLM → proposals."""

    def __init__(self, config: MemoryOSConfig):
        self.config = config
        self.root = config.root_dir
        self.llm = DefaultLlmProviderService()
        self.proposals_path = (self.root / "agent_proposals" / "giant_scan_proposals.jsonl").resolve()

    def run(
        self,
        provider: str = "gemini",
        model: str = "gemini-2.5-pro",
        force: bool = False,
        dry_run: bool = False,
        target_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute the full Giant Scan pipeline."""

        scan_root = None
        if target_dir:
            scan_root = (self.root / target_dir).resolve()
            if not str(scan_root).startswith(str(self.root)):
                return {"status": "aborted", "reason": "Target directory is outside project root."}

        # 1. Collect source code
        repo = RepoCollector(self.root, target_dir=scan_root)
        source_text, char_count = repo.collect()

        # 2. Budget guard
        if char_count > CHAR_BUDGET_WARNING and not force:
            return {
                "status": "aborted",
                "reason": f"Source code is {char_count:,} chars (>{CHAR_BUDGET_WARNING:,}). "
                          f"Use --force to proceed.",
                "char_count": char_count,
            }

        # 3. Collect graph state
        graph = GraphCollector(self.config)
        graph_text = graph.collect()

        # 4. Compose user message
        user_message = f"# PROJECT SOURCE CODE\n\n{source_text}\n\n# MEMORY OS GRAPH STATE\n\n{graph_text}"

        # 5. Dry-run: return stats only
        if dry_run:
            return {
                "status": "dry_run",
                "char_count": char_count,
                "graph_lines": graph_text.count("\n"),
                "total_prompt_chars": len(user_message),
            }

        # 6. Call LLM
        print(f"[Giant Scan] Sending {len(user_message):,} chars to {provider}/{model}...", file=sys.stderr)
        try:
            raw_response = self.llm.call_llm(
                user_message=user_message,
                system_prompt=GIANT_SCAN_SYSTEM_PROMPT,
                provider=provider,
                model=model,
            )
        except Exception as exc:
            return {"status": "error", "reason": f"LLM call failed: {exc}"}

        # 7. Parse response
        cleaned = raw_response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            return {
                "status": "error",
                "reason": f"Failed to parse LLM JSON: {exc}",
                "raw_response": raw_response[:2000],
            }

        findings = result.get("findings", [])
        summary = result.get("summary", "")

        # 8. Write proposals
        created = self._write_proposals(findings)

        return {
            "status": "success",
            "char_count": char_count,
            "findings_count": len(findings),
            "findings": findings,
            "summary": summary,
            "proposals_created": created,
            "proposals_file": str(self.proposals_path),
        }

    def _write_proposals(self, findings: List[Dict[str, Any]]) -> int:
        """Persist findings as draft proposals in JSONL."""
        self.proposals_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing IDs to deduplicate
        existing_ids: Set[str] = set()
        if self.proposals_path.exists():
            try:
                with open(self.proposals_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                            existing_ids.add(row.get("id", ""))
                        except json.JSONDecodeError:
                            pass
            except Exception:
                pass

        created = 0
        with open(self.proposals_path, "a", encoding="utf-8") as f:
            for finding in findings:
                fid = finding.get("id", f"gs:auto:{int(time.time())}_{created}")
                if fid in existing_ids:
                    continue

                row = {
                    "id": fid,
                    "ts": int(time.time() * 1000),
                    "role": "system",
                    "type": "giant_scan_finding",
                    "status": "draft",
                    "category": finding.get("category", "unknown"),
                    "severity": finding.get("severity", "medium"),
                    "title": finding.get("title", ""),
                    "desc": finding.get("description", ""),
                    "affected_files": finding.get("affected_files", []),
                    "recommendation": finding.get("recommendation", ""),
                    "src": "memory_os.toolkit.giant_scan",
                }
                f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                created += 1
                existing_ids.add(fid)

        return created


# ---------------------------------------------------------------------------
# Standalone CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Giant Scan: Full-context audit for Memory OS.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]),
                        help="Project root directory.")
    parser.add_argument("--provider", default="gemini", help="LLM provider (gemini, openrouter, openai).")
    parser.add_argument("--model", default="gemini-2.5-pro", help="LLM model ID.")
    parser.add_argument("--force", action="store_true", help="Allow scanning repos >500K chars.")
    parser.add_argument("--dry-run", action="store_true", help="Collect stats without calling LLM.")
    parser.add_argument("--format", choices={"json", "markdown"}, default="markdown",
                        help="Output format.")
    args = parser.parse_args()

    import os
    root = Path(args.root).resolve()
    env_file = root / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

    config_path = os.environ.get("MEMORY_OS_CONFIG_PATH") or (root / "memory_os.config.json")
    config = MemoryOSConfig(config_path=str(config_path) if Path(config_path).exists() else None)

    runner = GiantScanRunner(config)
    result = runner.run(
        provider=args.provider,
        model=args.model,
        force=args.force,
        dry_run=args.dry_run,
    )

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        _print_markdown(result)

    return 0 if result.get("status") in ("success", "dry_run") else 1


def _print_markdown(result: Dict[str, Any]) -> None:
    """Pretty-print scan results as markdown."""
    status = result.get("status", "unknown")
    print(f"# Giant Scan Report\n")
    print(f"**Status:** {status}")
    char_count = result.get('char_count')
    if isinstance(char_count, int):
        print(f"**Source chars:** {char_count:,}")
    else:
        print(f"**Source chars:** N/A")

    if status == "dry_run":
        print(f"**Graph lines:** {result.get('graph_lines', 0)}")
        print(f"**Total prompt chars:** {result.get('total_prompt_chars', 0):,}")
        print("\n_Dry run complete. No LLM call was made._")
        return

    if status == "aborted":
        print(f"\n⚠️  {result.get('reason', '')}")
        return

    if status == "error":
        print(f"\n❌ {result.get('reason', '')}")
        return

    print(f"**Findings:** {result.get('findings_count', 0)}")
    print(f"**Proposals created:** {result.get('proposals_created', 0)}")

    summary = result.get("summary", "")
    if summary:
        print(f"\n## Summary\n\n{summary}")

    findings = result.get("findings", [])
    if findings:
        print(f"\n## Findings\n")
        for i, f in enumerate(findings, 1):
            sev = f.get("severity", "?").upper()
            cat = f.get("category", "?")
            print(f"### {i}. [{sev}] {f.get('title', 'Untitled')}")
            print(f"**Category:** {cat}")
            if f.get("affected_files"):
                print(f"**Files:** {', '.join(f['affected_files'])}")
            print(f"\n{f.get('description', '')}\n")
            if f.get("recommendation"):
                print(f"**Recommendation:** {f['recommendation']}\n")


if __name__ == "__main__":
    raise SystemExit(main())
