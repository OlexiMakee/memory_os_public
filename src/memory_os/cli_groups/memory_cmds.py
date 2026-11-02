import argparse
import json
import os
import sys
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, List

from memory_os import MemoryOSConfig, MemoryCompactor, LifecycleManager, MemorySearcher, MemoryOS
from memory_os.core.storage import FileSystemMemoryStorage

UTC = timezone.utc
def cmd_snapshot(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.modules.context import ContextRegistry
    root = config.root_dir
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

def cmd_ingest(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.adapters.markitdown_adapter import MarkItDownAdapter
    from memory_os.core.file_policy import load_export_ignore_patterns, resolve_ingest_path

    export_ignore_patterns = load_export_ignore_patterns(config.root_dir)
    resolved_path, decision = resolve_ingest_path(
        args.path,
        config.root_dir,
        allow_outside_root=args.allow_outside_root,
        include_private=args.include_private,
        export_ignore_patterns=export_ignore_patterns,
    )
    if not decision.allowed:
        result = {
            "ok": False,
            "detail": decision.reason,
            "source_path": args.path,
        }
    else:
        result = MarkItDownAdapter().convert(
            str(resolved_path),
            dry_run=not args.write,
            allowed_root=config.root_dir,
            allow_outside_root=args.allow_outside_root,
        )
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        if not result["ok"]:
            print(f"Error: {result['detail']}", file=sys.stderr)
        else:
            print(f"Converted {result['source_path']} ({result['source_bytes']} bytes, sha256={result['source_sha256'][:16]})")
            print(result["markdown_text"][:2000])
    return 0 if result["ok"] else 1

def cmd_change_size(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.review_pack import change_size_report

    report = change_size_report(config)
    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(f"Changed files: {report['file_count']}")
        for w in report["warnings"]:
            print(f"  [!] {w}")
    return 0

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

def cmd_compress(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    compactor = MemoryCompactor(config)
    return compactor.compress_graph(provider=args.provider, model=args.model, dry_run=args.dry_run)

def cmd_link_infer(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.link_inferrer import LinkInferrer
    inferrer = LinkInferrer(config)
    exclude = set(t.strip() for t in (args.exclude_types or "").split(",") if t.strip())
    return inferrer.run(
        method=args.method,
        resource_mode=getattr(args, "resource_mode", None) or None,
        dry_run=args.dry_run,
        min_score=args.min_score,
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        batch_size=args.batch_size,
        exclude_types=exclude or None,
    )

def cmd_prune(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    lifecycle = LifecycleManager(config)
    return lifecycle.prune()

def _memory_status_counts(config: MemoryOSConfig) -> dict[str, int]:
    storage = FileSystemMemoryStorage()
    nodes_path = config.memory_dir / "nodes.jsonl"
    counts: dict[str, int] = {}
    for node in storage.load_jsonl(nodes_path):
        status = str(node.get("status", "") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts

def _resolve_transition_min_confidence(config: MemoryOSConfig, value: Any) -> float:
    if value is not None:
        return float(value)
    return float(getattr(config, "confidence_threshold", 0.7))

def cmd_transition(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    lifecycle = LifecycleManager(config)
    min_confidence = _resolve_transition_min_confidence(config, getattr(args, "min_confidence", None))
    before_counts = _memory_status_counts(config)
    ret = lifecycle.transition(validator=args.validator, min_confidence=min_confidence)
    if ret != 0:
        return ret
    after_counts = _memory_status_counts(config)
    if args.prune:
        lifecycle.prune()
        after_counts = _memory_status_counts(config)
    lifecycle.manifest()
    verified = after_counts.get("verified", 0)
    held = after_counts.get("draft", 0) + after_counts.get("observed", 0)
    stale = after_counts.get("stale", 0)
    superseded = after_counts.get("superseded", 0)
    before_verified = before_counts.get("verified", 0)
    print(
        "Lifecycle transition complete: "
        f"verified={verified} (+{max(verified - before_verified, 0)}), "
        f"held={held}, stale={stale}, superseded={superseded}, "
        f"min_confidence={min_confidence:.2f}"
    )
    return 0

def cmd_graph_map(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    if getattr(args, "visual", False) or getattr(args, "html", None):
        from pathlib import Path
        from memory_os.modules.graph_visualizer import GraphVisualizer

        visualizer = GraphVisualizer(config)
        output_path = Path(args.html) if getattr(args, "html", None) else None
        saved_path = visualizer.generate_html(output_path=output_path)
        print(f"Visual memory graph written to: {saved_path}")
        return 0

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

def cmd_query(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.memory_graph_service import MemoryGraphService

    payload = MemoryGraphService(config).list_nodes(
        node_type=args.type or "",
        trust=args.trust or "",
        status=args.status or "",
        tag=args.tag or "",
        since=args.since or "",
        include_internal=True,
        limit=getattr(args, "limit", None),
        offset=getattr(args, "offset", 0),
    )
    results = payload["nodes"]

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

def cmd_memory_browse(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.memory_graph_service import MemoryGraphService

    service = MemoryGraphService(config)
    report = service.browse(
        query=getattr(args, "query", ""),
        node_id=getattr(args, "node_id", None),
        depth=getattr(args, "depth", 1),
        limit=getattr(args, "limit", 3),
        neighbors=getattr(args, "neighbors", 8),
        edges_limit=getattr(args, "edges", 12),
    )

    if report["status"] == "not_found":
        print(f"No memory nodes found for '{getattr(args, 'query', '') or getattr(args, 'node_id', '')}'.")
        return 1

    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    print(f"Memory Browse: {report['query'] or report['focus_ids'][0]}")
    for result in report["results"]:
        focus = result["focus"]
        print(f"\n[{focus['id']}] ({focus['type']})")
        print(f"  Status: {focus.get('status', '?')} | Trust: {focus.get('trust', '?')}")
        if result.get("focus_signal"):
            signal = result["focus_signal"]
            print(f"  Signal: degree={signal.get('degree', 0)} | {signal.get('reason', '')}")
        if focus.get("tags"):
            print(f"  Tags: {', '.join(focus['tags'])}")
        print(f"  Summary: {focus.get('summary', '')}")
        if result["related_node_ids"]:
            print(f"  Related: {', '.join(result['related_node_ids'][:8])}")
        if result["outbound_edges"]:
            print("  Outbound:")
            for edge in result["outbound_edges"][: args.edges]:
                print(f"    - {edge['source']} --{edge['type']}--> {edge['target']}")
        if result["inbound_edges"]:
            print("  Inbound:")
            for edge in result["inbound_edges"][: args.edges]:
                print(f"    - {edge['source']} --{edge['type']}--> {edge['target']}")
        if result["neighbor_nodes"]:
            print("  Nearby nodes:")
            for node in result["neighbor_nodes"][: args.neighbors]:
                print(f"    - {node['id']} ({node.get('type', '?')})")
    return 0

def cmd_memory_write(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    """Agent-facing 'remember this' — a draft candidate via the lifecycle gate."""
    import hashlib as _hashlib
    import re as _re
    from memory_os.modules.lifecycle import LifecycleManager

    summary = args.summary.strip()
    if not summary:
        print("Error: --summary is empty", file=sys.stderr)
        return 1
    node_id = args.node_id
    if not node_id:
        slug = _re.sub(r"[^a-z0-9]+", "-", summary.lower()).strip("-")[:48]
        digest = _hashlib.sha1(summary.encode("utf-8")).hexdigest()[:6]
        node_id = f"{args.node_type}:{slug}-{digest}"
    validator = args.validator or os.environ.get("MEMORY_OS_AGENT_ID", "cli")

    lifecycle = LifecycleManager(config)
    rc = lifecycle.propose_candidate(
        node_id=node_id,
        node_type=args.node_type,
        summary=summary,
        evidence=args.evidence,
        confidence=args.confidence,
        validator=validator,
        tags=args.tags,
    )
    if rc == 0:
        print(f"recorded {node_id} [draft, confidence={args.confidence}] — promote via lifecycle gate")
    return rc

def cmd_memory_log(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.modules.history import MemoryHistory

    events = MemoryHistory(config).log(node_id=args.node, limit=args.limit)
    if args.format == "json":
        print(json.dumps(events, indent=2, ensure_ascii=False))
    else:
        if not events:
            print("No events recorded yet." if not args.node else f"No events recorded for '{args.node}'.")
        for e in events:
            print(f"{e.get('timestamp', '?')}  {e.get('event', '?')}  {e.get('node_id', '?')}  [{e.get('status', '?')}]")
            claim = e.get("claim")
            if claim:
                print(f"    {claim}")
    return 0

def cmd_memory_show(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.modules.history import MemoryHistory

    result = MemoryHistory(config).show(args.node_id)
    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if not result["found"]:
            print(f"Node '{args.node_id}' not found in current or archived nodes.")
            return 1
        if result["current"]:
            print(f"Current: status={result['current']['status']}  trust={result['current']['trust']}")
            print(f"  {result['current']['summary']}")
        elif result["archived"]:
            print(f"Archived: status={result['archived'].get('status')}")
            print(f"  {result['archived'].get('summary')}")
        
        shown_node = result["current"] or result["archived"]
        status = shown_node.get("status") if shown_node else ""
        if status in {"archived", "superseded"} and result.get("superseded_by_details"):
            for item in result["superseded_by_details"]:
                reason_suffix = f" ({item['reason']})" if item.get("reason") else ""
                print(f"Superseded by: {item['id']} — {item['summary']}{reason_suffix}")
        if result.get("replaced_by"):
            print(f"\nReplaced by: {', '.join(result['replaced_by'])}")
        if result.get("replaces"):
            print(f"Replaces: {', '.join(result['replaces'])}")
        print(f"\nHistory ({len(result['history'])} event(s)):")
        for e in result["history"]:
            print(f"  {e.get('timestamp', '?')}  {e.get('event', '?')}  [{e.get('status', '?')}]")
    return 0 if result["found"] else 1

def cmd_memory_revert(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.modules.history import MemoryHistory

    result = MemoryHistory(config).revert(args.node_id, dry_run=args.dry_run)
    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if not result["ok"]:
            print(f"Error: {result['detail']}", file=sys.stderr)
        elif result.get("dry_run"):
            print(f"Would restore '{args.node_id}' from archive as draft (dry-run).")
        else:
            print(f"Restored '{args.node_id}' as draft. Run 'memory_os transition' to re-verify it.")
    return 0 if result["ok"] else 1

def cmd_memory_normalize_timecodes(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.modules.timecode_normalizer import TimecodeNormalizer

    result = TimecodeNormalizer(config).normalize()
    payload = result.to_dict()
    if args.format == "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(
            "Timecodes normalized: "
            f"{result.nodes_fixed} node(s) fixed, "
            f"{result.events_fixed} event(s) fixed, "
            f"{result.unresolvable} unresolvable."
        )
    return 0

def cmd_memory_health(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.memory_graph_service import MemoryGraphService

    report = MemoryGraphService(config).health()

    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["status"] != "red" else 1

    print("Memory Health")
    print(f"Status: {report['status']}")
    print(f"Live graph: {report['live_nodes']} node(s), {report['live_edges']} edge(s)")
    print(f"Archived: {report['archived_nodes']} node(s), {report['archived_edges']} edge(s)")
    print(f"Noise: {report['comm_nodes']} comm node(s) ({report['comm_noise_ratio']:.2%})")
    print(f"Orphans: {len(report['orphan_nodes'])} node(s) ({report['orphan_ratio']:.2%})")
    print(f"Density: {report['edge_density']:.2f} edges/node")
    print(
        f"Confidence floor: {report.get('confidence_floor', 0.5):.2f} "
        f"({report.get('low_confidence_count', 0)} node(s) below)"
    )
    if report.get("eval") and report["eval"].get("status") != "skipped":
        metric = report["eval"].get("metric", "eval")
        metric_val = report["eval"].get("recall_at_5", report["eval"].get("pass_rate", 0.0))
        print(f"Eval: {report['eval'].get('suite')} {metric}={metric_val:.2f} (threshold={report['eval'].get('pass_threshold', 'n/a')})")
    else:
        print("Eval: unavailable")
    if report["top_connected_nodes"]:
        print("Top connected:")
        for node in report["top_connected_nodes"]:
            print(f"  - {node.get('id', '')} (degree {node.get('degree', 0)})")
    if report["orphan_nodes"]:
        print("Orphans:")
        for node in report["orphan_nodes"][:5]:
            print(f"  - {node}")
    return 0 if report["status"] != "red" else 1

def cmd_memory_curate(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.memory_graph_service import MemoryGraphService

    report = MemoryGraphService(config).curate(limit=getattr(args, "limit", 10))

    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    print("Memory Curation")
    print(f"Nodes: {report['live_nodes']}  Edges: {report['live_edges']}")
    print(f"Orphans: {len(report['orphan_nodes'])}")
    print(f"Merge candidates: {len(report['merge_candidates'])}")
    if report.get("primary_recommendation") and report["primary_recommendation"] != "none":
        print(f"Primary recommendation: {report['primary_recommendation']}")
    if report.get("next_actions"):
        print("Next actions:")
        for action in report["next_actions"][:5]:
            print(f"  - {action['action']} ({action['priority']}): {action['reason']}")
    for cand in report["merge_candidates"][:10]:
        reasons = ", ".join(cand["reasons"]) if cand["reasons"] else "heuristic"
        print(f"  - {cand['left']} <-> {cand['right']}  score={cand['score']:.2f}  {reasons}")
    if report["components"]:
        print("Components:")
        for comp in report["components"][:5]:
            print(f"  - size={comp['size']} density={comp['density']:.2f} nodes={', '.join(comp['nodes'][:5])}")
    if report["orphan_nodes"]:
        print("Orphans:")
        for nid in report["orphan_nodes"][:10]:
            print(f"  - {nid}")
    return 0

def cmd_memory_dedup_candidates(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.memory_graph_service import MemoryGraphService

    candidates = MemoryGraphService(config).get_dedup_candidates(limit=getattr(args, "limit", None))

    if args.format == "json":
        # Return a simplified serializable version of candidates
        serializable = []
        for c in candidates:
            serializable.append({
                "node_a_id": c["node_a_id"],
                "node_b_id": c["node_b_id"],
                "cosine": c["cosine"],
                "jaccard": c["jaccard"],
                "node_a_confidence": c["node_a"].get("confidence", 1.0),
                "node_a_status": c["node_a"].get("status", "none"),
                "node_b_confidence": c["node_b"].get("confidence", 1.0),
                "node_b_status": c["node_b"].get("status", "none"),
            })
        print(json.dumps(serializable, indent=2, ensure_ascii=False))
        return 0

    print("Memory Deduplication Candidates")
    print(f"Found {len(candidates)} candidate pairs.")
    for cand in candidates:
        max_score = max(cand["cosine"], cand["jaccard"])
        print(f"\n- Pair: {cand['node_a_id']} <-> {cand['node_b_id']} (score={max_score:.4f})")
        print(f"  Similarity: cosine={cand['cosine']:.4f}, jaccard={cand['jaccard']:.4f}")
        print(f"  Node A: confidence={cand['node_a'].get('confidence', 1.0)}, status={cand['node_a'].get('status', 'none')}")
        print(f"    Summary: {cand['node_a'].get('summary', '')}")
        print(f"  Node B: confidence={cand['node_b'].get('confidence', 1.0)}, status={cand['node_b'].get('status', 'none')}")
        print(f"    Summary: {cand['node_b'].get('summary', '')}")
        print(f"  Merge Command: memory_os memory merge-preview {cand['node_a_id']} {cand['node_b_id']}")
    return 0

def cmd_memory_merge_preview(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.memory_graph_service import MemoryGraphService

    report = MemoryGraphService(config).merge_preview(limit=getattr(args, "limit", 10))

    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    print("Memory Merge Preview")
    print(f"Nodes: {report['live_nodes']}  Edges: {report['live_edges']}")
    print(f"Groups: {len(report['merge_groups'])}")
    for group in report["merge_groups"]:
        print(f"  - canonical={group['canonical']} size={group['size']}")
        print(f"    members: {', '.join(group['members'])}")
        print(f"    summary: {group['merged_summary']}")
        if group.get("merged_tags"):
            print(f"    tags: {', '.join(group['merged_tags'])}")
        if group.get("merged_evidence"):
            print(f"    evidence: {', '.join(group['merged_evidence'])}")
    return 0

def cmd_memory_merge_apply(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.memory_graph_service import MemoryGraphService

    report = MemoryGraphService(config).merge_apply(limit=getattr(args, "limit", 10), dry_run=getattr(args, "dry_run", False))
    success = bool(report.get("applied")) or report.get("status") in {"empty", "not_found"} or getattr(args, "dry_run", False)

    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if success else 1

    print("Memory Merge Apply")
    print(f"Applied: {report.get('applied', False)}")
    print(f"Groups: {len(report.get('merge_groups', []))}")
    print(f"Patches: {', '.join(report.get('patch_ids', [])) or 'none'}")
    if report.get("applied_groups") is not None:
        print(f"Applied groups: {report.get('applied_groups', 0)}")
    if report.get("merged_out_nodes"):
        print(f"Merged out: {', '.join(report['merged_out_nodes'][:10])}")
    for group in report.get("merge_groups", []):
        print(f"  - canonical={group['canonical']} size={group['size']}")
        print(f"    members: {', '.join(group['members'])}")
    return 0 if success else 1

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

def cmd_stats(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    os_kernel = MemoryOS(config)
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
        if getattr(args, "json", False):
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(_safe_yaml_dump(report))
        return 0
    finally:
        conn.close()

def cmd_rag(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    root = config.root_dir
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
        f.write(_safe_yaml_dump({"active_context": formatted}))
        
    print(f"Wrote {len(formatted)} memory nodes to {output_path.relative_to(root)}")
    return 0

def cmd_ingest_transcript(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.transcript_ingestor import TranscriptIngestor
    ingestor = TranscriptIngestor(config)
    transcript_path = Path(args.log_file).resolve()
    print(f"Parsing transcript {transcript_path.name}...")
    capsules = ingestor.ingest(transcript_path, args.provider, args.model)
    print(f"Extracted {len(capsules)} task capsules.")
    for c in capsules:
        print(f"- {c.get('task')}")
    return 0

def cmd_search(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    searcher = MemorySearcher(config)

    matches = searcher.search_memory(args.query, args.depth, semantic=args.semantic)

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

def cmd_export_obsidian(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.obsidian_exporter import export_obsidian_vault
    nodes_path = config.internal_memory_dir / 'nodes.jsonl'
    edges_path = config.internal_memory_dir / 'edges.jsonl'
    root_dir = Path(config.root_dir)
    success = export_obsidian_vault(root_dir, nodes_path, edges_path)
    return 0 if success else 1
