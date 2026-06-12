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

# Load .env from the current working directory (the user's project root)
_env_file = Path.cwd() / ".env"
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
    from memory_os.modules.context import ContextRegistry
    root = Path(args.root).resolve()
    registry = ContextRegistry(str(root))
    snapshot = registry.build_snapshot(paths=["."])
    if args.write:
        snapshot_file = config.snapshot_file
        snapshot_file.parent.mkdir(parents=True, exist_ok=True)
        with open(snapshot_file, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        print(f"Snapshot successfully written to {snapshot_file.relative_to(root)}")
    else:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    return 0

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
    from memory_os.modules.compactor import MemoryCompactor
    compactor = MemoryCompactor(config=config)
    return compactor.compact_capsules(provider=args.provider, model=args.model)

def cmd_sync(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.repository import MemoryRepository
    from memory_os.core.storage import FileSystemMemoryStorage
    
    repo = MemoryRepository(FileSystemMemoryStorage(), config)
    repo.sync_graph_nodes()
    print("Graph nodes successfully synced to SQLite FTS5.")
    return 0

def cmd_export_skills(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.skills_exporter import export_claude_skills
    root = Path(args.root).resolve()
    export_claude_skills(root)
    return 0

def cmd_compress(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    root = Path(args.root).resolve()
    compactor = MemoryCompactor(config)
    return compactor.compress_graph(provider=args.provider, model=args.model, dry_run=args.dry_run)

def cmd_prune(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    root = Path(args.root).resolve()
    lifecycle = LifecycleManager(config)
    return lifecycle.prune()

def cmd_transition(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    lifecycle = LifecycleManager(config)
    ret = lifecycle.transition(validator=args.validator)
    if ret != 0:
        return ret
    if args.prune:
        lifecycle.prune()
    lifecycle.manifest()
    print("Lifecycle transition complete.")
    return 0

def cmd_graph_map(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.graph_mapper import GraphMapper

    mapper = GraphMapper(config)
    result = mapper.run(emit_nodes=args.emit_nodes)

    if result["status"] == "error":
        print(f"Error: {result['reason']}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False, default=list))
        return 0

    print(f"Codebase map written to: {result['output']}")
    print(f"Files indexed: {result['total_files']}")

    god_nodes = result.get("god_nodes", [])
    if god_nodes:
        print(f"\nGod nodes ({len(god_nodes)}):")
        for node in god_nodes:
            print(f"  {node['in_degree']:>3}x  {node['file']}  [{node['layer']}]")
    else:
        print("\nNo god nodes found — run `memory_os snapshot --write` first.")

    clusters = result.get("clusters", [])
    if clusters:
        print(f"\nModule clusters ({len(clusters)}):")
        for c in clusters:
            print(f"  {c['name']}/  ({c['file_count']} files, {c['internal_edges']} internal edges)")

    if args.emit_nodes:
        print("\nCluster nodes emitted to memory/nodes.jsonl.")

    return 0

def cmd_triage(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.storage import FileSystemMemoryStorage

    storage = FileSystemMemoryStorage()
    nodes_path = config.memory_dir / "nodes.jsonl"
    events_path = config.memory_dir / "events.jsonl"

    nodes = storage.load_jsonl(nodes_path)
    draft_nodes = [n for n in nodes if n["status"] == "draft"]

    if not draft_nodes:
        print("No draft nodes to triage.")
        return 0

    verified_nodes = [n for n in nodes if n["status"] == "verified"]

    def _word_overlap(a: str, b: str) -> float:
        wa = set(a.lower().split())
        wb = set(b.lower().split())
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / len(wa | wb)

    non_interactive = args.dry_run or not sys.stdin.isatty()
    if non_interactive:
        print(f"{len(draft_nodes)} draft node(s) pending triage:")
        for n in draft_nodes:
            print(f"  [{n['id']}] ({n['type']}) {n['summary'][:80]}")
        return 0

    approved = rejected = skipped = 0
    updates: Dict[str, Any] = {}
    new_events = []

    print(f"\n=== Memory OS Triage ({len(draft_nodes)} draft nodes) ===")
    print("y = approve  |  n = reject  |  s = skip  |  t tag1,tag2 = tag+approve\n")

    for idx, node in enumerate(draft_nodes, 1):
        print(f"[{idx}/{len(draft_nodes)}]  {node['id']}  ({node['type']})")
        print(f"  Summary : {node['summary']}")
        if node.get("tags"):
            print(f"  Tags    : {', '.join(node['tags'])}")
        if node.get("evidence"):
            print(f"  Evidence: {', '.join(node['evidence'])}")

        similar = sorted(
            [(v["id"], _word_overlap(node["summary"], v["summary"])) for v in verified_nodes],
            key=lambda x: -x[1],
        )
        similar = [(nid, s) for nid, s in similar if s >= 0.4]
        if similar:
            print(f"  ⚠  Similar verified: {similar[0][0]} ({similar[0][1]:.0%} overlap)")

        while True:
            try:
                answer = input("  > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nTriage interrupted.")
                break
            al = answer.lower()
            if al == "y":
                updates[node["id"]] = {"status": "observed", "action": "approved", "tags": []}
                approved += 1
                break
            elif al == "n":
                updates[node["id"]] = {"status": "stale", "action": "rejected", "tags": []}
                rejected += 1
                break
            elif al == "s":
                skipped += 1
                break
            elif al.startswith("t"):
                tag_str = answer[1:].strip().strip(",")
                new_tags = [t.strip() for t in tag_str.split(",") if t.strip()]
                updates[node["id"]] = {"status": "observed", "action": "tagged", "tags": new_tags}
                approved += 1
                break
            else:
                print("  y / n / s / t tag1,tag2")

    if updates:
        now = datetime.now().isoformat(timespec="seconds")
        updated_nodes = []
        for node in nodes:
            upd = updates.get(node["id"])
            if upd:
                node = dict(node)
                node["status"] = upd["status"]
                if upd.get("tags"):
                    merged = list(dict.fromkeys(node.get("tags", []) + upd["tags"]))
                    node["tags"] = merged
                new_events.append({
                    "timestamp": now,
                    "event": "memory.node.triaged",
                    "node_id": node["id"],
                    "claim": f"Human triage: {upd['action']} → {upd['status']}",
                    "evidence": node.get("evidence", []),
                    "validator": "human_triage",
                    "status": "accepted" if upd["action"] != "rejected" else "rejected",
                    "action": upd["action"],
                })
            updated_nodes.append(node)
        storage.save_jsonl(nodes_path, updated_nodes)
        for ev in new_events:
            storage.append_jsonl(events_path, ev)

    print(f"\nTriage complete: {approved} approved, {rejected} rejected, {skipped} skipped.")
    if approved:
        print("Hint: run `memory_os transition` to promote observed → verified.")
    return 0


def cmd_query(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.storage import FileSystemMemoryStorage

    storage = FileSystemMemoryStorage()
    nodes_path = config.memory_dir / "nodes.jsonl"
    internal_nodes_path = config.internal_memory_dir / "nodes.jsonl"

    nodes = storage.load_jsonl(nodes_path)
    if storage.exists(internal_nodes_path):
        nodes += storage.load_jsonl(internal_nodes_path)

    results = nodes
    if args.type:
        results = [n for n in results if n.get("type") == args.type]
    if args.trust:
        results = [n for n in results if n.get("trust") == args.trust]
    if args.status:
        results = [n for n in results if n.get("status") == args.status]
    if args.tag:
        tl = args.tag.lower()
        results = [n for n in results if any(tl == t.lower() for t in n.get("tags", []))]
    if args.since:
        results = [n for n in results if n.get("freshness", "") >= args.since]

    if not results:
        print("No nodes match the given filters.")
        return 0

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0

    print(f"Found {len(results)} node(s):\n")
    for node in results:
        print(f"[{node['id']}]  ({node['type']})")
        print(f"  Summary  : {node['summary']}")
        print(f"  Status   : {node['status']} | Trust: {node['trust']} | Freshness: {node.get('freshness', 'N/A')}")
        if node.get("tags"):
            print(f"  Tags     : {', '.join(node['tags'])}")
        if node.get("evidence"):
            print(f"  Evidence : {', '.join(node['evidence'])}")
        print()
    return 0


def cmd_backlinks(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.storage import FileSystemMemoryStorage

    storage = FileSystemMemoryStorage()
    nodes_path = config.memory_dir / "nodes.jsonl"
    edges_path = config.memory_dir / "edges.jsonl"

    nodes = storage.load_jsonl(nodes_path)
    edges = storage.load_jsonl(edges_path)

    target_id = args.node_id
    all_ids = {n["id"] for n in nodes}
    if target_id not in all_ids:
        print(f"Node '{target_id}' not found in nodes.jsonl.")
        return 1

    inbound_edges = [e for e in edges if e.get("target") == target_id]
    edge_source_ids = {e["source"] for e in inbound_edges}

    related_refs = [
        n for n in nodes
        if target_id in n.get("related_nodes", []) and n["id"] != target_id
    ]
    related_ref_ids = {n["id"] for n in related_refs}

    textual_refs = [
        n for n in nodes
        if n["id"] != target_id
        and n["id"] not in edge_source_ids
        and n["id"] not in related_ref_ids
        and target_id in n.get("summary", "")
    ]

    if not inbound_edges and not related_refs and not textual_refs:
        print(f"No backlinks found for '{target_id}'.")
        return 0

    if args.json:
        print(json.dumps({
            "target": target_id,
            "inbound_edges": inbound_edges,
            "related_node_refs": [n["id"] for n in related_refs],
            "textual_refs": [n["id"] for n in textual_refs],
        }, indent=2, ensure_ascii=False))
        return 0

    nodes_by_id = {n["id"]: n for n in nodes}
    print(f"Backlinks for '{target_id}':\n")

    if inbound_edges:
        print(f"Edges pointing here ({len(inbound_edges)}):")
        for e in inbound_edges:
            src = nodes_by_id.get(e["source"], {})
            print(f"  [{e['source']}] --{e['type']}--> {target_id}")
            if src.get("summary"):
                print(f"    {src['summary'][:90]}")
        print()

    if related_refs:
        print(f"related_nodes references ({len(related_refs)}):")
        for n in related_refs:
            print(f"  [{n['id']}]  {n['summary'][:90]}")
        print()

    if textual_refs:
        print(f"Textual mentions without edge ({len(textual_refs)}):")
        for n in textual_refs:
            print(f"  [{n['id']}]  {n['summary'][:90]}")
        print("  Hint: consider adding edges to formalise these relationships.")

    return 0


def cmd_unlinked(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.storage import FileSystemMemoryStorage

    storage = FileSystemMemoryStorage()
    nodes_path = config.memory_dir / "nodes.jsonl"
    edges_path = config.memory_dir / "edges.jsonl"
    capsules_path = config.capsules_file

    nodes = storage.load_jsonl(nodes_path)
    edges = storage.load_jsonl(edges_path)

    all_node_ids = [n["id"] for n in nodes]
    edge_pairs = {(e["source"], e["target"]) for e in edges}
    edge_pairs |= {(e["target"], e["source"]) for e in edges}

    findings: List[Dict[str, Any]] = []

    for node in nodes:
        summary = node.get("summary", "")
        for other_id in all_node_ids:
            if other_id == node["id"]:
                continue
            if other_id in summary and (node["id"], other_id) not in edge_pairs:
                findings.append({
                    "source": node["id"],
                    "mentioned": other_id,
                    "context": "node_summary",
                    "snippet": summary[:120],
                })

    if storage.exists(capsules_path):
        capsules = storage.load_jsonl(capsules_path)
        for cap in capsules:
            ts = cap.get("timestamp", "?")
            full_text = " ".join([
                cap.get("task", ""),
                cap.get("hurdles_regression", ""),
                cap.get("resolution", ""),
                cap.get("lessons_learned", ""),
            ])
            for node_id in all_node_ids:
                if node_id in full_text:
                    findings.append({
                        "source": f"capsule:{ts}",
                        "mentioned": node_id,
                        "context": "task_capsule",
                        "snippet": full_text[:120],
                    })

    if not findings:
        print("No unlinked mentions found.")
        return 0

    if args.json:
        print(json.dumps(findings, indent=2, ensure_ascii=False))
        return 0

    print(f"Found {len(findings)} unlinked mention(s):\n")
    for f in findings:
        print(f"  {f['source']}  mentions  [{f['mentioned']}]  (via {f['context']})")
        print(f"  └ {f['snippet'][:100]}")
        print()
    print("Run `memory_os backlinks <node-id>` for details, then add edges to formalise.")
    return 0


def cmd_ide_grant(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    import json
    from datetime import datetime
    
    print("Configuring Antigravity Auto-Permissions...")
    home = Path.home()
    config_dir = home / ".gemini" / "config"
    config_path = config_dir / "config.json"
    
    print(f"Target config file: {config_path}")
    config_dir.mkdir(parents=True, exist_ok=True)
    
    wildcards = [
        "command(*)",
        "custom(*)",
        "execute_url(*)",
        "mcp(*)",
        "read_file(*)",
        "read_url(*)",
        "unsandboxed(*)",
        "write_file(*)"
    ]
    
    config_data = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    config_data = json.loads(content)
        except Exception as e:
            print(f"Warning: Failed to parse existing config.json: {e}")
            backup_path = config_path.with_name(f"config.json.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}")
            try:
                config_path.rename(backup_path)
                print(f"Backup saved to: {backup_path}")
            except Exception as backup_err:
                print(f"Error: Could not back up config file: {backup_err}")
                return 1
            config_data = {}
            
    if "userSettings" not in config_data or not isinstance(config_data["userSettings"], dict):
        config_data["userSettings"] = {}
    if "globalPermissionGrants" not in config_data["userSettings"] or not isinstance(config_data["userSettings"]["globalPermissionGrants"], dict):
        config_data["userSettings"]["globalPermissionGrants"] = {}
    if "allow" not in config_data["userSettings"]["globalPermissionGrants"] or not isinstance(config_data["userSettings"]["globalPermissionGrants"]["allow"], list):
        config_data["userSettings"]["globalPermissionGrants"]["allow"] = []
        
    allow_list = config_data["userSettings"]["globalPermissionGrants"]["allow"]
    added_count = 0
    
    for wc in wildcards:
        if wc not in allow_list:
            allow_list.append(wc)
            print(f"Adding permission: {wc}")
            added_count += 1
            
    if added_count > 0:
        config_data["userSettings"]["globalPermissionGrants"]["allow"] = allow_list
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)
            print("Successfully enabled auto-permissions! Antigravity will now run autonomously without prompting.")
            return 0
        except Exception as e:
            print(f"Error: Failed to write config.json: {e}")
            return 1
    else:
        print("All auto-permission wildcard rules are already configured in config.json.")
        return 0

def cmd_stats(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    import yaml
    root = Path(args.root).resolve()
    os_kernel = MemoryOS(db_path=str(root / "data" / "memory_os.db"))
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
        node_data = {
            "id": r.get("id"),
            "summary": r.get("summary")
        }
        if "match_snippet" in r:
            node_data["match_snippet"] = r["match_snippet"]
        formatted.append(node_data)
        
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
                if "match_snippet" in node:
                    print(f"  Snippet: {node['match_snippet']}")
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

def cmd_daemon(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    import subprocess
    import signal
    import urllib.request
    root = Path(args.root).resolve()
    data_dir = root / "data"
    pid_file = data_dir / "daemon.pid"
    
    def send_daemon_request(port: int, path: str, method: str = "GET") -> Optional[dict]:
        url = f"http://127.0.0.1:{port}{path}"
        req = urllib.request.Request(url, method=method)
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    if args.daemon_action == "start":
        if pid_file.exists():
            print("Daemon is already running (PID file exists).")
            return 1
            
        transcript_path = args.log_file or str(root / "agent_context" / "transcript.jsonl")
        
        command = [sys.executable, "-m", "memory_os", "--root", str(root), "_run_daemon_blocking", str(transcript_path)]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        print(f"Daemon started with PID {process.pid}. Run 'python -m memory_os monitor' to view logs.")
        return 0
        
    elif args.daemon_action == "stop":
        # First try to stop gracefully via HTTP IPC
        port = config.daemon_port
        res = send_daemon_request(port, "/stop", method="POST")
        if res and res.get("status") == "stopping":
            print("Daemon stopped gracefully via IPC.")
            return 0
            
        if not pid_file.exists():
            print("Daemon is not running.")
            return 1
        pid = int(pid_file.read_text().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"Sent SIGTERM to daemon (PID {pid}).")
        except ProcessLookupError:
            print("Process not found, cleaning up stale PID file.")
            pid_file.unlink()
        return 0
        
    elif args.daemon_action == "status":
        port = config.daemon_port
        res = send_daemon_request(port, "/status")
        if res:
            print(f"Daemon is RUNNING (PID {res.get('pid')})")
            print("\nDaemon Details (via IPC):")
            print(f"  Last Activity : {res.get('last_activity_time', 'N/A')}")
            print(f"  Last Ingestion: {res.get('last_ingestion_time', 'N/A')}")
            err = res.get('last_ingestion_error')
            if err:
                print(f"  Last Ingestion Error: {err} (at {res.get('last_ingestion_error_time', 'N/A')})")
            print(f"  Watched File  : {res.get('config', {}).get('transcript_path', 'N/A')}")
            print(f"  IPC Port      : {res.get('config', {}).get('daemon_port', 'N/A')}")
            return 0

        # Fallback if IPC unreachable
        status_file = data_dir / "daemon_status.json"
        is_running = False
        pid = None
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, 0)
                is_running = True
            except OSError:
                pass
                
        if is_running:
            print(f"Daemon is RUNNING (PID {pid})")
        else:
            print("Daemon is STOPPED")
            
        if status_file.exists():
            try:
                status_data = json.loads(status_file.read_text(encoding="utf-8"))
                print("\nDaemon Details (fallback):")
                print(f"  Last Activity : {status_data.get('last_activity_time', 'N/A')}")
                print(f"  Last Ingestion: {status_data.get('last_ingestion_time', 'N/A')}")
                err = status_data.get('last_ingestion_error')
                if err:
                    print(f"  Last Ingestion Error: {err} (at {status_data.get('last_ingestion_error_time', 'N/A')})")
                print(f"  Watched File  : {status_data.get('config', {}).get('transcript_path', 'N/A')}")
            except Exception as e:
                print(f"  Could not read status file: {e}")
        return 0 if is_running else 1

    elif args.daemon_action == "sync":
        port = config.daemon_port
        res = send_daemon_request(port, "/sync", method="POST")
        if res and res.get("status") == "sync_triggered":
            print("Daemon sync triggered successfully via IPC.")
            return 0
        print("Could not contact daemon via IPC. Is the daemon running?")
        return 1
    return 0

def cmd_run_daemon_blocking(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.daemon import MemoryDaemon
    root = Path(args.root).resolve()
    transcript_path = Path(args.log_file).resolve()
    daemon = MemoryDaemon(config, transcript_path)
    daemon.run()
    return 0

def cmd_review(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.core import MemoryOS
    from memory_os.core.models import MemoryNode
    db = MemoryOS(config)
    conn = db.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, type, summary FROM graph_nodes WHERE valid_to IS NULL AND status = 'draft'")
        drafts = cursor.fetchall()
        if not drafts:
            print("No draft nodes pending review in SQLite.")
            return 0
            
        print(f"Found {len(drafts)} nodes pending review:")
        for row in drafts:
            print(f"[{row['id']}] ({row['type']}) - {row['summary']}")
        return 0
    finally:
        conn.close()

def cmd_approve(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.core import MemoryOS
    db = MemoryOS(config)
    conn = db.get_connection()
    node_id = args.node_id
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM graph_nodes WHERE id = ? AND valid_to IS NULL AND status = 'draft'", (node_id,))
        if not cursor.fetchone():
            print(f"Node {node_id} is either not found, not active, or not in 'draft' status.")
            return 1
            
        conn.execute("UPDATE graph_nodes SET status = 'verified', trust = 'verified' WHERE id = ? AND valid_to IS NULL", (node_id,))
        conn.commit()
        print(f"Node {node_id} successfully approved and marked as verified.")
        return 0
    except Exception as e:
        print(f"Failed to approve node {node_id}: {e}")
        return 1
    finally:
        conn.close()

def cmd_db_optimize(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.core import MemoryOS
    db = MemoryOS(config)
    print("Optimizing database... This may take a moment depending on DB size.")
    try:
        db.optimize_db()
        print("Database successfully optimized and vacuumed.")
        return 0
    except Exception as e:
        print(f"Failed to optimize database: {e}")
        return 1

def cmd_monitor(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    import time
    root = Path(args.root).resolve()
    log_file = root / "data" / "daemon.log"
    
    if not log_file.exists():
        print(f"Log file {log_file} does not exist yet. Is the daemon running?")
        return 1
        
    print(f"Tailing {log_file}... (Press Ctrl+C to stop)")
    with open(log_file, "r", encoding="utf-8") as f:
        if not getattr(args, 'all', False):
            f.seek(0, 2)
        try:
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                print(line, end="")
        except KeyboardInterrupt:
            print("\nMonitor stopped.")
    return 0


def cmd_export_obsidian(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.obsidian_exporter import export_obsidian_vault
    nodes_path = config.internal_memory_dir / 'nodes.jsonl'
    edges_path = config.internal_memory_dir / 'edges.jsonl'
    root_dir = Path(config.root_dir)
    success = export_obsidian_vault(root_dir, nodes_path, edges_path)
    return 0 if success else 1

def cmd_linear_sync(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.linear_sync import sync_roadmap_with_linear
    root_dir = Path(config.root_dir)
    success = sync_roadmap_with_linear(root_dir)
    return 0 if success else 1

def cmd_doctor(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    import sqlite3
    root = Path(args.root).resolve()
    print("=== Memory OS Diagnostics (doctor) ===\n")
    
    ok = True
    
    # 1. Config Check
    config_file = root / "memory_os.config.json"
    if config_file.exists():
        print(f"  [✓] Config file: Found at {config_file.relative_to(root)}")
    else:
        print("  [!] Config file: Missing! Using default developer profile.")
        
    # 2. Directories Check
    dirs = ["memory", "agent_context", "workflows"]
    for d in dirs:
        dp = root / d
        if dp.exists() and dp.is_dir():
            print(f"  [✓] Directory '{d}': Exists")
        else:
            print(f"  [✗] Directory '{d}': Missing!")
            ok = False
            
    # 3. Core Files Check
    files = [
        ("nodes.jsonl", config.memory_dir / "nodes.jsonl"),
        ("edges.jsonl", config.memory_dir / "edges.jsonl"),
        ("events.jsonl", config.memory_dir / "events.jsonl"),
        ("task_capsules.jsonl", config.capsules_file),
    ]
    for name, path in files:
        if path.exists():
            print(f"  [✓] File '{name}': Exists ({path.stat().st_size} bytes)")
        else:
            print(f"  [✗] File '{name}': Missing!")
            ok = False
            
    # 4. Database Check
    db_path = config.db_path
    if db_path.exists():
        print(f"  [✓] SQLite DB: Found at {db_path.relative_to(root)}")
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            
            cur.execute("SELECT COUNT(*) FROM graph_nodes WHERE valid_to IS NULL")
            nodes_count = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM memory_os_telemetry")
            telemetry_count = cur.fetchone()[0]
            
            print(f"      - Active nodes in SQLite: {nodes_count}")
            print(f"      - Telemetry records: {telemetry_count}")
            conn.close()
        except Exception as e:
            print(f"  [✗] SQLite DB connection error: {e}")
            ok = False
    else:
        print("  [✗] SQLite DB: Missing!")
        ok = False
        
    # 5. API Keys Check (Secrets Shield!)
    keys = ["GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"]
    present_keys = [k for k in keys if os.environ.get(k)]
    if present_keys:
        print(f"  [✓] LLM API Keys configured: {', '.join(present_keys)}")
    else:
        print("  [!] LLM API Keys: None found in environment! (Background calls will fail)")
        
    # 6. Daemon Status Check
    pid_file = root / "data" / "daemon.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            try:
                os.kill(pid, 0)
                print(f"  [✓] Background Daemon: RUNNING (PID {pid})")
            except OSError:
                print(f"  [!] Background Daemon: PID file exists ({pid}) but process is dead.")
        except Exception as e:
            print(f"  [!] Background Daemon: Error checking PID file: {e}")
    else:
        print("  [ ] Background Daemon: STOPPED")
        
    print("")
    if ok:
        print("Doctor diagnostics: ALL CRITICAL PATHS OK")
        return 0
    else:
        print("Doctor diagnostics: CRITICAL PATH ERRORS FOUND! Run 'memory_os init' to resolve.")
        return 1


class _CleanHelpFormatter(argparse.HelpFormatter):
    """Hides subcommands registered with help=argparse.SUPPRESS."""
    def _format_action(self, action):
        if action.help == argparse.SUPPRESS:
            return ""
        result = super()._format_action(action)
        # Also strip SUPPRESS entries from subparsers choice list
        if hasattr(action, "_choices_actions"):
            action._choices_actions = [
                a for a in action._choices_actions if a.help != argparse.SUPPRESS
            ]
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Memory OS project-local CLI.",
        formatter_class=_CleanHelpFormatter,
    )
    parser.add_argument("--root", default=".", help="Project root")
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

    sync_parser = subparsers.add_parser(
        "sync",
        help="Sync JSONL memory nodes to SQLite FTS5 graph database.",
    )
    sync_parser.set_defaults(func=cmd_sync)

    export_skills_parser = subparsers.add_parser(
        "export-skills",
        help="Export Memory OS write-skills for Claude Code to .claude/skills/ directory.",
    )
    export_skills_parser.set_defaults(func=cmd_export_skills)

    compress_parser = subparsers.add_parser(
        "compress",
        help="Use LLM to semantically merge verified memory nodes.",
    )
    compress_parser.add_argument("--provider", help="Optional provider override (gemini, openrouter, openai)")
    compress_parser.add_argument("--model", help="Optional model override")
    compress_parser.add_argument("--dry-run", action="store_true", help="Show what would be merged without writing.")
    compress_parser.set_defaults(func=cmd_compress)

    prune_parser = subparsers.add_parser(
        "prune",
        help="Archive stale and superseded memory nodes and edges.",
    )
    prune_parser.set_defaults(func=cmd_prune)

    transition_parser = subparsers.add_parser(
        "transition",
        help="Promote observed nodes to verified; handle overrides/refutes deprecation; write manifest.",
    )
    transition_parser.add_argument("--prune", action="store_true", help="Also archive stale/superseded nodes after transition.")
    transition_parser.add_argument("--validator", default="cli_transition", help="Validator name recorded in events.jsonl.")
    transition_parser.set_defaults(func=cmd_transition)

    graph_map_parser = subparsers.add_parser("graph-map", help=argparse.SUPPRESS)
    graph_map_parser.add_argument("--emit-nodes", action="store_true")
    graph_map_parser.add_argument("--format", choices={"json", "text"}, default="text")
    graph_map_parser.set_defaults(func=cmd_graph_map)

    analyze_os_parser = subparsers.add_parser("analyze-os", help=argparse.SUPPRESS)
    analyze_os_parser.add_argument("-v", "--verbose", action="store_true")
    analyze_os_parser.set_defaults(func=cmd_analyze_os)

    giant_scan_parser = subparsers.add_parser("giant-scan", help=argparse.SUPPRESS)
    giant_scan_parser.add_argument("--provider", default="gemini")
    giant_scan_parser.add_argument("--model", default="gemini-2.5-pro")
    giant_scan_parser.add_argument("--force", action="store_true")
    giant_scan_parser.add_argument("--dry-run", action="store_true")
    giant_scan_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    giant_scan_parser.add_argument("--target-dir", default=None)
    giant_scan_parser.set_defaults(func=cmd_giant_scan)

    search_parser = subparsers.add_parser(
        "search",
        help="Query Memory OS nodes, codebase symbols, and traverse relations."
    )
    search_parser.add_argument("query", help="Keyword query or exact symbol.")
    search_parser.add_argument("--depth", type=int, default=1, help="Graph traversal recursion depth.")
    search_parser.add_argument("--json", action="store_true", help="Output raw JSON instead of human-readable text.")
    search_parser.set_defaults(func=cmd_search)

    stats_parser = subparsers.add_parser("stats", help=argparse.SUPPRESS)
    stats_parser.set_defaults(func=cmd_stats)

    rag_parser = subparsers.add_parser("rag", help=argparse.SUPPRESS)
    rag_parser.add_argument("query")
    rag_parser.set_defaults(func=cmd_rag)

    ingest_parser = subparsers.add_parser("ingest-transcript", help=argparse.SUPPRESS)
    ingest_parser.add_argument("log_file")
    ingest_parser.add_argument("--provider", default="gemini")
    ingest_parser.add_argument("--model", default="")
    ingest_parser.set_defaults(func=cmd_ingest_transcript)

    compile_parser = subparsers.add_parser("compile-prompt", help=argparse.SUPPRESS)
    compile_parser.set_defaults(func=cmd_compile_prompt)

    persona_sync_parser = subparsers.add_parser("persona-sync", help=argparse.SUPPRESS)
    persona_sync_parser.add_argument("log_file")
    persona_sync_parser.add_argument("--provider", default="gemini")
    persona_sync_parser.add_argument("--model", default="")
    persona_sync_parser.set_defaults(func=cmd_persona_sync)

    persona_parser = subparsers.add_parser("persona", help=argparse.SUPPRESS)
    persona_parser.set_defaults(func=cmd_persona)

    daemon_parser = subparsers.add_parser("daemon", help=argparse.SUPPRESS)
    daemon_parser.add_argument("daemon_action", choices=["start", "stop", "status", "sync"])
    daemon_parser.add_argument("--log-file")
    daemon_parser.set_defaults(func=cmd_daemon)

    monitor_parser = subparsers.add_parser("monitor", help=argparse.SUPPRESS)
    monitor_parser.add_argument("--all", action="store_true")
    monitor_parser.set_defaults(func=cmd_monitor)

    internal_daemon_parser = subparsers.add_parser("_run_daemon_blocking", help=argparse.SUPPRESS)
    internal_daemon_parser.add_argument("log_file")
    internal_daemon_parser.set_defaults(func=cmd_run_daemon_blocking)

    review_parser = subparsers.add_parser("review", help="List all draft memory nodes pending human review.")
    review_parser.set_defaults(func=cmd_review)
    
    approve_parser = subparsers.add_parser("approve", help="Approve a draft memory node and mark it as verified.")
    approve_parser.add_argument("node_id", help="ID of the draft node to approve.")
    approve_parser.set_defaults(func=cmd_approve)

    db_optimize_parser = subparsers.add_parser("db-optimize", help=argparse.SUPPRESS)
    db_optimize_parser.set_defaults(func=cmd_db_optimize)

    triage_parser = subparsers.add_parser(
        "triage",
        help="Interactively review draft nodes: approve (observed), reject (stale), tag, or skip.",
    )
    triage_parser.add_argument("--dry-run", action="store_true", help="List draft nodes without prompting.")
    triage_parser.set_defaults(func=cmd_triage)

    query_parser = subparsers.add_parser(
        "query",
        help="Filter memory nodes by metadata (type, trust, status, tag, date).",
    )
    query_parser.add_argument("--type", help="Filter by node type (rule, fact, policy, …)")
    query_parser.add_argument("--trust", help="Filter by trust level (verified, unverified, extracted, inferred)")
    query_parser.add_argument("--status", help="Filter by status (draft, observed, verified, stale, superseded)")
    query_parser.add_argument("--tag", help="Filter by tag (exact match, case-insensitive)")
    query_parser.add_argument("--since", help="Filter nodes with freshness >= ISO date (e.g. 2026-06-01)")
    query_parser.add_argument("--json", action="store_true", help="Output raw JSON.")
    query_parser.set_defaults(func=cmd_query)

    backlinks_parser = subparsers.add_parser(
        "backlinks",
        help="Show all nodes that reference a given node ID via edges, related_nodes, or text.",
    )
    backlinks_parser.add_argument("node_id", help="Target node ID to look up.")
    backlinks_parser.add_argument("--json", action="store_true", help="Output raw JSON.")
    backlinks_parser.set_defaults(func=cmd_backlinks)

    unlinked_parser = subparsers.add_parser("unlinked", help=argparse.SUPPRESS)
    unlinked_parser.add_argument("--json", action="store_true")
    unlinked_parser.set_defaults(func=cmd_unlinked)

    ide_grant_parser = subparsers.add_parser("ide-grant", help=argparse.SUPPRESS)
    ide_grant_parser.set_defaults(func=cmd_ide_grant)

    obsidian_parser = subparsers.add_parser("export-obsidian", help=argparse.SUPPRESS)
    obsidian_parser.set_defaults(func=cmd_export_obsidian)

    linear_parser = subparsers.add_parser("linear-sync", help=argparse.SUPPRESS)
    linear_parser.set_defaults(func=cmd_linear_sync)

    doctor_parser = subparsers.add_parser("doctor", help="Check system dependencies, files, DB, and environment.")
    doctor_parser.set_defaults(func=cmd_doctor)


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
    else:
        # Default to current working directory if no root or config given
        config_path = str(Path.cwd() / "memory_os.config.json")
        
    config = MemoryOSConfig(config_path)
    return args.func(args, config)

if __name__ == "__main__":
    raise SystemExit(main())
