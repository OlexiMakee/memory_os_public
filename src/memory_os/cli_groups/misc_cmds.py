import argparse
import json
import sys
from datetime import timezone
from pathlib import Path

from memory_os import MemoryOSConfig

UTC = timezone.utc
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

def cmd_export_skills(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.skills_exporter import export_claude_skills
    root = Path(args.root).resolve()
    export_claude_skills(root)
    return 0

def cmd_skills(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.skill_registry import (
        discover_skills,
        sync_skills,
        validate_skills,
    )

    root = Path(args.root).resolve()
    skills_dir = getattr(args, "skills_dir", "skills")

    if args.skills_action == "list":
        skills = discover_skills(root, skills_dir=skills_dir)
        if args.format == "json":
            print(json.dumps([skill.to_dict() for skill in skills], indent=2))
        else:
            print(f"Skills: {len(skills)}")
            for skill in skills:
                print(f"- {skill.name}: {skill.description}")
        return 0

    if args.skills_action == "validate":
        report = validate_skills(root, skills_dir=skills_dir)
        if args.format == "json":
            print(json.dumps(report, indent=2))
        elif report["ok"]:
            print(f"OK: {len(report['skills'])} skills valid")
        else:
            print("Skill validation failed:")
            for error in report["errors"]:
                print(f"- {error}")
        return 0 if report["ok"] else 1

    if args.skills_action == "sync":
        agents = args.agent or list(KNOWN_AGENTS)
        report = sync_skills(
            root,
            agents=agents,
            skills_dir=skills_dir,
            dry_run=args.dry_run,
        )
        if args.format == "json":
            print(json.dumps(report, indent=2))
        elif report["ok"]:
            verb = "Would sync" if args.dry_run else "Synced"
            print(f"{verb}: {len(report['actions'])} skill installs")
            for action in report["actions"]:
                print(f"- {action['agent']}:{action['skill']} -> {action['destination']}")
        else:
            print("Skill sync failed:")
            for error in report["errors"]:
                print(f"- {error}")
        return 0 if report["ok"] else 1

    if args.skills_action == "lock":
        from memory_os.toolkit.skill_registry import write_skills_lock
        report = write_skills_lock(root, skills_dir=skills_dir)
        if args.format == "json":
            print(json.dumps(report, indent=2))
        elif report["ok"]:
            print(f"OK: Generated skills.lock.json with {len(report['skills'])} skills")
        else:
            print("Lock failed:")
            for error in report["errors"]:
                print(f"- {error}")
        return 0 if report["ok"] else 1

    if args.skills_action == "refresh":
        from memory_os.toolkit.skill_registry import refresh_skill, refresh_all_skills
        if not args.name and not args.all:
            print("Error: Specify a skill name or use --all", file=sys.stderr)
            return 1
            
        if args.all:
            report = refresh_all_skills(root, skills_dir=skills_dir)
            if args.format == "json":
                print(json.dumps(report, indent=2))
            elif report["ok"]:
                print(f"OK: Refreshed {len(report['refreshed'])} skills")
                for s_name, res in report["refreshed"].items():
                    print(f"- {s_name}: resolved to {res['resolved_ref'][:12]}")
            else:
                print("Refresh failed:")
                for error in report.get("errors", []):
                    print(f"- {error}")
            return 0 if report["ok"] else 1
        else:
            try:
                res = refresh_skill(root, args.name, skills_dir=skills_dir)
                if args.format == "json":
                    print(json.dumps(res, indent=2))
                else:
                    print(f"OK: Refreshed '{args.name}' to resolved ref {res['resolved_ref'][:12]}")
                return 0
            except Exception as e:
                if args.format == "json":
                    print(json.dumps({"ok": False, "errors": [str(e)]}, indent=2))
                else:
                    print(f"Error: {e}", file=sys.stderr)
                return 1

    raise SystemExit(f"Unknown skills action: {args.skills_action}")
