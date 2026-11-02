import argparse
import json
import sys
from datetime import timezone
from pathlib import Path

from memory_os import MemoryOSConfig

UTC = timezone.utc
def cmd_models(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    if args.models_action == "recommend":
        from memory_os.toolkit.model_catalog import recommend_models

        result = recommend_models()
        if getattr(args, "format", "text") == "json":
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0

        hardware = result["hardware"]
        ram_gb = hardware["ram_gb"]
        vram_gb = hardware["vram_gb"]
        recommendations = result["recommendations"]

        print("System Hardware:")
        print(f"  CPU Cores : {hardware['cpu_cores']}")
        print(f"  System RAM: {ram_gb:.2f} GB")
        print(f"  GPU VRAM  : {vram_gb:.2f} GB" if vram_gb > 0 else "  GPU VRAM  : None detected")
        print()
        
        headers = ["Model", "Installed", "Params", "Quant", "Min RAM", "Min VRAM", "Status", "Sug. Ctx", "Reason"]
        rows = [
            {
                "name": recommendation["name"],
                "installed": "Yes" if recommendation["installed"] else "No",
                "params": recommendation["parameter_size"],
                "quant": recommendation["quantization"],
                "min_ram": f"{recommendation['min_ram_gb']:.1f} GB",
                "min_vram": (
                    f"{recommendation['min_vram_gb']:.1f} GB"
                    if recommendation["min_vram_gb"] > 0
                    else "N/A"
                ),
                "status": recommendation["status"],
                "reason": recommendation["reason"],
                "suggested_ctx": recommendation["suggested_context"],
            }
            for recommendation in recommendations
        ]
        col_widths = {h: len(h) for h in headers}
        for r in rows:
            col_widths["Model"] = max(col_widths["Model"], len(r["name"]))
            col_widths["Installed"] = max(col_widths["Installed"], len(r["installed"]))
            col_widths["Params"] = max(col_widths["Params"], len(r["params"]))
            col_widths["Quant"] = max(col_widths["Quant"], len(r["quant"]))
            col_widths["Min RAM"] = max(col_widths["Min RAM"], len(r["min_ram"]))
            col_widths["Min VRAM"] = max(col_widths["Min VRAM"], len(r["min_vram"]))
            col_widths["Status"] = max(col_widths["Status"], len(r["status"]))
            col_widths["Sug. Ctx"] = max(col_widths["Sug. Ctx"], len(r["suggested_ctx"]))
            col_widths["Reason"] = max(col_widths["Reason"], len(r["reason"]))
            
        header_row = " | ".join(h.ljust(col_widths[h]) for h in headers)
        separator_row = "-+-".join("-" * col_widths[h] for h in headers)
        print(header_row)
        print(separator_row)
        for r in rows:
            row_str = " | ".join([
                r["name"].ljust(col_widths["Model"]),
                r["installed"].ljust(col_widths["Installed"]),
                r["params"].ljust(col_widths["Params"]),
                r["quant"].ljust(col_widths["Quant"]),
                r["min_ram"].ljust(col_widths["Min RAM"]),
                r["min_vram"].ljust(col_widths["Min VRAM"]),
                r["status"].ljust(col_widths["Status"]),
                r["suggested_ctx"].ljust(col_widths["Sug. Ctx"]),
                r["reason"].ljust(col_widths["Reason"]),
            ])
            print(row_str)
            
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
            metric = result.get("metric")
            if metric and "precision_at_5" in result:
                metric_part = f", recall@5={result.get('recall_at_5', 0.0):.2f}, precision@5={result.get('precision_at_5', 0.0):.2f}"
            else:
                metric_part = f", {metric}={result.get('recall_at_5', result['pass_rate']):.2f}" if metric else ""
            print(f"{result['suite']} [{result['kind']}]: {result['status']} (pass_rate={result['pass_rate']:.2f}{metric_part}, threshold={result['pass_threshold']})")
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
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Wrote {path}")
        return 0

    # compare
    try:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
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
        vllm_provider, mcp_adapter, telegram_adapter, discord_adapter,
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
        "telegram": telegram_adapter.TelegramAdapter().audit(),
        "discord": discord_adapter.DiscordAdapter().audit(),
    }
    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        for name, status in report.items():
            print(f"{name}\tavailable={status['available']}")
    return 0

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
        print(f"Error: {exc}", file=sys.stderr)
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
            print(f"Error: {exc}", file=sys.stderr)
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
                print(f"Error: --input expects key=value, got {pair!r}", file=sys.stderr)
                return 1
            key, value = pair.split("=", 1)
            inputs[key] = value
        try:
            rendered = registry.render(args.id, inputs)
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
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

def cmd_compile_prompt(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.prompt_compiler import compile_context
    root = Path(args.root).resolve()
    print(compile_context(root))
    return 0
