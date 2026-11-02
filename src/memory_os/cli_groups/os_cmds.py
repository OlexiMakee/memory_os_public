import argparse
import json
import sys
from datetime import timezone
from pathlib import Path

from memory_os import MemoryOSConfig

UTC = timezone.utc
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

def cmd_linux(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.linux_inventory import (
        LinuxInventoryCollector,
        installed_sudo_guidance,
        query_inventory,
        render_inventory_text,
        sync_inventory_to_memory,
        write_snapshot,
    )

    action = getattr(args, "linux_action", None) or "inventory"

    if action == "inventory":
        inventory = LinuxInventoryCollector(root=config.root_dir).collect()
        snapshot_path = write_snapshot(config, inventory) if args.write else None
        if args.format == "json":
            print(json.dumps(inventory.to_dict(), indent=2, sort_keys=True))
        else:
            print(render_inventory_text(inventory))
            if snapshot_path:
                print(f"\nSnapshot written: {snapshot_path.relative_to(config.root_dir)}")
        return 0

    if action == "sync":
        inventory = LinuxInventoryCollector(root=config.root_dir).collect()
        snapshot_path = write_snapshot(config, inventory)
        result = sync_inventory_to_memory(config, inventory)
        if args.format == "json":
            print(json.dumps({**result, "snapshot": str(snapshot_path)}, indent=2, sort_keys=True))
        else:
            print(f"Linux inventory synced: {result['nodes_upserted']} nodes, {result['edges_upserted']} edges.")
            print(f"Snapshot written: {snapshot_path.relative_to(config.root_dir)}")
            if result["issues"]:
                print(f"Issues observed: {result['issues']}")
        return 0

    if action == "query":
        matches = query_inventory(config, args.query, limit=args.limit)
        if args.format == "json":
            print(json.dumps(matches, indent=2, sort_keys=True))
        else:
            if not matches:
                print(f"No linux inventory matches for '{args.query}'. Run `memory_os linux sync` first.")
                return 0
            for node in matches:
                print(f"[{node['id']}] {node['summary']}")
        return 0

    if action == "doctor":
        inventory = LinuxInventoryCollector(root=config.root_dir).collect()
        print(render_inventory_text(inventory))
        print("\nOperational guidance:")
        for item in installed_sudo_guidance():
            print(f"- {item}")
        print("\nPolicy: sudo or password-required actions are not run automatically. Ask the user first and explain the change in one sentence.")
        return 1 if inventory.issues else 0

    if action == "provision":
        from memory_os.toolkit.linux_provisioner import LinuxProvisioner
        provisioner = LinuxProvisioner(root=config.root_dir)
        ok = False
        if args.type == "ui":
            ok = provisioner.install_ui(args.target)
        elif args.type == "tool":
            ok = provisioner.install_tool(args.target)
        elif args.type == "app":
            ok = provisioner.install_app(args.target)
        return 0 if ok else 1

    print(f"Unknown linux action: {action}", file=sys.stderr)
    return 2

def cmd_xfce(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.xfce_manager import (
        XFCE_PROFILES,
        XFCEManager,
        diff_xfce_summaries,
        read_xfce_cache,
        render_profile_plan_text,
        render_summary_diff_text,
        render_snapshot_text,
        render_summary_text,
        sync_xfce_cache,
        write_xfce_cache,
    )

    manager = XFCEManager()
    action = getattr(args, "xfce_action", None) or "status"

    try:
        if action == "status":
            status = {
                "available": manager.available(),
                "channels": manager.channels() if manager.available() else [],
            }
            if getattr(args, "json", False):
                print(json.dumps(status, indent=2, ensure_ascii=False))
            else:
                print(f"xfconf-query: {'available' if status['available'] else 'missing'}")
                if status["channels"]:
                    print("channels:")
                    for channel in status["channels"]:
                        print(f"- {channel}")
            return 0 if status["available"] else 1

        if action == "channels":
            channels = manager.channels()
            if getattr(args, "json", False):
                print(json.dumps(channels, indent=2, ensure_ascii=False))
            else:
                for channel in channels:
                    print(channel)
            return 0

        if action == "list":
            props = manager.properties(args.channel)
            if getattr(args, "json", False):
                print(json.dumps(props, indent=2, ensure_ascii=False))
            else:
                for prop in props:
                    print(prop)
            return 0

        if action == "get":
            print(manager.get(args.channel, args.property))
            return 0

        if action == "set":
            manager.set(args.channel, args.property, args.value, args.type, create=args.create)
            sync_xfce_cache(Path(config.root_dir), manager)
            print(f"set {args.channel}:{args.property}")
            return 0

        if action == "reset":
            manager.reset(args.channel, args.property, recursive=args.recursive)
            sync_xfce_cache(Path(config.root_dir), manager)
            print(f"reset {args.channel}:{args.property}")
            return 0

        if action == "snapshot":
            channels = args.channel or None
            snapshot = manager.snapshot(channels=channels)
            if getattr(args, "json", False):
                print(json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(render_snapshot_text(snapshot))
            return 0

        if action == "summary":
            cached_only = getattr(args, "cached", False)
            try:
                summary = read_xfce_cache(Path(config.root_dir))["summary"] if cached_only else manager.state_summary()
            except RuntimeError as exc:
                if cached_only:
                    raise
                payload = read_xfce_cache(Path(config.root_dir))
                summary = payload["summary"]
                if getattr(args, "json", False):
                    print(json.dumps({"cached_only": True, "reason": str(exc), "summary": summary}, indent=2, ensure_ascii=False, sort_keys=True))
                else:
                    print(f"XFCE live summary unavailable: {exc}")
                    print("showing cached summary instead")
                    print(render_summary_text(summary))
                return 1
            if getattr(args, "json", False):
                print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(render_summary_text(summary))
            return 0

        if action == "cache":
            if getattr(args, "write", False):
                snapshot = manager.snapshot()
                summary = manager.state_summary(snapshot=snapshot)
                path = write_xfce_cache(Path(config.root_dir), snapshot, summary)
                if getattr(args, "json", False):
                    print(json.dumps({"path": str(path), "summary": summary}, indent=2, ensure_ascii=False, sort_keys=True))
                else:
                    print(f"XFCE cache written: {path.relative_to(config.root_dir)}")
                    print(render_summary_text(summary))
                return 0
            payload = read_xfce_cache(Path(config.root_dir))
            if getattr(args, "json", False):
                print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(f"generated_at: {payload.get('generated_at')}")
                print(render_summary_text(payload["summary"]))
            return 0

        if action == "profiles":
            profiles = sorted(XFCE_PROFILES)
            if getattr(args, "json", False):
                print(json.dumps(profiles, indent=2, ensure_ascii=False))
            else:
                for profile in profiles:
                    print(profile)
            return 0

        if action == "apply":
            plan = manager.apply_profile(args.profile, dry_run=args.dry_run)
            if not args.dry_run:
                sync_xfce_cache(Path(config.root_dir), manager)
            if getattr(args, "json", False):
                print(json.dumps(plan, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(render_profile_plan_text(args.profile, plan, dry_run=args.dry_run))
            return 0

        if action == "sync":
            path = sync_xfce_cache(Path(config.root_dir), manager)
            payload = read_xfce_cache(Path(config.root_dir))
            if getattr(args, "json", False):
                print(json.dumps({"path": str(path), **payload}, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(f"XFCE cache synced: {path.relative_to(config.root_dir)}")
                print(render_summary_text(payload["summary"]))
            return 0

        if action == "diff":
            payload = read_xfce_cache(Path(config.root_dir))
            try:
                live_summary = manager.state_summary()
            except RuntimeError as exc:
                if getattr(args, "json", False):
                    print(json.dumps({"error": str(exc), "cached": payload["summary"]}, indent=2, ensure_ascii=False, sort_keys=True))
                else:
                    print(f"XFCE live summary unavailable: {exc}")
                    print("cached summary remains available at agent_context/xfce/latest.json")
                return 1
            diff = diff_xfce_summaries(payload["summary"], live_summary)
            if getattr(args, "json", False):
                print(json.dumps(diff, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(render_summary_diff_text(diff))
            return 0 if not diff else 1
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Unknown xfce action: {action}", file=sys.stderr)
    return 2

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
