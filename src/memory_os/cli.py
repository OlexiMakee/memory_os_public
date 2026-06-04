#!/usr/bin/env python3
"""Portable Memory OS control CLI for project-local operations."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load .env from project root so LLM API keys are available
_env_file = ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _, _v = _line.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip())

from memory_os import (
    MemoryOSConfig,
    MemoryValidator,
    MemoryCompactor,
    LifecycleManager,
    MemorySearcher,
    MemoryOS
)
from memory_os.toolkit.auditor import audit, to_markdown

DEFAULT_WORKFLOWS = """# Workflows

Use two explicit workstreams:
- `product`: customer-facing product work.
- `memory_os`: internal shorthand for agent workflow, telemetry, repo analysis, and self-improvement tools.

Naming guard: `memory_os` is the internal command/workflow alias.

Step scale: 1 nano, 2 micro, 3 tiny, 4 little, 5 pretty little, 6 light mid,
7 mid, 8 high mid, 9 mid high, 10 big, 11 large, 12 giant.
"""

DEFAULT_AGENTS_BLOCK = """\n## Memory OS Integration

- Read `agent_context/WORKFLOWS.md` before choosing task scope.
- Route work through `product` or `memory_os`.
- Use the 12-step scale from `nano` to `giant`.
- Run `python -m memory_os audit` before broad Memory OS changes.
"""

DEFAULT_WORKFLOW_TOMLS = {
    "chat.nano.toml": """id = "chat.nano"
step_min = 0
step_max = 2
level_min = 1
level_max = 18
model_policy = "cheap_free"
tools = ["search_memory"]
verification = ["schema_check"]

[memory_policy]
max_cards = 3
max_tokens = 1200

[escalation]
if_uncertainty_above = 0.6
escalate_to = "chat.standard"
""",
    "code.small.toml": """id = "code.small"
step_min = 3
step_max = 8
level_min = 26
level_max = 64
model_policy = "codex"
tools = ["search_memory", "validate_memory"]
verification = ["test_run_required"]

[memory_policy]
max_cards = 10
max_tokens = 4000

[escalation]
if_risk_above = 0.5
escalate_to = "code.standard"
""",
    "architecture.giant.toml": """id = "architecture.giant"
step_min = 9
step_max = 13
level_min = 65
level_max = 100
model_policy = "large_reasoning"
tools = ["repo_index", "symbol_search", "test_runner", "adr_writer"]
verification = ["dry_run_required", "user_approval_required"]

[memory_policy]
root_files = ["AGENTS.md", "INDEX.md", "README.md"]
graph_depth = 3
require_evidence = true

[output]
format = "adr_proposal"
""",
}

def write_if_missing(path: Path, content: str, actions: List[str]) -> None:
    if path.exists():
        actions.append(f"exists {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    actions.append(f"created {path}")

def append_if_absent(path: Path, marker: str, content: str, actions: List[str]) -> None:
    if path.exists():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if marker in text:
            actions.append(f"already integrated {path}")
            return
        path.write_text(text.rstrip() + "\n" + content.lstrip(), encoding="utf-8")
        actions.append(f"updated {path}")
        return
    path.write_text(content.lstrip(), encoding="utf-8")
    actions.append(f"created {path}")

def cmd_init(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    root = Path(args.root).resolve()
    actions: List[str] = []
    write_if_missing(root / "agent_context" / "WORKFLOWS.md", DEFAULT_WORKFLOWS, actions)
    write_if_missing(
        root / "agent_context" / "HANDSHAKE.md",
        "# Agent Handshake\n\n## Current Session Status\n- Active Agent: unknown\n- Budget Tier applied: `memory_os nano` / score 1\n- Target: Initial Memory OS bootstrap.\n",
        actions,
    )
    write_if_missing(root / "agent_context" / "development_log.md", "# Development Log\n", actions)
    write_if_missing(root / "agent_context" / "task_capsules.jsonl", "", actions)
    write_if_missing(root / "memory" / "nodes.jsonl", "", actions)
    write_if_missing(root / "memory" / "edges.jsonl", "", actions)
    write_if_missing(root / "memory" / "events.jsonl", "", actions)
    for filename, content in DEFAULT_WORKFLOW_TOMLS.items():
        write_if_missing(root / "workflows" / filename, content, actions)
    write_if_missing(
        root / "memory_os.config.json",
        json.dumps({
            "version": "0.1",
            "created_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "workflows": ["product", "memory_os"],
            "step_scale": "1..12",
        }, indent=2, sort_keys=True) + "\n",
        actions,
    )
    print("\n".join(actions))
    return 0

def cmd_integrate(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    root = Path(args.root).resolve()
    actions: List[str] = []
    if not (root / "agent_context" / "WORKFLOWS.md").exists():
        write_if_missing(root / "agent_context" / "WORKFLOWS.md", DEFAULT_WORKFLOWS, actions)
    append_if_absent(root / "AGENTS.md", "## Memory OS Integration", DEFAULT_AGENTS_BLOCK, actions)
    print("\n".join(actions))
    return 0

def cmd_audit(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    report = audit(Path(args.root).resolve())
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(to_markdown(report))
    return 1 if report["capsule_jsonl_errors"] or report["capsule_validation_errors"] else 0

def cmd_validate(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    root = Path(args.root).resolve()
    
    validator = MemoryValidator(config)
    errors = []
    
    errors.extend(validator.validate_file())
    errors.extend(validator.validate_nodes())
    errors.extend(validator.validate_edges())
    errors.extend(validator.validate_events())
    errors.extend(validator.validate_proposals_file())

    from memory_os.toolkit.workflow_validator import build_report as build_workflow_report
    workflow_report = build_workflow_report(root)
    errors.extend(f"workflows: {error}" for error in workflow_report["errors"])

    if errors:
        print("\n".join(errors))
        return 1
    print("memory_os validation ok")
    return 0

def cmd_snapshot(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    root = Path(args.root).resolve()
    # Find script path relative to this script's directory
    script_dir = Path(__file__).resolve().parent
    command = [sys.executable, str(script_dir / "compact_memory.py")]
    if args.write:
        command.append("--write")
    return subprocess.run(command, cwd=str(root), check=False).returncode

def cmd_quantize(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.quantizer import calculate_score, resolve_profile

    legacy_score = calculate_score(
        args.task,
        risk=args.risk,
        volume=args.volume,
        uncertainty=args.uncertainty,
    )
    result = {
        "task": args.task,
        "legacy_score": legacy_score,
        **resolve_profile(legacy_score),
    }
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Task: {result['task']}")
        print(f"Legacy Score: {result['legacy_score']}/100")
        print(f"Step Score: {result['step_score']}/12")
        print(f"Step Name: {result['step_name']}")
        print(f"Workflow ID: {result['workflow_id']}")
        print(f"Model Policy: {result['model_policy']}")
        print(f"Escalate: {str(result['escalate']).lower()}")
    return 0

def cmd_workflows(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.workflow_validator import build_report, to_markdown, write_manifest

    root = Path(args.root).resolve()
    report = build_report(root)
    if args.write_manifest:
        write_manifest(report, root / args.manifest_path)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(to_markdown(report))
    return 0 if report["ok"] else 1

def cmd_compact(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    root = Path(args.root).resolve()
    compactor = MemoryCompactor(config)
    return compactor.compact_capsules(provider=args.provider, model=args.model)

def cmd_compress(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    root = Path(args.root).resolve()
    compactor = MemoryCompactor(config)
    return compactor.compress_graph(provider=args.provider, model=args.model)

def cmd_prune(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    root = Path(args.root).resolve()
    lifecycle = LifecycleManager(config)
    return lifecycle.prune()

def cmd_stats(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    import yaml
    root = Path(args.root).resolve()
    os_kernel = MemoryOS(str(root / "data" / "memory_os.db"))
    conn = os_kernel.get_connection()
    try:
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*), SUM(cost), SUM(input_tokens), SUM(output_tokens), AVG(latency_ms) FROM memory_os_telemetry")
        total_row = cur.fetchone()
        totals = {
            "calls": total_row[0] or 0,
            "cost_usd": round(total_row[1] or 0, 5) if total_row[1] else 0.0,
            "input_tokens": total_row[2] or 0,
            "output_tokens": total_row[3] or 0,
            "avg_latency_ms": round(total_row[4] or 0, 1) if total_row[4] else 0.0
        }
        
        cur.execute("SELECT provider_id, model_id, COUNT(*), SUM(cost) FROM memory_os_telemetry GROUP BY provider_id, model_id")
        models = []
        for row in cur.fetchall():
            models.append({
                "provider": row[0],
                "model": row[1],
                "calls": row[2],
                "cost_usd": round(row[3] or 0, 5) if row[3] else 0.0
            })
            
        cur.execute("SELECT prompt_name, COUNT(*), AVG(latency_ms) FROM memory_os_telemetry GROUP BY prompt_name")
        prompts = []
        for row in cur.fetchall():
            prompts.append({
                "prompt": row[0],
                "calls": row[1],
                "avg_latency_ms": round(row[2] or 0, 1) if row[2] else 0.0
            })
            
        report = {
            "Total": totals,
            "By_Model": models,
            "By_Prompt": prompts
        }
        print(yaml.safe_dump(report, default_flow_style=False, sort_keys=False))
        return 0
    finally:
        conn.close()

def cmd_rag(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    import yaml
    root = Path(args.root).resolve()
    searcher = MemorySearcher(config)
    
    results = searcher.search_memory(args.query, depth=1)
    if not results:
        print("No rules found for this context.")
        return 0
        
    formatted = []
    for r in results[:5]: # Take top 5 to save tokens
        formatted.append({
            "id": r.get("id"),
            "summary": r.get("summary")
        })
        
    output_path = root / "agent_context" / "active_memory.yaml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.safe_dump({"active_context": formatted}, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        
    print(f"Wrote {len(formatted)} memory nodes to {output_path.relative_to(root)}")
    return 0

def cmd_ingest_transcript(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.transcript_ingestor import TranscriptIngestor
    from memory_os.core.config import MemoryOSConfig
    root = Path(args.root).resolve()
    
    ingestor = TranscriptIngestor(config)
    transcript_path = Path(args.log_file).resolve()
    print(f"Parsing transcript {transcript_path.name}...")
    capsules = ingestor.ingest(transcript_path, args.provider, args.model)
    print(f"Extracted {len(capsules)} task capsules.")
    for c in capsules:
        print(f"- {c.get('task')}")
    return 0

def cmd_compile_prompt(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.prompt_compiler import compile_context
    root = Path(args.root).resolve()
    print(compile_context(root))
    return 0

def cmd_persona_sync(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.modules.persona import PersonaManager
    root = Path(args.root).resolve()
    
    pm = PersonaManager(config.persona_memory_dir)
    transcript_path = Path(args.log_file).resolve()
    
    print(f"Extracting persona from {transcript_path.name}...")
    success = pm.sync_from_transcript(transcript_path, args.provider, args.model)
    if success:
        print(f"Persona successfully synced to {config.persona_memory_dir / 'persona.yaml'}")
        return 0
    else:
        print("Failed to sync persona.")
        return 1



def cmd_persona(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.modules.persona import PersonaManager
    root = Path(args.root).resolve()
    
    pm = PersonaManager(config.persona_memory_dir)
    print(pm.get_persona())
    return 0

def cmd_search(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    root = Path(args.root).resolve()
    config_path = args.config or os.environ.get("MEMORY_OS_CONFIG_PATH")
    searcher = MemorySearcher(config)

    matches = searcher.search_memory(args.query, args.depth)

    if args.json:
        print(json.dumps(matches, indent=2))
    else:
        nodes = [m for m in matches if m["type"] != "code_file"]
        code_files = [m for m in matches if m["type"] == "code_file"]

        if not nodes and not code_files:
            print(f"No matches found for query '{args.query}'")
            return 0

        if nodes:
            print(f"Found {len(nodes)} matched memory nodes:")
            for node in nodes:
                print(f"\n[{node['id']}] ({node['type']})")
                print(f"  Summary: {node['summary']}")
                print(f"  Status: {node['status']} | Trust: {node['trust']}")
                if node.get("evidence"):
                    print(f"  Evidence: {', '.join(node['evidence'])}")

        if code_files:
            if nodes:
                print("\n" + "="*50 + "\n")
            print(f"Found {len(code_files)} matched codebase files:")
            for item in code_files:
                print(f"\n[{item['id']}] ({item['layer']}) - Rank {item['rank']} ({item['match_type']})")
                if item.get("classes"):
                    print(f"  Classes: {', '.join(item['classes'])}")
                if item.get("functions"):
                    print(f"  Functions: {', '.join(item['functions'])}")
                if item.get("routes"):
                    print(f"  Routes: {', '.join(item['routes'])}")
                if item.get("dependencies"):
                    print(f"  Dependencies: {', '.join(item['dependencies'])}")
                if item.get("headings"):
                    print(f"  Headings: {', '.join(item['headings'])}")
                preview = item["summary"][:240]
                print(f"  Preview: {preview}...")
    return 0

def cmd_analyze_os(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.config import MemoryOSConfig
    from memory_os.toolkit.analyzer import OSPerformanceAnalyzer
    import sys
    
    root = Path(args.root).resolve()
    
    analyzer = OSPerformanceAnalyzer(config)
    print("Gathering local telemetry and performance digest...")
    result = analyzer.generate_insights()
    
    if result["status"] == "error":
        print(f"Error generating insights: {result['reason']}", file=sys.stderr)
        return 1
    elif result["status"] == "skipped":
        print(f"Skipped: {result['reason']}")
        return 0
        
    print(f"Success! Generated {result['created_proposals']} new performance insights.")
    print("Review them in agent_proposals/admin_proposals.jsonl.")
    if args.verbose:
        print("\n--- DIGEST SENT TO LLM ---")
        print(result["digest"])
    return 0

def cmd_giant_scan(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.giant_scan import GiantScanRunner

    root = Path(args.root).resolve()

    runner = GiantScanRunner(config)
    result = runner.run(
        provider=args.provider,
        model=args.model,
        force=args.force,
        dry_run=args.dry_run,
        target_dir=args.target_dir,
    )

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        from memory_os.toolkit.giant_scan import _print_markdown
        _print_markdown(result)

    return 0 if result.get("status") in ("success", "dry_run") else 1

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Memory OS project-local CLI.")
    parser.add_argument("--root", default=str(ROOT), help="Project root")
    parser.add_argument("--config", help="Path to memory_os.config.json file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create missing Memory OS control files.")
    init_parser.set_defaults(func=cmd_init)

    integrate_parser = subparsers.add_parser("integrate", help="Add minimal Memory OS agent instructions.")
    integrate_parser.set_defaults(func=cmd_integrate)

    audit_parser = subparsers.add_parser("audit", help="Audit Memory OS control-plane state.")
    audit_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    audit_parser.set_defaults(func=cmd_audit)

    validate_parser = subparsers.add_parser("validate", help="Validate task capsules and lifecycle JSONL.")
    validate_parser.set_defaults(func=cmd_validate)

    snapshot_parser = subparsers.add_parser("snapshot", help="Build compact memory snapshot for this repo.")
    snapshot_parser.add_argument("--write", action="store_true", help="Write agent_context/memory_snapshot.json")
    snapshot_parser.set_defaults(func=cmd_snapshot)

    quantize_parser = subparsers.add_parser("quantize", help="Quantize a task into the 12-step Memory OS scale.")
    quantize_parser.add_argument("--task", required=True, help="Task description")
    quantize_parser.add_argument("--risk", type=float, default=0.0)
    quantize_parser.add_argument("--volume", type=float, default=0.0)
    quantize_parser.add_argument("--uncertainty", type=float, default=0.0)
    quantize_parser.add_argument("--format", choices={"json", "text"}, default="text")
    quantize_parser.set_defaults(func=cmd_quantize)

    workflows_parser = subparsers.add_parser("workflows", help="Validate workflow TOML specs and build a manifest.")
    workflows_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    workflows_parser.add_argument("--write-manifest", action="store_true")
    workflows_parser.add_argument("--manifest-path", default="memory/workflow_manifest.json")
    workflows_parser.set_defaults(func=cmd_workflows)

    compact_parser = subparsers.add_parser(
        "compact",
        help="Parse task capsules to extract new memory nodes and edges via LLM.",
    )
    compact_parser.add_argument("--provider", help="Optional provider override (gemini, openrouter, openai)")
    compact_parser.add_argument("--model", help="Optional model override")
    compact_parser.set_defaults(func=cmd_compact)

    compress_parser = subparsers.add_parser(
        "compress",
        help="Use LLM to semantically merge verified memory nodes.",
    )
    compress_parser.add_argument("--provider", help="Optional provider override (gemini, openrouter, openai)")
    compress_parser.add_argument("--model", help="Optional model override")
    compress_parser.set_defaults(func=cmd_compress)

    prune_parser = subparsers.add_parser(
        "prune",
        help="Archive stale and superseded memory nodes and edges.",
    )
    prune_parser.set_defaults(func=cmd_prune)

    analyze_os_parser = subparsers.add_parser(
        "analyze-os",
        help="Analyze Memory OS algorithms and LLM telemetry to generate actionable insights."
    )
    analyze_os_parser.add_argument("-v", "--verbose", action="store_true", help="Print the local digest sent to LLM")
    analyze_os_parser.set_defaults(func=cmd_analyze_os)

    giant_scan_parser = subparsers.add_parser(
        "giant-scan",
        help="Full-context audit: send entire codebase + Memory OS graph to a large-context LLM."
    )
    giant_scan_parser.add_argument("--provider", default="gemini", help="LLM provider")
    giant_scan_parser.add_argument("--model", default="gemini-2.5-pro", help="LLM model ID")
    giant_scan_parser.add_argument("--force", action="store_true", help="Allow repos >500K chars")
    giant_scan_parser.add_argument("--dry-run", action="store_true", help="Collect stats without LLM call")
    giant_scan_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    giant_scan_parser.add_argument("--target-dir", default=None, help="Specific subdirectory to scan (relative to root).")
    giant_scan_parser.set_defaults(func=cmd_giant_scan)

    search_parser = subparsers.add_parser(
        "search",
        help="Query Memory OS nodes, codebase symbols, and traverse relations."
    )
    search_parser.add_argument("query", help="Keyword query or exact symbol.")
    search_parser.add_argument("--depth", type=int, default=1, help="Graph traversal recursion depth.")
    search_parser.add_argument("--json", action="store_true", help="Output raw JSON instead of human-readable text.")
    search_parser.set_defaults(func=cmd_search)

    stats_parser = subparsers.add_parser(
        "stats",
        help="Print LLM telemetry, costs, and latencies as a YAML dashboard.",
    )
    stats_parser.set_defaults(func=cmd_stats)

    rag_parser = subparsers.add_parser(
        "rag",
        help="Search memory based on task description and output active_memory.yaml for RAG.",
    )
    rag_parser.add_argument("query", help="Task description to search memory for.")
    rag_parser.set_defaults(func=cmd_rag)

    ingest_parser = subparsers.add_parser(
        "ingest-transcript",
        help="Extract completed tasks from IDE session transcript to task_capsules.jsonl."
    )
    ingest_parser.add_argument("log_file", help="Path to transcript.jsonl")
    ingest_parser.add_argument("--provider", help="Optional provider override", default="gemini")
    ingest_parser.add_argument("--model", help="Optional model override", default="")
    ingest_parser.set_defaults(func=cmd_ingest_transcript)

    compile_parser = subparsers.add_parser(
        "compile-prompt",
        help="Compile generic Memory OS context into a single system prompt."
    )
    compile_parser.set_defaults(func=cmd_compile_prompt)

    persona_sync_parser = subparsers.add_parser(
        "persona-sync",
        help="Extract User Persona from a transcript log.",
    )
    persona_sync_parser.add_argument("log_file", help="Path to transcript.jsonl")
    persona_sync_parser.add_argument("--provider", help="Optional provider override", default="gemini")
    persona_sync_parser.add_argument("--model", help="Optional model override", default="")
    persona_sync_parser.set_defaults(func=cmd_persona_sync)

    persona_parser = subparsers.add_parser(
        "persona",
        help="Print the current User Persona profile.",
    )
    persona_parser.set_defaults(func=cmd_persona)

    return parser

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    
    config_path = args.config
    if not config_path and args.root:
        root_path = Path(args.root).resolve()
        candidate = root_path / "memory_os.config.json"
        if candidate.exists():
            config_path = str(candidate)
            
    if config_path:
        os.environ["MEMORY_OS_CONFIG_PATH"] = config_path
        
    return args.func(args, config)

if __name__ == "__main__":
    raise SystemExit(main())
