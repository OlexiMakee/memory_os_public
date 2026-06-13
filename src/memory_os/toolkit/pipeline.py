"""
Memory OS Pipeline — chain multiple commands into named workflows.

Built-in pipelines:
  ingest   — notion-sync → compact → link-infer → sync
  refresh  — compress → prune → link-infer (text only) → sync
  full     — notion-sync → compact → link-infer → compress → prune → sync

Usage:
  memory_os pipeline ingest  [--notion-key KEY --notion-db DB]
  memory_os pipeline refresh [--provider PROVIDER --model MODEL]
  memory_os pipeline full    [--notion-key KEY --notion-db DB --provider PROVIDER]
  memory_os pipeline custom  STEP1 STEP2 ...   (run arbitrary sequence of commands)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Step runner
# ---------------------------------------------------------------------------

def _run_step(step_args: List[str], label: str) -> int:
    """Run a single memory_os subcommand. Returns exit code."""
    cmd = [sys.executable, "-m", "memory_os"] + step_args
    print(f"\n{'─'*60}")
    print(f"  STEP: {label}")
    print(f"  CMD : {' '.join(step_args)}")
    print(f"{'─'*60}")

    result = subprocess.run(cmd, cwd=Path.cwd())
    if result.returncode != 0:
        print(f"  [FAILED] {label} exited with code {result.returncode}", file=sys.stderr)
    else:
        print(f"  [OK] {label}")
    return result.returncode


# ---------------------------------------------------------------------------
# Named pipelines
# ---------------------------------------------------------------------------

PIPELINES = {
    "ingest": {
        "description": "Sync Notion → extract nodes/edges via LLM → infer text edges → index.",
        "steps": [
            # notion-sync is optional (needs keys), handled separately
            ("compact", "Extract nodes & edges from task capsules via LLM"),
            ("link-infer --method text --min-score 0.5", "Infer edges by text matching"),
            ("sync", "Index graph to SQLite FTS5"),
        ],
    },
    "refresh": {
        "description": "Merge duplicates, prune stale, re-infer text edges, re-index.",
        "steps": [
            ("compress", "Merge semantic duplicate nodes via LLM"),
            ("prune", "Archive stale and superseded nodes/edges"),
            ("link-infer --method text --min-score 0.5", "Infer edges by text matching"),
            ("sync", "Index graph to SQLite FTS5"),
        ],
    },
    "full": {
        "description": "Full pipeline: ingest + refresh in one pass.",
        "steps": [
            ("compact", "Extract nodes & edges from task capsules via LLM"),
            ("link-infer --method text --min-score 0.5", "Infer edges by text matching"),
            ("compress", "Merge semantic duplicate nodes via LLM"),
            ("prune", "Archive stale and superseded nodes/edges"),
            ("sync", "Index graph to SQLite FTS5"),
        ],
    },
}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

class PipelineRunner:
    def __init__(self, config: MemoryOSConfig):
        self.config = config

    def list_pipelines(self) -> None:
        print("\nAvailable pipelines:\n")
        for name, spec in PIPELINES.items():
            print(f"  {name:<10} — {spec['description']}")
            for step_cmd, label in spec["steps"]:
                print(f"             • {label}")
        print()

    def run(
        self,
        pipeline_name: str,
        custom_steps: Optional[List[str]] = None,
        notion_key: Optional[str] = None,
        notion_db: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        dry_run: bool = False,
    ) -> int:

        if pipeline_name == "list":
            self.list_pipelines()
            return 0

        if pipeline_name == "custom":
            if not custom_steps:
                print("Error: 'custom' pipeline requires at least one step argument.", file=sys.stderr)
                return 1
            steps = [(s, s) for s in custom_steps]
        else:
            spec = PIPELINES.get(pipeline_name)
            if not spec:
                print(f"Unknown pipeline '{pipeline_name}'. Use 'list' to see available pipelines.", file=sys.stderr)
                return 1
            steps = list(spec["steps"])

        # Prepend notion-sync if keys provided
        if notion_key and notion_db:
            steps.insert(0, (
                f"notion-sync --api-key {notion_key} --database-id {notion_db}",
                "Sync nodes from Notion database",
            ))

        # Inject provider/model into LLM steps
        if provider:
            steps = [
                (f"{cmd} --provider {provider}" if any(k in cmd for k in ["compact", "compress", "link-infer"]) else cmd, label)
                for cmd, label in steps
            ]
        if model:
            steps = [
                (f"{cmd} --model {model}" if any(k in cmd for k in ["compact", "compress", "link-infer"]) else cmd, label)
                for cmd, label in steps
            ]

        print(f"\nRunning pipeline: {pipeline_name}")
        print(f"Steps: {len(steps)}")

        if dry_run:
            print("\n[dry-run] Would execute:")
            for i, (cmd, label) in enumerate(steps, 1):
                print(f"  {i}. {label}")
                print(f"     memory_os {cmd}")
            return 0

        failed = 0
        for cmd, label in steps:
            rc = _run_step(cmd.split(), label)
            if rc != 0:
                failed += 1
                print(f"\nPipeline step failed: {label}. Continuing...", file=sys.stderr)

        print(f"\n{'='*60}")
        if failed == 0:
            print(f"  Pipeline '{pipeline_name}' completed successfully.")
        else:
            print(f"  Pipeline '{pipeline_name}' finished with {failed} failed step(s).")
        print(f"{'='*60}\n")

        return 0 if failed == 0 else 1
