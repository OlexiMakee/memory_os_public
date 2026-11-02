import argparse
import json
import sys
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, List

from memory_os import MemoryOSConfig, MemoryOS
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.toolkit.auditor import to_markdown

UTC = timezone.utc
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

def cmd_spec(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.spec_workflow import SpecManager, report_to_markdown

    manager = SpecManager(Path(args.root).resolve())
    action = args.spec_action
    if action == "init":
        try:
            paths = manager.init_feature(
                title=args.title,
                description=args.description or "",
                feature_id=args.id,
                force=args.force,
            )
        except (FileExistsError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        result = paths.to_dict(manager.root)
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"Created spec workspace: {result['root']}")
            print(f"- spec: {result['spec']}")
            print(f"- plan: {result['plan']}")
            print(f"- tasks: {result['tasks']}")
            print(f"- checklist: {result['checklist']}")
        return 0

    if action == "constitution":
        path = manager.ensure_constitution(force=args.force)
        if args.format == "json":
            print(json.dumps({"path": str(path.relative_to(manager.root))}, ensure_ascii=False, indent=2))
        else:
            print(f"Wrote {path.relative_to(manager.root)}")
        return 0

    if action == "list":
        features = manager.list_features()
        if args.format == "json":
            print(json.dumps({"features": features}, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            if not features:
                print("No specs found.")
            for feature in features:
                print(f"{feature['feature_id']}\t{feature['path']}")
        return 0

    if action == "analyze":
        try:
            report = manager.analyze(args.feature)
        except (FileNotFoundError, ValueError) as exc:
            report = {
                "ok": False,
                "feature_id": args.feature,
                "files": {},
                "requirements": [],
                "scenarios": [],
                "tasks": [],
                "errors": [str(exc)],
                "warnings": [],
            }
        if args.format == "json":
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(report_to_markdown(report))
        return 0 if report["ok"] else 1

    if action == "sync":
        from memory_os.toolkit.spec_sync import sync_specs_to_memory
        result = sync_specs_to_memory(config)
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"Spec workflow synced: {result['features']} features, {result['requirements']} requirements, {result['scenarios']} scenarios, {result['tasks']} tasks.")
            print(f"Total graph updates: {result['nodes_upserted']} nodes, {result['edges_upserted']} edges.")
        return 0

    raise ValueError(f"Unsupported spec action: {action}")

def cmd_contract(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.spec_workflow import SpecManager, contract_to_markdown

    manager = SpecManager(Path(args.root).resolve())
    try:
        contract = manager.write_contract(args.feature, risk_class=args.risk_class, force=args.force)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(contract_to_markdown(contract))
        print(f"\nWrote {contract['contract_md']} and {contract['contract_json']}")
    return 0

def cmd_context(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.context_pack import ContextPackBuilder

    builder = ContextPackBuilder(config)
    pack = builder.build(
        task=args.task or "",
        contract_path=args.contract,
        paths=args.path or None,
        include_private=args.include_private,
    )

    written = None
    if not args.dry_run:
        from memory_os.core.write_budget import ArtifactWriteBudget

        slug_source = args.task or (Path(args.contract).stem if args.contract else "pack")
        slug = re.sub(r"[^a-z0-9]+", "-", slug_source.lower()).strip("-")[:40] or "pack"
        out_dir = config.root_dir / "agent_context" / "context_packs" / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        write_budget = ArtifactWriteBudget(config)
        write_budget.write_text(out_dir / "pack.json", json.dumps(pack, indent=2), encoding="utf-8")
        write_budget.write_text(out_dir / "pack.md", builder.to_markdown(pack), encoding="utf-8")
        written = out_dir.relative_to(config.root_dir)

    if args.format == "json":
        print(json.dumps(pack, indent=2))
    else:
        print(builder.to_markdown(pack))

    if written:
        print(f"\nWrote {written}/pack.json and {written}/pack.md")
    return 0

def cmd_evidence(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.evidence import EvidenceStore, bundle_to_markdown

    store = EvidenceStore(config)
    action = args.evidence_action

    try:
        if action == "init":
            bundle = store.init(args.task, risk_class=args.risk_class, force=args.force, dry_run=args.dry_run)
            if args.format == "json":
                print(json.dumps(bundle, indent=2))
            else:
                print(f"{'Would create' if args.dry_run else 'Created'} evidence bundle for task '{args.task}'" + (f" (risk class: {args.risk_class})" if args.risk_class else ""))
            return 0

        if action == "add-command":
            command = list(args.command)
            if command and command[0] == "--":
                command = command[1:]
            if not command:
                print("Error: no command given after '--'", file=sys.stderr)
                return 1
            bundle = store.add_command(args.task, command, dry_run=args.dry_run)
            entry = bundle["_last_command"]
            if args.format == "json":
                print(json.dumps(entry, indent=2))
            else:
                print(f"$ {entry['command']}")
                print(entry["output_summary"])
                print(f"\nexit code: {entry['exit_code']}" + ("  (dry-run, not saved)" if args.dry_run else ""))
            return entry["exit_code"]

        if action == "summarize":
            bundle = store.summarize(
                args.task,
                manual_checks=args.manual_check,
                known_gaps=args.known_gap,
                reviewer_notes=args.reviewer_note,
                dry_run=args.dry_run,
            )
            if args.format == "json":
                print(json.dumps(bundle, indent=2))
            else:
                print(bundle_to_markdown(bundle))
            return 0

        # verify
        result = store.verify(args.task)
        if args.format == "json":
            print(json.dumps(result, indent=2))
        else:
            print(f"Evidence verify: {'OK' if result['ok'] else 'FAILED'} (task {args.task})")
            for reason in result["reasons"]:
                print(f"  [!] {reason}")
        return 0 if result["ok"] else 1
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except FileExistsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

def cmd_security_scan(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.security_scan import SecurityScanner

    try:
        result = SecurityScanner(config).scan(profile=args.profile)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"Profile: {result['profile']}")
        print(f"Scanned {len(result['scanned_files'])} file(s).")
        print(f"Secrets: {result['secret_count']}  |  Prompt-injection markers: {result['injection_marker_count']}")
        for f in result["findings"]:
            print(f"  [!] {f['file']}:{f['line']} {f['category']}/{f['pattern']} -> {f['excerpt']}")
    return 1 if (result["secret_count"] or result["injection_marker_count"]) else 0

def cmd_review_pack(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.review_pack import ReviewPackBuilder, review_pack_to_markdown

    builder = ReviewPackBuilder(config)
    try:
        pack = builder.build(args.task)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(pack, indent=2))
    else:
        print(review_pack_to_markdown(pack))
    return 0

def cmd_codebase(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.adapters import DomainAdapterIngestor
    from memory_os.core.repository import MemoryRepository
    from memory_os.core.safe_id import confine_to_root

    if args.codebase_action != "index":
        print(f"Unknown codebase action: {args.codebase_action}", file=sys.stderr)
        return 1

    try:
        source_root = confine_to_root(args.source, config.root_dir)
        repository = MemoryRepository(FileSystemMemoryStorage(), config)
        report = DomainAdapterIngestor(repository).ingest_python_tree(
            source_root=source_root,
            project_root=config.root_dir,
            protocol_level=args.protocol_level,
            dry_run=args.dry_run,
        )
    except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        operations = report["operations_planned"] if args.dry_run else report["operations_applied"]
        print(
            f"Codebase index: files={report['files_indexed']}, "
            f"operations={'planned' if args.dry_run else 'applied'}:{operations}, "
            f"storage_patches={report['storage_patches_applied']}, "
            f"source={report['source_root']}"
        )
    return 0

def cmd_triage(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.storage import FileSystemMemoryStorage
    from memory_os.core.repository import MemoryRepository
    from memory_os.core.timecode import now_local_iso
    from memory_os.toolkit.memory_graph_service import MemoryGraphService

    storage = FileSystemMemoryStorage()
    repository = MemoryRepository(storage, config)
    nodes_path = config.memory_dir / "nodes.jsonl"

    nodes = storage.load_jsonl(nodes_path)
    draft_nodes = [n for n in nodes if n["status"] == "draft"]

    if not draft_nodes:
        print("No draft nodes to triage.")
        return 0

    non_interactive = args.dry_run or not sys.stdin.isatty()
    if non_interactive:
        print(f"{len(draft_nodes)} draft node(s) pending triage:")
        for n in draft_nodes:
            print(f"  [{n['id']}] ({n['type']}) {n['summary'][:80]}")
        return 0

    approved = rejected = skipped = 0
    updates: Dict[str, Any] = {}
    new_events = []
    draft_ids = {str(node["id"]) for node in draft_nodes}
    similar_by_draft: Dict[str, List[tuple[str, float]]] = {node_id: [] for node_id in draft_ids}
    for candidate in MemoryGraphService(config, repository=repository).get_dedup_candidates(
        focus_ids=draft_ids,
        candidate_status="verified",
        include_all_types=True,
        min_cosine=0.4,
        min_jaccard=0.4,
    ):
        left_id = str(candidate["node_a_id"])
        right_id = str(candidate["node_b_id"])
        draft_id, verified_id = (left_id, right_id) if left_id in draft_ids else (right_id, left_id)
        score = max(float(candidate["cosine"]), float(candidate["jaccard"]))
        similar_by_draft[draft_id].append((verified_id, score))
    for matches in similar_by_draft.values():
        matches.sort(key=lambda item: (-item[1], item[0]))

    print(f"\n=== Memory OS Triage ({len(draft_nodes)} draft nodes) ===")
    print("y = approve  |  n = reject  |  s = skip  |  t tag1,tag2 = tag+approve\n")

    for idx, node in enumerate(draft_nodes, 1):
        print(f"[{idx}/{len(draft_nodes)}]  {node['id']}  ({node['type']})")
        print(f"  Summary : {node['summary']}")
        if node.get("tags"):
            print(f"  Tags    : {', '.join(node['tags'])}")
        if node.get("evidence"):
            print(f"  Evidence: {', '.join(node['evidence'])}")

        similar = similar_by_draft.get(str(node["id"]), [])
        if similar:
            print(f"  ⚠  Similar verified: {similar[0][0]} ({similar[0][1]:.0%} similarity)")

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
        now = now_local_iso(config)
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
        repository.replace_nodes(updated_nodes, events=new_events)

    print(f"\nTriage complete: {approved} approved, {rejected} rejected, {skipped} skipped.")
    if approved:
        print("Hint: run `memory_os transition` to promote observed → verified.")
    return 0

def cmd_review(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.repository import MemoryRepository
    from memory_os.core.storage import FileSystemMemoryStorage

    repo = MemoryRepository(FileSystemMemoryStorage(), config)
    drafts = [n for n in repo.get_nodes() if n.status == "draft"]
    seen_ids = {n.id for n in drafts}

    from memory_os.core.core import MemoryOS
    db = MemoryOS(config)
    conn = db.get_connection()
    try:
        for row in conn.execute("SELECT id, type, summary FROM graph_nodes WHERE valid_to IS NULL AND status = 'draft'"):
            if row["id"] not in seen_ids:
                drafts.append(type("DraftNode", (), {"id": row["id"], "type": row["type"], "summary": row["summary"]})())
                seen_ids.add(row["id"])
    finally:
        conn.close()

    if not drafts:
        print("No draft nodes pending review.")
        return 0

    print(f"Found {len(drafts)} nodes pending review:")
    for node in drafts:
        print(f"[{node.id}] ({node.type}) - {node.summary}")
    return 0

def cmd_approve(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.repository import MemoryRepository
    from memory_os.core.storage import FileSystemMemoryStorage
    from memory_os.core.timecode import now_local_iso

    repo = MemoryRepository(FileSystemMemoryStorage(), config)
    node_id = args.node_id

    try:
        nodes = repo.get_nodes()
        target = next((n for n in nodes if n.id == node_id), None)
        sqlite_row = None
        if target is None:
            from memory_os.core.core import MemoryOS
            db = MemoryOS(config)
            conn = db.get_connection()
            try:
                sqlite_row = conn.execute(
                    "SELECT id, type, summary FROM graph_nodes WHERE id = ? AND valid_to IS NULL AND status = 'draft'",
                    (node_id,),
                ).fetchone()
            finally:
                conn.close()
            if sqlite_row is None:
                print(f"Node {node_id} is either not found or not in 'draft' status.")
                return 1
        elif target.status != "draft":
            print(f"Node {node_id} is either not found or not in 'draft' status.")
            return 1

        now = now_local_iso(config)
        if target is None and sqlite_row is not None:
            repo.upsert_node(
                {
                    "id": sqlite_row["id"],
                    "type": sqlite_row["type"],
                    "summary": sqlite_row["summary"],
                    "evidence": [],
                    "status": "verified",
                    "freshness": now,
                    "trust": "verified",
                    "related_nodes": [],
                    "tags": [],
                    "valid_from": now,
                },
                events=[{
                    "timestamp": now,
                    "event": "memory.node.approved",
                    "node_id": node_id,
                    "claim": f"Approved SQLite draft node: {sqlite_row['summary']}",
                    "evidence": [],
                    "validator": "cli_approve",
                    "status": "accepted",
                }],
            )
        else:
            repo.update_node(
                node_id,
                {"status": "verified", "trust": "verified", "freshness": now, "valid_from": target.valid_from or now},
                events=[{
                    "timestamp": now,
                    "event": "memory.node.approved",
                    "node_id": node_id,
                    "claim": f"Approved node: {target.summary}",
                    "evidence": target.evidence,
                    "validator": "cli_approve",
                    "status": "accepted",
                }],
            )
        print(f"Node {node_id} successfully approved and marked as verified.")
        return 0
    except Exception as e:
        print(f"Failed to approve node {node_id}: {e}")
        return 1
