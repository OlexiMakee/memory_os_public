import argparse
import json
import sys
from datetime import timezone

from memory_os import MemoryOSConfig

UTC = timezone.utc
def cmd_lora_dataset_build(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.lora.dataset import (
        ActionRouterSource, CapsuleToolCallSource, DatasetBuilder,
        LocalDocumentSource, SqliteGraphSource, TelegramToolCallSource, UkrainianResponderSource,
    )
    from memory_os.core.safe_id import confine_to_root

    requested = set(args.source or ["capsules"])
    sources = []
    if "capsules" in requested:
        sources.append(CapsuleToolCallSource(config, system_prompt=args.system_prompt))
    if "sqlite" in requested:
        sources.append(SqliteGraphSource(config, system_prompt=args.system_prompt))
    if "docs" in requested:
        doc_root = confine_to_root(args.doc_root or ".", config.root_dir) if args.doc_root else config.root_dir
        patterns = args.doc_glob or ["**/*.md"]
        sources.append(LocalDocumentSource(doc_root, patterns, args.instruction, args.system_prompt))
    if "action_router" in requested:
        sources.append(ActionRouterSource())
    if "telegram" in requested:
        sources.append(TelegramToolCallSource(config))
    if "responder" in requested:
        sources.append(UkrainianResponderSource())

    out_path = confine_to_root(args.out, config.root_dir)
    count = DatasetBuilder(sources).build(out_path)
    result = {"adapter": args.adapter, "sources": sorted(requested), "examples_written": count, "out": str(out_path)}
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"Wrote {count} example(s) for adapter '{args.adapter}' to {out_path}")
    return 0

def cmd_lora_script_render(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.lora.registry import AdapterRegistry
    from memory_os.lora.training_config import LoraTrainingConfig
    from memory_os.lora.types import SkillAdapterSpec
    from memory_os.core.safe_id import confine_to_root

    script_path = confine_to_root(args.script_out, config.root_dir)
    cfg = LoraTrainingConfig(
        name=args.adapter,
        base_model=args.base_model,
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        method=args.method,
        rank=args.rank,
        alpha=args.alpha,
        epochs=args.epochs,
    )
    cfg.write_script(script_path)

    spec = SkillAdapterSpec(
        name=args.adapter,
        description=args.description,
        base_model=args.base_model,
        dataset_path=args.dataset,
        rank=args.rank,
        alpha=args.alpha,
        role=args.role,
        training_method=args.method,
        capabilities=args.capability or [],
        compatible_with=args.compatible_with or [],
        incompatible_with=args.incompatible_with or [],
    )
    version = AdapterRegistry(config).register(spec, script_path=str(script_path))

    result = {"adapter": args.adapter, "version": version, "role": args.role, "method": args.method, "script_path": str(script_path), "registered": True}
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"Rendered {args.method} training script for '{args.adapter}' {version} to {script_path}")
        print("Copy it (with the dataset) to a CUDA machine, install unsloth/trl/peft/bitsandbytes, then run it there.")
        print(f"Registered as a CANDIDATE — run 'memory_os lora registry promote --adapter {args.adapter} --version {version}' only after eval confirms it's better.")
    return 0

def cmd_lora_registry(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.lora.registry import AdapterRegistry

    registry = AdapterRegistry(config)
    action = args.lora_registry_action

    if action == "versions":
        versions = registry.list_versions(args.adapter)
        if args.format == "json":
            print(json.dumps(versions, indent=2))
        else:
            for v in versions:
                metrics = ", ".join(f"{k}={v_}" for k, v_ in (v.get("metrics") or {}).items())
                print(f"{v['version']}\t{v['status']}\t{v.get('base_model', '')}\t{v.get('description', '')}\t{metrics}")
        return 0

    if action == "compatible":
        compatible = registry.is_compatible(args.adapter_a, args.adapter_b)
        result = {"adapter_a": args.adapter_a, "adapter_b": args.adapter_b, "compatible": compatible}
        if args.format == "json":
            print(json.dumps(result, indent=2))
        else:
            print(f"{args.adapter_a} + {args.adapter_b}: {'compatible' if compatible else 'NOT compatible'}")
        return 0

    if action == "metrics":
        metrics = {}
        for pair in args.set or []:
            if "=" not in pair:
                print(f"Error: --set expects key=value, got {pair!r}", file=sys.stderr)
                return 1
            key, value = pair.split("=", 1)
            try:
                metrics[key] = float(value)
            except ValueError:
                metrics[key] = value
        try:
            registry.record_metrics(args.adapter, args.version, metrics)
        except KeyError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        result = {"adapter": args.adapter, "version": args.version, "metrics": metrics}
        if args.format == "json":
            print(json.dumps(result, indent=2))
        else:
            print(f"{args.adapter} {args.version} metrics recorded: {metrics}")
        return 0

    try:
        if action == "promote":
            registry.promote(args.adapter, args.version)
        else:  # reject
            registry.reject(args.adapter, args.version)
    except KeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    past_tense = {"promote": "promoted", "reject": "rejected"}[action]
    result = {"adapter": args.adapter, "version": args.version, "action": action}
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"{args.adapter} {args.version} -> {past_tense}")
    return 0

def cmd_lora_list(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.lora.registry import AdapterRegistry

    registry = AdapterRegistry(config)
    adapters = registry.find_by_capability(args.capability) if args.capability else registry.list()
    if args.format == "json":
        print(json.dumps(adapters, indent=2))
    else:
        if not adapters:
            print("No LoRA adapters registered yet. Run 'memory_os lora dataset build' and 'memory_os lora script render' first.")
        for a in adapters:
            caps = ",".join(a.get("capabilities") or [])
            print(f"{a['name']}\t{a['base_model']}\t{a['description']}\t[{caps}]")
    return 0
