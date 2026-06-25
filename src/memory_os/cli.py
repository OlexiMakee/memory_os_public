#!/usr/bin/env python3
"""Portable Memory OS control CLI for project-local operations."""

from __future__ import annotations

import argparse
import json
import re
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
- For non-trivial feature work, run `python -m memory_os spec init "<title>"` and keep spec/plan/tasks traceable.
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
    from memory_os.toolkit.spec_workflow import CONSTITUTION_TEMPLATE

    root = Path(args.root).resolve()
    actions: List[str] = []
    write_if_missing(root / "agent_context" / "WORKFLOWS.md", DEFAULT_WORKFLOWS, actions)
    write_if_missing(
        root / "agent_context" / "HANDSHAKE.md",
        "# Agent Handshake\n\n## Current Session Status\n- Active Agent: unknown\n- Budget Tier applied: `memory_os nano` / score 1\n- Target: Initial Memory OS bootstrap.\n",
        actions,
    )
    write_if_missing(root / "agent_context" / "development_log.md", "# Development Log\n", actions)
    write_if_missing(
        root / "agent_context" / "CONSTITUTION.md",
        CONSTITUTION_TEMPLATE,
        actions,
    )
    write_if_missing(root / "agent_context" / "task_capsules.jsonl", "", actions)
    write_if_missing(root / "memory" / "nodes.jsonl", "", actions)
    write_if_missing(root / "memory" / "edges.jsonl", "", actions)
    write_if_missing(root / "memory" / "events.jsonl", "", actions)
    write_if_missing(root / "specs" / ".gitkeep", "", actions)
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

def cmd_switch_space(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    import urllib.request
    import json
    
    url = f"http://127.0.0.1:{config.daemon_port}/space"
    req = urllib.request.Request(
        url,
        data=json.dumps({"space": args.target_space}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                print(f"[Switched] Daemon space updated to '{args.target_space}'.")
                return 0
    except Exception as e:
        print(f"Failed to switch daemon space. Is the daemon running? ({e})")
        return 1

def cmd_check_updates(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    import memory_os
    
    module_path = Path(memory_os.__file__).parent
    has_changes = False
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", str(module_path)],
            capture_output=True, text=True, check=True
        )
        has_changes = bool(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    print("Memory OS Upstream Configuration:")
    print("  URL: https://github.com/OlexiMakee/memory_os_public")
    
    if has_changes:
        print("\n[!] LOCAL MODIFICATIONS DETECTED [!]")
        print("You have made changes to the local memory_os core.")
        print("Before publishing, separate private planning files from public-facing changes.")

    print("\n[AGENT INSTRUCTION]")
    print("Public releases should target the public repository and omit private planning docs.")
    print("Keep DEV_STRATEGY.md, agent_context/IMPORTANT_PROPOSAL.md, and other internal notes on private remotes only.")
    print("Use normal issues, PRs, or agent proposals for public-facing feature and bug-fix work.")
    return 0

def cmd_validate(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    root = config.root_dir
    
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
            print(f"Error: {exc}")
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

    raise ValueError(f"Unsupported spec action: {action}")


def cmd_contract(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.spec_workflow import SpecManager, contract_to_markdown

    manager = SpecManager(Path(args.root).resolve())
    try:
        contract = manager.write_contract(args.feature, risk_class=args.risk_class, force=args.force)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
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
                print("Error: no command given after '--'")
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
        print(f"Error: {exc}")
        return 1
    except FileExistsError as exc:
        print(f"Error: {exc}")
        return 1


def cmd_eval(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.eval_runner import EvalRunner

    runner = EvalRunner(config)
    action = args.eval_action

    if action == "list":
        suites = runner.list_suites()
        if args.format == "json":
            print(json.dumps(suites, indent=2))
        else:
            for s in suites:
                print(f"{s['name']}\t{s['kind']}\tcases={s['case_count']}\tthreshold={s['pass_threshold']}\t{s['description']}")
        return 0

    if action == "run":
        result = runner.run(args.suite)
        if args.format == "json":
            print(json.dumps(result, indent=2))
        else:
            print(f"{result['suite']} [{result['kind']}]: {result['status']} (pass_rate={result['pass_rate']:.2f}, threshold={result['pass_threshold']})")
            for c in result.get("cases", []):
                print(f"  [{'PASS' if c.get('passed') else 'FAIL'}] {c['id']}: {c.get('detail', '')}")
            if result.get("reason"):
                print(f"  reason: {result['reason']}")
        return 0 if result["ok"] else 1

    if action == "export":
        from memory_os.toolkit.eval_export import write_export

        try:
            path = write_export(args.suite, args.target)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Error: {exc}")
            return 1
        print(f"Wrote {path}")
        return 0

    # compare
    try:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}")
        return 1
    diff = runner.compare(baseline, candidate)
    if args.format == "json":
        print(json.dumps(diff, indent=2))
    else:
        print(f"pass_rate delta: {diff['pass_rate_delta']:+.2f}")
        for f in diff["flipped_cases"]:
            print(f"  {f['id']}: {f['baseline_passed']} -> {f['candidate_passed']}")
    return 0


def cmd_route(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.routing_policy import RoutingPolicy

    decision = RoutingPolicy(config).route(args.task)
    if args.format == "json":
        print(json.dumps(decision, indent=2))
    else:
        print(f"{decision['task_type']} -> {decision['provider']}/{decision['model']} ({decision['reason']})")
    return 0


def cmd_budget(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.routing_policy import RoutingPolicy

    status = RoutingPolicy(config).budget_status()
    if args.format == "json":
        print(json.dumps(status, indent=2))
    else:
        print(f"Tokens used: {status['tokens_used']}/{status['daily_budget']} (remaining: {status['remaining']})")
        if status["exhausted"]:
            print("  [!] daily budget exhausted")
    return 0


def cmd_adapters_audit(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.adapters import (
        ollama_adapter, litellm_adapter, markitdown_adapter, otel_exporter, duckdb_adapter,
        qdrant_adapter, phoenix_exporter, langfuse_exporter, mlflow_exporter, pydantic_ai_bridge,
        vllm_provider, mcp_adapter,
    )

    report = {
        "ollama": ollama_adapter.OllamaAdapter().audit(),
        "litellm": litellm_adapter.LiteLLMAdapter().audit(),
        "markitdown": markitdown_adapter.MarkItDownAdapter().audit(),
        "otel": otel_exporter.OtelExporter(config).audit(),
        "duckdb": duckdb_adapter.DuckDBAdapter(config).audit(),
        "qdrant": qdrant_adapter.QdrantAdapter().audit(),
        "phoenix": phoenix_exporter.PhoenixExporter(config).audit(),
        "langfuse": langfuse_exporter.LangfuseExporter(config).audit(),
        "mlflow": mlflow_exporter.MLflowExporter(config).audit(),
        "pydantic_ai": pydantic_ai_bridge.audit(),
        "vllm": vllm_provider.VLLMProvider().audit(),
        "mcp": mcp_adapter.audit(),
    }
    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        for name, status in report.items():
            print(f"{name}\tavailable={status['available']}")
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
            print(f"Error: {result['detail']}")
        else:
            print(f"Converted {result['source_path']} ({result['source_bytes']} bytes, sha256={result['source_sha256'][:16]})")
            print(result["markdown_text"][:2000])
    return 0 if result["ok"] else 1


def cmd_observe(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.adapters.otel_exporter import OtelExporter

    exporter = OtelExporter(config)
    if args.observe_action == "status":
        result = exporter.audit()
    else:
        result = exporter.export(dry_run=args.dry_run, sample_rate=args.sample_rate)
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(result)
    return 0 if result.get("ok", True) else 1


def cmd_analytics(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.adapters.duckdb_adapter import DuckDBAdapter

    adapter = DuckDBAdapter(config)
    if args.analytics_action == "report":
        result = adapter.report(args.topic)
    else:
        result = adapter.export(format=args.export_format, dry_run=args.dry_run)
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(result)
    return 0 if result.get("ok", True) else 1


def cmd_mcp(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.adapters import mcp_adapter

    if args.mcp_action == "manifest":
        result = mcp_adapter.manifest()
    elif args.mcp_action == "audit":
        result = mcp_adapter.audit()
    else:  # serve
        result = mcp_adapter.serve(dry_run=not args.write)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok", True) else 1


def cmd_run(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.run_records import RunRecordStore

    store = RunRecordStore(config)
    action = args.run_action
    try:
        if action == "start":
            inputs = json.loads(args.inputs) if args.inputs else {}
            record = store.start(args.workflow, inputs=inputs)
        elif action == "status":
            record = store.status(args.run_id)
        elif action == "resume":
            record = store.resume(args.run_id)
        elif action == "complete":
            outputs = json.loads(args.outputs) if args.outputs else {}
            record = store.complete(args.run_id, outputs=outputs)
        elif action == "list":
            runs = store.list_runs()
            if args.format == "json":
                print(json.dumps(runs, indent=2))
            else:
                for r in runs:
                    print(f"{r['run_id']}\t{r['workflow_name']}\t{r['status']}\tstep={r['current_step']}")
            return 0
        else:  # abort
            record = store.abort(args.run_id)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}")
        return 1

    if args.format == "json":
        print(json.dumps(record, indent=2))
    else:
        print(f"{record['run_id']}\t{record['workflow_name']}\t{record['status']}\tstep={record['current_step']}")
    return 0


def cmd_provider(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.routing_policy import RoutingPolicy

    policy = RoutingPolicy(config)
    if args.provider_action == "list":
        providers = policy.list_providers()
        if args.format == "json":
            print(json.dumps(providers, indent=2))
        else:
            for p in providers:
                print(f"{p['name']}\tinstalled={p['adapter_installed']}\tconfigured={p['configured']}")
        return 0

    # test
    result = policy.test_provider(args.name)
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['name']}: {'OK' if result['ok'] else 'NOT READY'} ({result['detail']})")
    return 0 if result["ok"] else 1


def cmd_prompt(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.prompt_registry import PromptRegistry

    registry = PromptRegistry(config)
    action = args.prompt_action

    if action == "list":
        prompts = registry.list_prompts()
        if args.format == "json":
            print(json.dumps(prompts, indent=2))
        else:
            for p in prompts:
                print(f"{p['id']}\tv{p['version']}\t{p['sha256']}\t{p['purpose']}")
        return 0

    if action == "show":
        try:
            data = registry.show(args.id)
        except FileNotFoundError as exc:
            print(f"Error: {exc}")
            return 1
        if args.format == "json":
            print(json.dumps(data, indent=2))
        else:
            print(f"# {data.get('id')} (v{data.get('version')}, {data.get('sha256')})")
            print(f"Purpose: {data.get('purpose')}")
            print(f"Inputs: {data.get('inputs')}  Outputs: {data.get('outputs')}")
            print(f"Forbidden: {data.get('forbidden')}")
            print()
            print(data.get("body", ""))
        return 0

    if action == "render":
        inputs = {}
        for pair in args.input or []:
            if "=" not in pair:
                print(f"Error: --input expects key=value, got {pair!r}")
                return 1
            key, value = pair.split("=", 1)
            inputs[key] = value
        try:
            rendered = registry.render(args.id, inputs)
        except FileNotFoundError as exc:
            print(f"Error: {exc}")
            return 1
        print(rendered)
        return 0

    # verify
    result = registry.verify()
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"Prompt verify: {'OK' if result['ok'] else 'FAILED'}")
        for err in result["errors"]:
            print(f"  [!] {err}")
    return 0 if result["ok"] else 1


def cmd_idea(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.prompt_registry import PromptRegistry, idea_expand_dry_run

    registry = PromptRegistry(config)
    rendered = idea_expand_dry_run(registry, args.text)
    if args.format == "json":
        print(json.dumps({"text": args.text, "rendered_prompt": rendered}, indent=2))
    else:
        print(rendered)
        print("\n(rendered only — no LLM call was made; pass this prompt to a provider yourself)")
    return 0


def cmd_security_scan(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.security_scan import SecurityScanner

    try:
        result = SecurityScanner(config).scan(profile=args.profile)
    except ValueError as exc:
        print(f"Error: {exc}")
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
        print(f"Error: {exc}")
        return 1

    if args.format == "json":
        print(json.dumps(pack, indent=2))
    else:
        print(review_pack_to_markdown(pack))
    return 0


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

def cmd_export_skills(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.skills_exporter import export_claude_skills
    root = Path(args.root).resolve()
    export_claude_skills(root)
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

def cmd_pipeline(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.pipeline import PipelineRunner
    runner = PipelineRunner(config)
    return runner.run(
        pipeline_name=args.name,
        custom_steps=getattr(args, "steps", None),
        notion_key=getattr(args, "notion_key", None),
        notion_db=getattr(args, "notion_db", None),
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        dry_run=args.dry_run,
    )

def cmd_prune(args: argparse.Namespace, config: MemoryOSConfig) -> int:
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


try:
    from memory_os.ide_grant_private import cmd_ide_grant
except ImportError:
    cmd_ide_grant = None


def cmd_stats(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    import yaml
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
        print(yaml.safe_dump(report, default_flow_style=False, sort_keys=False))
        return 0
    finally:
        conn.close()

def cmd_rag(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    import yaml
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
        yaml.safe_dump({"active_context": formatted}, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        
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

def cmd_compile_prompt(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.prompt_compiler import compile_context
    root = Path(args.root).resolve()
    print(compile_context(root))
    return 0

def cmd_persona_sync(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.modules.persona import PersonaManager
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
    pm = PersonaManager(config.persona_memory_dir)
    print(pm.get_persona())
    return 0

def cmd_search(args: argparse.Namespace, config: MemoryOSConfig) -> int:
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
        popen_kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True
        process = subprocess.Popen(command, **popen_kwargs)
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
            if sys.platform == "win32":
                # TerminateProcess is abrupt on Windows — finally blocks in the daemon
                # won't run, so clean up the PID file here.
                pid_file.unlink(missing_ok=True)
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

def cmd_notion_sync(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.notion_sync import sync_with_notion
    success = sync_with_notion(
        config=config,
        notion_api_key=args.api_key,
        notion_database_id=args.database_id,
        to_capsules=args.to_capsules
    )
    return 0 if success else 1

def cmd_gdrive_sync(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.gdrive_sync import sync_with_gdrive
    success = sync_with_gdrive(
        config=config,
        access_token=args.token,
        folder_id=args.folder_id,
        to_capsules=args.to_capsules
    )
    return 0 if success else 1

def cmd_ui(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.ui import run_ui_server
    run_ui_server(config, port=args.port)
    return 0





def cmd_resources(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.disk_guard import DiskGuard
    from memory_os.core.write_budget import ArtifactWriteBudget

    guard = DiskGuard(config)
    write_budget = ArtifactWriteBudget(config)
    action = getattr(args, "resources_action", None) or "snapshot"

    if action == "compact":
        result = guard.compact(dry_run=args.dry_run)
        if args.format == "json":
            print(json.dumps(result, indent=2))
        else:
            print("=== Memory OS Resource Compact" + (" (dry-run)" if args.dry_run else "") + " ===\n")
            checkpoint = result["checkpoint"]
            print(f"  WAL checkpoint : {'OK' if checkpoint.get('ok') else 'FAILED'}")
            if not checkpoint.get("ok"):
                print(f"  Detail         : {checkpoint.get('detail')}")
            print(f"  Resource level : {result['snapshot']['level'].upper()}")
        return 0 if result.get("ok") else 1

    if action == "checkpoint":
        result = guard.checkpoint_sqlite(truncate=not args.no_truncate, dry_run=args.dry_run)
        if args.format == "json":
            print(json.dumps(result, indent=2))
        else:
            print("=== SQLite WAL Checkpoint" + (" (dry-run)" if args.dry_run else "") + " ===\n")
            print(f"  Status : {'OK' if result.get('ok') else 'FAILED'}")
            before = result.get("before", {})
            after = result.get("after", {})
            print(f"  WAL    : {before.get('wal_mb', 0.0)} MB -> {after.get('wal_mb', before.get('wal_mb', 0.0))} MB")
            if not result.get("ok"):
                print(f"  Detail : {result.get('detail')}")
        return 0 if result.get("ok") else 1

    snap = guard.snapshot()
    write_status = write_budget.status()

    if args.format == "json":
        result = snap.to_dict()
        result["write_budget"] = write_status.to_dict()
        print(json.dumps(result, indent=2))
    else:
        print("=== Memory OS Resources ===\n")
        print(f"  Free disk space    : {snap.free_disk_mb:,.1f} MB" + ("  [!] below min_free_disk_mb" if snap.low_disk else ""))
        print(f"  SQLite DB          : {snap.sqlite.db_mb} MB" + ("  [!] exceeds max_sqlite_db_mb" if snap.sqlite.exceeds_max_db else ""))
        print(f"  SQLite WAL         : {snap.sqlite.wal_mb} MB" + ("  [!] exceeds max_sqlite_wal_mb" if snap.sqlite.exceeds_max_wal else ""))
        print(f"  SQLite SHM         : {snap.sqlite.shm_mb} MB")
        print(f"  JSONL source files : {snap.jsonl_total_mb} MB" + ("  [!] exceeds max_jsonl_total_mb" if snap.exceeds_max_jsonl else ""))
        growth = f"{snap.growth_mb_per_hour} MB/hr" if snap.growth_mb_per_hour is not None else "n/a (no prior snapshot)"
        print(f"  Growth rate        : {growth}" + ("  [!] exceeds max_observed_growth_mb_per_hour" if snap.growth_alert else ""))
        write_flag = "  [!] over cap" if not write_status.ok else ""
        print(f"  Agent artifacts    : {write_status.agent_context_mb} MB / {write_status.max_agent_context_mb} MB, {write_status.agent_context_files}/{write_status.max_agent_context_files} files{write_flag}")
        print(f"\nResource level: {snap.level.upper()}")

    return 1 if snap.level == "hot" or not write_status.ok else 0


def cmd_telemetry(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.telemetry_policy import TelemetryPolicy

    db = MemoryOS(config)
    policy = TelemetryPolicy(config, db_path=db.db_path)
    conn = db.get_connection()
    try:
        if args.telemetry_action == "audit":
            report = policy.audit(conn)
            if args.format == "json":
                print(json.dumps(report, indent=2))
            else:
                print("=== Telemetry Audit ===\n")
                db_flag = "  [!] OVER CAP" if report["db_over_cap"] else ("  [!] approaching cap" if report["db_warn_cap"] else "")
                print(f"  Enabled   : {report['enabled']}")
                print(f"  DB size   : {report['db_mb']} MB / {report['max_db_mb']} MB cap{db_flag}")
                print(f"  Retention : {report['retention_days']} days\n")
                for t in report["tables"]:
                    flag = "  [!] OVER CAP" if t["over_cap"] else ("  [!] approaching cap" if t["warn_cap"] else "")
                    print(f"  {t['table']:<24}: {t['row_count']}/{t['max_rows']} rows{flag}")
            return 1 if (report["db_over_cap"] or any(t["over_cap"] for t in report["tables"])) else 0

        # prune
        results = {}
        for table in ("memory_os_telemetry", "memory_os_performance"):
            if args.dry_run:
                budget = policy.table_budget(conn, table)
                results[table] = {
                    "over_cap": budget.over_cap,
                    "row_count": budget.row_count,
                    "max_rows": budget.max_rows,
                    "dry_run": True,
                }
            else:
                results[table] = policy.prune(conn, table)
        if args.format == "json":
            print(json.dumps(results, indent=2))
        else:
            print("=== Telemetry Prune" + (" (dry-run)" if args.dry_run else "") + " ===\n")
            for table, r in results.items():
                print(f"  {table}: {r}")
        return 0
    finally:
        conn.close()


def cmd_release_check(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.release_check import ReleaseChecker

    try:
        result = ReleaseChecker(config).run(target=args.target)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"=== Memory OS Release Check ({result['target']}) ===\n")
        for check in result["checks"]:
            status = "OK" if check["ok"] else ("WARN" if check["severity"] == "warning" else "FAIL")
            print(f"  [{status}] {check['name']}: {check['detail']}")
        print(f"\nResult: {'OK' if result['ok'] else 'FAILED'}")
    return 0 if result["ok"] else 1


def cmd_doctor(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    import sqlite3
    root = config.root_dir
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

            from memory_os.core.telemetry_policy import TelemetryPolicy
            telemetry_report = TelemetryPolicy(config, db_path=db_path).audit(conn)
            if telemetry_report["db_over_cap"]:
                print(f"  [!] Telemetry: DB size {telemetry_report['db_mb']} MB exceeds max_db_mb cap ({telemetry_report['max_db_mb']} MB) — run 'memory_os telemetry prune'")
            elif telemetry_report["db_warn_cap"]:
                print(f"  [!] Telemetry: DB size {telemetry_report['db_mb']} MB approaching max_db_mb cap ({telemetry_report['max_db_mb']} MB)")
            for t in telemetry_report["tables"]:
                if t["over_cap"]:
                    print(f"  [!] Telemetry: '{t['table']}' has {t['row_count']} rows, exceeds max_rows_per_table cap ({t['max_rows']}) — run 'memory_os telemetry prune'")
                elif t["warn_cap"]:
                    print(f"  [!] Telemetry: '{t['table']}' has {t['row_count']} rows, approaching max_rows_per_table cap ({t['max_rows']})")

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
        
    # 5b. Disk / WAL health (DiskGuard)
    from memory_os.core.disk_guard import DiskGuard
    disk_snap = DiskGuard(config).snapshot()
    if disk_snap.low_disk:
        print(f"  [!] Disk: {disk_snap.free_disk_mb:,.1f} MB free — below min_free_disk_mb threshold")
    else:
        print(f"  [✓] Disk: {disk_snap.free_disk_mb:,.1f} MB free")
    if disk_snap.sqlite.exceeds_max_wal:
        print(f"  [!] SQLite WAL: {disk_snap.sqlite.wal_mb} MB — exceeds max_sqlite_wal_mb cap")
    elif disk_snap.sqlite.wal_mb:
        print(f"      - SQLite WAL: {disk_snap.sqlite.wal_mb} MB")

    # 5c. Last evidence bundle status
    evidence_dir = root / "agent_context" / "evidence"
    bundles = sorted(evidence_dir.glob("*/bundle.json"), key=lambda p: p.stat().st_mtime) if evidence_dir.is_dir() else []
    if bundles:
        from memory_os.core.evidence import EvidenceStore
        last_task = bundles[-1].parent.name
        verify_result = EvidenceStore(config).verify(last_task)
        status = "OK" if verify_result["ok"] else "NOT VERIFIED"
        print(f"  [{'✓' if verify_result['ok'] else '!'}] Last evidence bundle: task '{last_task}' — {status}")
        for reason in verify_result["reasons"]:
            print(f"      - {reason}")
    else:
        print("  [ ] Last evidence bundle: none recorded yet")

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
    parser.add_argument("--space", type=str, default="default", help="Memory space to operate on (e.g. default, user_persona)")
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

    spec_parser = subparsers.add_parser(
        "spec",
        help="Create and validate spec-driven development artifacts.",
    )
    spec_subparsers = spec_parser.add_subparsers(dest="spec_action", required=True)

    spec_init_parser = spec_subparsers.add_parser("init", help="Create specs/<id>/ files.")
    spec_init_parser.add_argument("title", help="Feature or change title.")
    spec_init_parser.add_argument("--description", default="", help="Short goal statement.")
    spec_init_parser.add_argument("--id", help="Explicit feature id, e.g. 001-retrieval-router.")
    spec_init_parser.add_argument("--force", action="store_true", help="Overwrite existing spec files.")
    spec_init_parser.add_argument("--format", choices={"json", "text"}, default="text")
    spec_init_parser.set_defaults(func=cmd_spec)

    spec_constitution_parser = spec_subparsers.add_parser(
        "constitution",
        help="Create agent_context/CONSTITUTION.md if missing.",
    )
    spec_constitution_parser.add_argument("--force", action="store_true", help="Overwrite existing constitution.")
    spec_constitution_parser.add_argument("--format", choices={"json", "text"}, default="text")
    spec_constitution_parser.set_defaults(func=cmd_spec)

    spec_list_parser = spec_subparsers.add_parser("list", help="List local specs.")
    spec_list_parser.add_argument("--format", choices={"json", "text"}, default="text")
    spec_list_parser.set_defaults(func=cmd_spec)

    spec_analyze_parser = spec_subparsers.add_parser("analyze", help="Validate spec quality gates.")
    spec_analyze_parser.add_argument("feature", nargs="?", help="Feature id or unique prefix. Defaults to latest.")
    spec_analyze_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    spec_analyze_parser.set_defaults(func=cmd_spec)

    contract_parser = subparsers.add_parser(
        "contract",
        help="Derive a machine-readable contract from existing spec/plan artifacts.",
    )
    contract_subparsers = contract_parser.add_subparsers(dest="contract_action", required=True)

    contract_build_parser = contract_subparsers.add_parser("build", help="Build contract.json/contract.md for a spec.")
    contract_build_parser.add_argument("feature", nargs="?", help="Feature id or unique prefix. Defaults to latest.")
    contract_build_parser.add_argument("--risk-class", dest="risk_class", default=None, help="Override the inferred risk class (e.g. low, moderate, migration-risk).")
    contract_build_parser.add_argument("--force", action="store_true", help="Overwrite an existing contract.")
    contract_build_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    contract_build_parser.set_defaults(func=cmd_contract)

    context_parser = subparsers.add_parser(
        "context",
        help="Build a targeted, reproducible context pack instead of dumping the repo into the model.",
    )
    context_subparsers = context_parser.add_subparsers(dest="context_action", required=True)

    context_build_parser = context_subparsers.add_parser("build", help="Build a context pack from a task description and/or a contract file.")
    context_build_parser.add_argument("--task", default="", help="Task description used for relevance scoring.")
    context_build_parser.add_argument("--contract", default=None, help="Path to a contract.json/contract.md to seed task_summary/constraints/verification_plan.")
    context_build_parser.add_argument("--path", action="append", default=[], help="Repeatable root-relative file or directory to scan. Defaults to the project root.")
    context_build_parser.add_argument("--include-private", action="store_true", help="Opt in to files excluded by private/export-ignore policy.")
    context_build_parser.add_argument("--dry-run", action="store_true", help="Print the pack without writing it to agent_context/context_packs/.")
    context_build_parser.add_argument("--format", choices={"markdown", "json"}, default="markdown")
    context_build_parser.set_defaults(func=cmd_context)

    evidence_parser = subparsers.add_parser(
        "evidence",
        help="Build a verification evidence bundle: commands run, exit codes, changed files, gaps.",
    )
    evidence_subparsers = evidence_parser.add_subparsers(dest="evidence_action", required=True)

    evidence_init_parser = evidence_subparsers.add_parser("init", help="Create a new evidence bundle for a task.")
    evidence_init_parser.add_argument("--task", required=True, help="Task id.")
    evidence_init_parser.add_argument("--risk-class", dest="risk_class", default=None)
    evidence_init_parser.add_argument("--force", action="store_true")
    evidence_init_parser.add_argument("--dry-run", action="store_true")
    evidence_init_parser.add_argument("--format", choices={"json", "text"}, default="text")
    evidence_init_parser.set_defaults(func=cmd_evidence)

    evidence_add_command_parser = evidence_subparsers.add_parser("add-command", help="Run a command and record it (exit code + bounded, redacted output) in the bundle.")
    evidence_add_command_parser.add_argument("--task", required=True, help="Task id.")
    evidence_add_command_parser.add_argument("--dry-run", action="store_true", help="Run the command but do not save it to the bundle.")
    evidence_add_command_parser.add_argument("--format", choices={"json", "text"}, default="text")
    evidence_add_command_parser.add_argument("command", nargs=argparse.REMAINDER, help="-- <command and args to run>")
    evidence_add_command_parser.set_defaults(func=cmd_evidence)

    evidence_summarize_parser = evidence_subparsers.add_parser("summarize", help="Refresh changed files, append notes, and render a summary.")
    evidence_summarize_parser.add_argument("--task", required=True, help="Task id.")
    evidence_summarize_parser.add_argument("--manual-check", action="append", default=[], help="Repeatable: append a manual check note.")
    evidence_summarize_parser.add_argument("--known-gap", action="append", default=[], help="Repeatable: append a known gap.")
    evidence_summarize_parser.add_argument("--reviewer-note", action="append", default=[], help="Repeatable: append a reviewer note.")
    evidence_summarize_parser.add_argument("--dry-run", action="store_true")
    evidence_summarize_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    evidence_summarize_parser.set_defaults(func=cmd_evidence)

    evidence_verify_parser = evidence_subparsers.add_parser("verify", help="Exit non-zero unless every recorded command passed and risk_class is set.")
    evidence_verify_parser.add_argument("--task", required=True, help="Task id.")
    evidence_verify_parser.add_argument("--format", choices={"json", "text"}, default="text")
    evidence_verify_parser.set_defaults(func=cmd_evidence)

    review_pack_parser = subparsers.add_parser(
        "review-pack",
        help="Assemble contract + context pack + evidence into one reviewer-facing document.",
    )
    review_pack_parser.add_argument("--task", required=True, help="Task id (same id used for 'evidence init --task').")
    review_pack_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    review_pack_parser.set_defaults(func=cmd_review_pack)

    change_size_parser = subparsers.add_parser(
        "change-size",
        help="Advisory small-batch warnings for the current uncommitted change set.",
    )
    change_size_parser.add_argument("--format", choices={"json", "text"}, default="text")
    change_size_parser.set_defaults(func=cmd_change_size)

    security_parser = subparsers.add_parser(
        "security",
        help="Offline secret and prompt-injection scan over local-first memory stores.",
    )
    security_subparsers = security_parser.add_subparsers(dest="security_action", required=True)
    security_scan_parser = security_subparsers.add_parser("scan", help="Scan memory/evidence/context-pack stores for secrets and injection markers.")
    security_scan_parser.add_argument("--profile", choices={"default", "private-docs", "context-artifacts", "docs", "all"}, default="default")
    security_scan_parser.add_argument("--format", choices={"json", "text"}, default="text")
    security_scan_parser.set_defaults(func=cmd_security_scan)

    prompt_parser = subparsers.add_parser(
        "prompt",
        help="List, show, render, or verify versioned prompt templates (no LLM call).",
    )
    prompt_subparsers = prompt_parser.add_subparsers(dest="prompt_action", required=True)

    prompt_list_parser = prompt_subparsers.add_parser("list", help="List all prompts with id/version/hash.")
    prompt_list_parser.add_argument("--format", choices={"json", "text"}, default="text")
    prompt_list_parser.set_defaults(func=cmd_prompt)

    prompt_show_parser = prompt_subparsers.add_parser("show", help="Show one prompt's metadata and body.")
    prompt_show_parser.add_argument("id", help="Prompt id (matches its filename stem).")
    prompt_show_parser.add_argument("--format", choices={"json", "text"}, default="text")
    prompt_show_parser.set_defaults(func=cmd_prompt)

    prompt_render_parser = prompt_subparsers.add_parser("render", help="Render a prompt body with {{var}} substitutions.")
    prompt_render_parser.add_argument("id", help="Prompt id.")
    prompt_render_parser.add_argument("--input", action="append", help="key=value, repeatable.")
    prompt_render_parser.add_argument("--format", choices={"json", "text"}, default="text")
    prompt_render_parser.set_defaults(func=cmd_prompt)

    prompt_verify_parser = prompt_subparsers.add_parser("verify", help="Check every prompt file has required frontmatter and a matching id.")
    prompt_verify_parser.add_argument("--format", choices={"json", "text"}, default="text")
    prompt_verify_parser.set_defaults(func=cmd_prompt)

    idea_parser = subparsers.add_parser(
        "idea",
        help="Expand a rough idea into a discovery-brief prompt (rendering only, no LLM call).",
    )
    idea_subparsers = idea_parser.add_subparsers(dest="idea_action", required=True)
    idea_expand_parser = idea_subparsers.add_parser("expand", help="Render the idea_expand prompt for a raw idea.")
    idea_expand_parser.add_argument("--text", required=True, help="The raw idea text.")
    idea_expand_parser.add_argument("--dry-run", action="store_true", help="Accepted for forward-compat; rendering is always dry (no LLM call exists yet).")
    idea_expand_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    idea_expand_parser.set_defaults(func=cmd_idea)

    route_parser = subparsers.add_parser("route", help="Route a task to a provider/model via LLMRouter (no network call).")
    route_parser.add_argument("--task", required=True, help="Free-text task description.")
    route_parser.add_argument("--format", choices={"json", "text"}, default="json")
    route_parser.set_defaults(func=cmd_route)

    budget_parser = subparsers.add_parser("budget", help="Token budget status.")
    budget_subparsers = budget_parser.add_subparsers(dest="budget_action", required=True)
    budget_status_parser = budget_subparsers.add_parser("status", help="Show daily token budget status.")
    budget_status_parser.add_argument("--format", choices={"json", "text"}, default="text")
    budget_status_parser.set_defaults(func=cmd_budget)

    provider_parser = subparsers.add_parser("provider", help="List or offline-test known model providers/adapters.")
    provider_subparsers = provider_parser.add_subparsers(dest="provider_action", required=True)
    provider_list_parser = provider_subparsers.add_parser("list", help="List known providers and adapter/config status.")
    provider_list_parser.add_argument("--format", choices={"json", "text"}, default="text")
    provider_list_parser.set_defaults(func=cmd_provider)
    provider_test_parser = provider_subparsers.add_parser("test", help="Offline-only readiness check for one provider (no network call).")
    provider_test_parser.add_argument("name", help="Provider name (see 'provider list').")
    provider_test_parser.add_argument("--format", choices={"json", "text"}, default="text")
    provider_test_parser.set_defaults(func=cmd_provider)

    adapters_parser = subparsers.add_parser("adapters", help="Audit optional adapter availability (offline, no network).")
    adapters_subparsers = adapters_parser.add_subparsers(dest="adapters_action", required=True)
    adapters_audit_parser = adapters_subparsers.add_parser("audit", help="Report install status for every optional adapter.")
    adapters_audit_parser.add_argument("--format", choices={"json", "text"}, default="text")
    adapters_audit_parser.set_defaults(func=cmd_adapters_audit)

    ingest_file_parser = subparsers.add_parser(
        "ingest",
        help="Convert an external document to Markdown via the optional MarkItDown adapter.",
    )
    ingest_subparsers = ingest_file_parser.add_subparsers(dest="ingest_action", required=True)
    ingest_file_sub = ingest_subparsers.add_parser("file", help="Convert one local file (untrusted; no network fetch; no script execution).")
    ingest_file_sub.add_argument("path", help="Local file path.")
    ingest_file_sub.add_argument("--allow-outside-root", action="store_true", help="Explicitly permit reading a file outside the Memory OS workspace.")
    ingest_file_sub.add_argument("--include-private", action="store_true", help="Explicitly permit files hidden by private/export-ignore policy.")
    ingest_file_sub.add_argument("--write", action="store_true", help="Reserved for future persistence; conversion itself never writes to disk.")
    ingest_file_sub.add_argument("--format", choices={"json", "text"}, default="text")
    ingest_file_sub.set_defaults(func=cmd_ingest)

    observe_parser = subparsers.add_parser("observe", help="OpenTelemetry-compatible export status/dry-run over bounded local telemetry.")
    observe_subparsers = observe_parser.add_subparsers(dest="observe_action", required=True)
    observe_status_parser = observe_subparsers.add_parser("status", help="Report OTel SDK availability (offline).")
    observe_status_parser.add_argument("--format", choices={"json", "text"}, default="text")
    observe_status_parser.set_defaults(func=cmd_observe)
    observe_export_parser = observe_subparsers.add_parser("export", help="Export bounded telemetry to OTel spans/metrics (dry-run by default).")
    observe_export_parser.add_argument("--target", choices={"otel"}, default="otel")
    observe_export_parser.add_argument("--dry-run", action="store_true", default=True, help="Default; pass --write to actually attempt an OTel export.")
    observe_export_parser.add_argument("--write", dest="dry_run", action="store_false", help="Attempt a real OTel export (requires the optional SDK).")
    observe_export_parser.add_argument("--sample-rate", dest="sample_rate", type=float, default=1.0)
    observe_export_parser.add_argument("--format", choices={"json", "text"}, default="text")
    observe_export_parser.set_defaults(func=cmd_observe)

    analytics_parser = subparsers.add_parser("analytics", help="Local analytics reports over evals/telemetry/evidence via the optional DuckDB adapter.")
    analytics_subparsers = analytics_parser.add_subparsers(dest="analytics_action", required=True)
    analytics_report_parser = analytics_subparsers.add_parser("report", help="Aggregate one topic.")
    analytics_report_parser.add_argument("--topic", choices={"evals", "telemetry", "evidence"}, required=True)
    analytics_report_parser.add_argument("--format", choices={"json", "text"}, default="text")
    analytics_report_parser.set_defaults(func=cmd_analytics)
    analytics_export_parser = analytics_subparsers.add_parser("export", help="Export an analytics inventory (dry-run by default).")
    analytics_export_parser.add_argument("--export-format", dest="export_format", choices={"json", "parquet"}, default="json")
    analytics_export_parser.add_argument("--dry-run", action="store_true", default=True, help="Default; pass --write to actually write the export file.")
    analytics_export_parser.add_argument("--write", dest="dry_run", action="store_false", help="Actually write the export file (requires the optional duckdb package).")
    analytics_export_parser.add_argument("--format", choices={"json", "text"}, default="text")
    analytics_export_parser.set_defaults(func=cmd_analytics)

    mcp_parser = subparsers.add_parser("mcp", help="MCP capability manifest/audit/serve (optional, least-privilege by default).")
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_action", required=True)
    mcp_manifest_parser = mcp_subparsers.add_parser("manifest", help="Show the allowed/denied MCP tool manifest.")
    mcp_manifest_parser.set_defaults(func=cmd_mcp)
    mcp_audit_parser = mcp_subparsers.add_parser("audit", help="Report MCP SDK availability and tool counts (offline).")
    mcp_audit_parser.set_defaults(func=cmd_mcp)
    mcp_serve_parser = mcp_subparsers.add_parser("serve", help="Dry-run by default; --write attempts a real server (not implemented in this stage).")
    mcp_serve_parser.add_argument("--write", action="store_true", help="Attempt a real MCP server instead of a dry-run description.")
    mcp_serve_parser.set_defaults(func=cmd_mcp)
    for p in (mcp_manifest_parser, mcp_audit_parser, mcp_serve_parser):
        p.add_argument("--format", choices={"json", "text"}, default="json")

    run_parser = subparsers.add_parser("run", help="Lightweight native run/checkpoint records (no workflow engine; see Stage 14).")
    run_subparsers = run_parser.add_subparsers(dest="run_action", required=True)
    run_start_parser = run_subparsers.add_parser("start", help="Start a new run record.")
    run_start_parser.add_argument("--workflow", required=True, help="Workflow name, e.g. idea-to-spec.")
    run_start_parser.add_argument("--inputs", help="JSON object string of inputs.")
    run_start_parser.set_defaults(func=cmd_run)
    run_status_parser = run_subparsers.add_parser("status", help="Show one run's current record.")
    run_status_parser.add_argument("run_id")
    run_status_parser.set_defaults(func=cmd_run)
    run_resume_parser = run_subparsers.add_parser("resume", help="Return the persisted state for a run (no re-execution).")
    run_resume_parser.add_argument("run_id")
    run_resume_parser.set_defaults(func=cmd_run)
    run_complete_parser = run_subparsers.add_parser("complete", help="Mark a run completed with outputs.")
    run_complete_parser.add_argument("run_id")
    run_complete_parser.add_argument("--outputs", help="JSON object string of outputs.")
    run_complete_parser.set_defaults(func=cmd_run)
    run_abort_parser = run_subparsers.add_parser("abort", help="Mark a run aborted.")
    run_abort_parser.add_argument("run_id")
    run_abort_parser.set_defaults(func=cmd_run)
    run_list_parser = run_subparsers.add_parser("list", help="List all run records.")
    run_list_parser.set_defaults(func=cmd_run)
    for p in (run_start_parser, run_status_parser, run_resume_parser, run_complete_parser, run_abort_parser, run_list_parser):
        p.add_argument("--format", choices={"json", "text"}, default="text")

    eval_parser = subparsers.add_parser(
        "eval",
        help="Run local-deterministic and optional LLM-judge eval suites for nondeterministic surfaces.",
    )
    eval_subparsers = eval_parser.add_subparsers(dest="eval_action", required=True)

    eval_list_parser = eval_subparsers.add_parser("list", help="List available eval suites.")
    eval_list_parser.add_argument("--format", choices={"json", "text"}, default="text")
    eval_list_parser.set_defaults(func=cmd_eval)

    eval_run_parser = eval_subparsers.add_parser("run", help="Run one eval suite by name.")
    eval_run_parser.add_argument("suite", help="Suite name (see 'eval list').")
    eval_run_parser.add_argument("--format", choices={"json", "text"}, default="text")
    eval_run_parser.set_defaults(func=cmd_eval)

    eval_compare_parser = eval_subparsers.add_parser("compare", help="Diff two saved 'eval run --format json' result files.")
    eval_compare_parser.add_argument("baseline", help="Path to a saved baseline result JSON file.")
    eval_compare_parser.add_argument("candidate", help="Path to a saved candidate result JSON file.")
    eval_compare_parser.add_argument("--format", choices={"json", "text"}, default="text")
    eval_compare_parser.set_defaults(func=cmd_eval)

    eval_export_parser = eval_subparsers.add_parser("export", help="Export a suite to a best-effort Inspect AI / promptfoo config shape.")
    eval_export_parser.add_argument("suite", help="Suite name (see 'eval list').")
    eval_export_parser.add_argument("--target", choices={"inspect", "promptfoo"}, required=True)
    eval_export_parser.set_defaults(func=cmd_eval)

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

    link_infer_parser = subparsers.add_parser(
        "link-infer",
        help="Automatically discover and add edges between memory nodes.",
    )
    link_infer_parser.add_argument(
        "--method",
        choices=["cascade", "text", "llm", "both"],
        default="cascade",
        help="Edge discovery method: cascade (default — BM25+structural+tags+temporal then LLM on unlinked), text, llm, both.",
    )
    link_infer_parser.add_argument(
        "--resource-mode",
        choices=["quiet", "normal", "max"],
        default=None,
        dest="resource_mode",
        help="Resource budget: quiet (Stage 0 only), normal (+ embeddings when available), max (+ local LM). Defaults to config value.",
    )
    link_infer_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print proposed edges without writing to edges.jsonl.",
    )
    link_infer_parser.add_argument(
        "--min-score",
        type=float,
        default=0.3,
        help="Minimum confidence score for text-matching method (0.0–1.0, default 0.3).",
    )
    link_infer_parser.add_argument(
        "--provider",
        default=None,
        help="LLM provider override (gemini, openrouter, openai).",
    )
    link_infer_parser.add_argument(
        "--model",
        default=None,
        help="LLM model override.",
    )
    link_infer_parser.add_argument(
        "--batch-size",
        type=int,
        default=60,
        help="Number of nodes per LLM batch (default 60).",
    )
    link_infer_parser.add_argument(
        "--exclude-types",
        default="",
        help="Comma-separated node types to skip during edge discovery (e.g. 'chat_history,draft').",
    )
    link_infer_parser.set_defaults(func=cmd_link_infer)

    pipeline_parser = subparsers.add_parser(
        "pipeline",
        help="Run a named sequence of memory_os operations in one command.",
    )
    pipeline_parser.add_argument(
        "name",
        nargs="?",
        default="list",
        help="Pipeline name: ingest | refresh | full | custom | list (default: list).",
    )
    pipeline_parser.add_argument(
        "steps",
        nargs="*",
        help="For 'custom' pipeline: sequence of memory_os subcommands to run.",
    )
    pipeline_parser.add_argument("--notion-key", default=None, help="Notion API key (triggers notion-sync step).")
    pipeline_parser.add_argument("--notion-db", default=None, help="Notion database ID.")
    pipeline_parser.add_argument("--provider", default=None, help="LLM provider for LLM steps.")
    pipeline_parser.add_argument("--model", default=None, help="LLM model override.")
    pipeline_parser.add_argument("--dry-run", action="store_true", help="Print steps without executing.")
    pipeline_parser.set_defaults(func=cmd_pipeline)

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

    if cmd_ide_grant is not None:
        ide_grant_parser = subparsers.add_parser("ide-grant", help=argparse.SUPPRESS)
        ide_grant_parser.set_defaults(func=cmd_ide_grant)

    obsidian_parser = subparsers.add_parser("export-obsidian", help=argparse.SUPPRESS)
    obsidian_parser.set_defaults(func=cmd_export_obsidian)

    linear_parser = subparsers.add_parser("linear-sync", help=argparse.SUPPRESS)
    linear_parser.set_defaults(func=cmd_linear_sync)

    notion_parser = subparsers.add_parser("notion-sync", help="Synchronize memory nodes from a Notion database.")
    notion_parser.add_argument("--api-key", help="Notion Integration Token (NOTION_API_KEY).")
    notion_parser.add_argument("--database-id", help="Notion Database ID (NOTION_DATABASE_ID).")
    notion_parser.add_argument("--to-capsules", action="store_true", help="Import Notion pages as task capsules instead of memory nodes.")
    notion_parser.set_defaults(func=cmd_notion_sync)

    gdrive_parser = subparsers.add_parser("gdrive-sync", help="Synchronize memory nodes from a Google Drive folder.")
    gdrive_parser.add_argument("--token", help="Google Drive Access Token (GDRIVE_ACCESS_TOKEN).")
    gdrive_parser.add_argument("--folder-id", help="Google Drive Folder ID (GDRIVE_FOLDER_ID).")
    gdrive_parser.add_argument("--to-capsules", action="store_true", help="Import Google Drive documents as task capsules instead of memory nodes.")
    gdrive_parser.set_defaults(func=cmd_gdrive_sync)

    ui_parser = subparsers.add_parser("ui", help="Start the Memory OS Visualizer UI server.")
    ui_parser.add_argument("--port", type=int, default=8080, help="Port to run the UI server on.")
    ui_parser.set_defaults(func=cmd_ui)





    doctor_parser = subparsers.add_parser("doctor", help="Check system dependencies, files, DB, and environment.")
    doctor_parser.set_defaults(func=cmd_doctor)

    resources_parser = subparsers.add_parser(
        "resources",
        help="Snapshot free disk space, SQLite DB/WAL size, and JSONL size against configured budgets.",
    )
    resources_subparsers = resources_parser.add_subparsers(dest="resources_action")
    resources_parser.add_argument("--format", choices={"json", "text"}, default="text")
    resources_parser.set_defaults(func=cmd_resources)

    resources_snapshot_parser = resources_subparsers.add_parser("snapshot", help="Report disk/SQLite/JSONL resource health.")
    resources_snapshot_parser.add_argument("--format", choices={"json", "text"}, default="text")
    resources_snapshot_parser.set_defaults(func=cmd_resources)

    resources_checkpoint_parser = resources_subparsers.add_parser("checkpoint", help="Run a SQLite WAL checkpoint.")
    resources_checkpoint_parser.add_argument("--format", choices={"json", "text"}, default="text")
    resources_checkpoint_parser.add_argument("--dry-run", action="store_true")
    resources_checkpoint_parser.add_argument("--no-truncate", action="store_true", help="Use FULL checkpoint instead of TRUNCATE.")
    resources_checkpoint_parser.set_defaults(func=cmd_resources)

    resources_compact_parser = resources_subparsers.add_parser("compact", help="Run bounded local resource compaction actions.")
    resources_compact_parser.add_argument("--format", choices={"json", "text"}, default="text")
    resources_compact_parser.add_argument("--dry-run", action="store_true")
    resources_compact_parser.set_defaults(func=cmd_resources)

    telemetry_parser = subparsers.add_parser(
        "telemetry",
        help="Audit or prune bounded telemetry/performance tables.",
    )
    telemetry_subparsers = telemetry_parser.add_subparsers(dest="telemetry_action", required=True)

    telemetry_audit_parser = telemetry_subparsers.add_parser("audit", help="Report row counts and DB size against configured caps.")
    telemetry_audit_parser.add_argument("--format", choices={"json", "text"}, default="text")
    telemetry_audit_parser.set_defaults(func=cmd_telemetry)

    telemetry_prune_parser = telemetry_subparsers.add_parser("prune", help="Delete rows past retention_days and trim down to max_rows_per_table.")
    telemetry_prune_parser.add_argument("--format", choices={"json", "text"}, default="text")
    telemetry_prune_parser.add_argument("--dry-run", action="store_true", help="Report what would be pruned without deleting anything.")
    telemetry_prune_parser.set_defaults(func=cmd_telemetry)

    release_check_parser = subparsers.add_parser(
        "release-check",
        help="Run deterministic local gates before private or public publishing.",
    )
    release_check_parser.add_argument("--target", choices={"private", "public"}, default="private")
    release_check_parser.add_argument("--format", choices={"json", "text"}, default="text")
    release_check_parser.set_defaults(func=cmd_release_check)

    check_updates_parser = subparsers.add_parser(
        "check-updates",
        help="Check the upstream URL for memory_os and read agent contribution rules."
    )
    check_updates_parser.set_defaults(func=cmd_check_updates)

    switch_space_parser = subparsers.add_parser(
        "switch-space",
        help="Switch the background daemon to a different memory space."
    )
    switch_space_parser.add_argument("target_space", help="Name of the space to switch to (e.g. default, user_persona)")
    switch_space_parser.set_defaults(func=cmd_switch_space)

    return parser

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    
    config_path = args.config
    if not config_path and args.root:
        # Always derive config_path from --root, even if the config file
        # doesn't exist there yet — MemoryOSConfig already defaults missing
        # config to built-in values, and root_dir comes from config_path's
        # parent, so falling through to cwd here would silently operate on
        # the wrong directory instead of the one the caller asked for.
        root_path = Path(args.root).resolve()
        config_path = str(root_path / "memory_os.config.json")

    if config_path:
        os.environ["MEMORY_OS_CONFIG_PATH"] = config_path
    else:
        # Default to current working directory if no root or config given
        config_path = str(Path.cwd() / "memory_os.config.json")
        
    config = MemoryOSConfig(config_path, space=args.space)
    return args.func(args, config)

if __name__ == "__main__":
    raise SystemExit(main())
