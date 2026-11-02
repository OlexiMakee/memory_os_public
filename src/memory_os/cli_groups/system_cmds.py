import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from memory_os import MemoryOSConfig, MemoryValidator, MemoryOS
from memory_os.toolkit.auditor import audit, to_markdown

UTC = timezone.utc

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
from .util_cmds import write_if_missing, append_if_absent

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
            "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "workflows": ["product", "memory_os"],
            "step_scale": "1..12",
        }, indent=2, sort_keys=True) + "\n",
        actions,
    )
    append_if_absent(
        root / ".gitignore",
        "# Memory OS runtime state",
        "\n# Memory OS runtime state\n"
        "data/\n"
        "memory/*\n"
        "!memory/nodes.jsonl\n"
        "!memory/edges.jsonl\n"
        "!memory/skills.lock.json\n"
        "agent_context/task_capsules.jsonl\n"
        "agent_context/memory_snapshot.json\n"
        "agent_context/task_events.jsonl\n",
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
    if getattr(args, "install_git_hooks", False):
        from memory_os.toolkit.git_hooks import install_git_hooks

        success, hook_actions = install_git_hooks(root)
        actions.extend(hook_actions)
        if not success:
            print("\n".join(actions))
            return 1
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
    from memory_os.toolkit.daemon_client import DaemonClient

    response = DaemonClient(config.root_dir, config.daemon_port, timeout=5).request(
        "/space",
        method="POST",
        body={"space": args.target_space},
    )
    if response.ok and response.payload.get("status") == "space_switched":
        print(f"[Switched] Daemon space updated to '{args.target_space}'.")
        return 0
    error = response.payload.get("error") or response.error
    if error:
        print(f"Failed to switch daemon space: {error}")
    elif response.status_code:
        print(f"Failed to switch daemon space (HTTP {response.status_code}).")
    else:
        print("Failed to switch daemon space: daemon unreachable.")
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

def cmd_daemon(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    import subprocess
    import signal
    import time
    from memory_os.toolkit.daemon_client import DaemonClient
    root = Path(args.root).resolve()
    data_dir = root / "data"
    pid_file = data_dir / "daemon.pid"
    
    daemon_client = DaemonClient(root, config.daemon_port)


    if args.daemon_action == "start":
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, 0)
                print(f"Daemon is already running (PID {pid}).")
                return 1
            except (ProcessLookupError, PermissionError, ValueError):
                print("Removing stale PID file and restarting...")
                pid_file.unlink(missing_ok=True)
            
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
        pid: Optional[int] = None
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
            except (OSError, ValueError):
                pid = None

        def wait_for_exit(target_pid: int, timeout: float) -> bool:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    os.kill(target_pid, 0)
                except ProcessLookupError:
                    return True
                time.sleep(0.1)
            return False

        response = daemon_client.request("/stop", method="POST")
        res = response.payload if response.ok else None
        if res and res.get("status") == "stopping":
            if pid is None or wait_for_exit(pid, 5.0):
                print("Daemon stopped gracefully via IPC.")
                return 0
            os.kill(pid, signal.SIGTERM)
            if wait_for_exit(pid, 5.0):
                print(f"Daemon required SIGTERM after IPC shutdown (PID {pid}).")
                return 0
            if sys.platform != "win32":
                os.kill(pid, signal.SIGKILL)
                if wait_for_exit(pid, 2.0):
                    pid_file.unlink(missing_ok=True)
                    print(f"Daemon required SIGKILL after blocked shutdown (PID {pid}).")
                    return 0
            print(f"Daemon did not stop (PID {pid}).", file=sys.stderr)
            return 1
            
        if not pid_file.exists():
            print("Daemon is not running.")
            return 1
        if pid is None:
            print("Daemon PID file is invalid.", file=sys.stderr)
            return 1
        try:
            os.kill(pid, signal.SIGTERM)
            if wait_for_exit(pid, 5.0):
                print(f"Daemon stopped after SIGTERM (PID {pid}).")
                return 0
            if sys.platform == "win32":
                pid_file.unlink(missing_ok=True)
                print(f"Daemon did not confirm exit after SIGTERM (PID {pid}).", file=sys.stderr)
                return 1
            os.kill(pid, signal.SIGKILL)
            if wait_for_exit(pid, 2.0):
                pid_file.unlink(missing_ok=True)
                print(f"Daemon required SIGKILL after blocked shutdown (PID {pid}).")
                return 0
            print(f"Daemon did not stop (PID {pid}).", file=sys.stderr)
            return 1
        except ProcessLookupError:
            print("Process not found, cleaning up stale PID file.")
            pid_file.unlink(missing_ok=True)
            return 0
        
    elif args.daemon_action == "status":
        response = daemon_client.request("/status")
        res = response.payload if response.ok else None
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
        response = daemon_client.request("/sync", method="POST")
        res = response.payload if response.ok else None
        if res and res.get("status") == "sync_triggered":
            print("Daemon sync triggered successfully via IPC.")
            return 0
        print("Could not contact daemon via IPC. Is the daemon running?")
        return 1
    return 0

def cmd_ls(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    """List running memory_os instances: tmux workspace + daemon."""
    from memory_os.toolkit.workspace import instances

    root = Path(args.root).resolve() if args.root else Path.cwd()
    info = instances(root)

    if getattr(args, "json", False):
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0

    ws = info.get("workspace")
    dm = info.get("daemon")
    any_running = bool(ws or (dm and dm.get("alive")))

    if ws:
        attached = "  [attached]" if ws.get("attached") else ""
        print(f"workspace  {ws['session']}  windows={ws['windows']}{attached}")
    else:
        print("workspace  (not running)")

    if dm:
        if dm.get("alive"):
            print(f"daemon     PID {dm['pid']}  running")
        else:
            print("daemon     (stale pid file — process gone)")
    else:
        print("daemon     (not running)")

    return 0 if any_running else 1

def cmd_install(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    """Run universal system bootstrap and environment diagnostic."""
    from memory_os.toolkit.bootstrap_installer import run_bootstrap
    force = getattr(args, "force", False)
    dry_run = getattr(args, "dry_run", False)
    json_output = getattr(args, "json", False)
    run_bootstrap(force=force, interactive=not json_output, dry_run=dry_run, json_output=json_output)
    return 0

def cmd_workspace(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    """Manage registered workspace profiles in ~/.memory_os/workspaces.toml."""
    from memory_os.toolkit.workspace_registry import (
        list_workspaces, register_workspace, unregister_workspace
    )
    action = getattr(args, "workspace_action", None)
    if action == "list" or action is None:
        ws_list = list_workspaces()
        if getattr(args, "json", False):
            print(json.dumps(ws_list, indent=2))
        else:
            print(f"\n📂 Registered Workspaces ({len(ws_list)}):\n")
            for w in ws_list:
                print(f"  • {w['name']} ({w['slug']}) → {w['path']}")
            print()
        return 0
    elif action == "register":
        target_path = Path(args.path).resolve() if getattr(args, "path", None) else Path.cwd()
        name = getattr(args, "name", None)
        slug = register_workspace(target_path, name=name)
        print(f"Registered workspace '{slug}' -> {target_path}")
        return 0
    elif action == "unregister":
        name = args.name
        if unregister_workspace(name):
            print(f"Unregistered workspace '{name}'.")
            return 0
        else:
            print(f"Workspace '{name}' not found in registry.", file=sys.stderr)
            return 1
    elif action == "telegram-token":
        from memory_os.toolkit.project_secrets import (
            ensure_project_telegram_token,
            project_has_telegram_token,
            upsert_project_env,
        )
        target_path = Path(args.path).resolve() if getattr(args, "path", None) else config.root_dir
        if getattr(args, "check", False):
            print("configured" if project_has_telegram_token(target_path) else "missing")
            return 0 if project_has_telegram_token(target_path) else 1
        if getattr(args, "stdin", False):
            token = sys.stdin.read().strip()
            if not token:
                print("No token read from stdin.", file=sys.stderr)
                return 1
            upsert_project_env(target_path, "TELEGRAM_BOT_TOKEN", token)
            print(f"Project TELEGRAM_BOT_TOKEN configured in {target_path / '.env'}")
            return 0
        return 0 if ensure_project_telegram_token(
            target_path,
            interactive=sys.stdin.isatty(),
        ) else 1
    elif action == "status":
        from memory_os.toolkit.workspace_runtime import WorkspaceSpec, select_workspace_runtime

        runtime_name = getattr(args, "runtime", None) or os.environ.get("MEMORY_OS_WORKSPACE_RUNTIME", "auto")
        runtime = select_workspace_runtime(runtime_name)
        cfg = MemoryOSConfig(str(Path(config.root_dir) / "memory_os.config.json"))
        spec = WorkspaceSpec(root=Path(config.root_dir), session_name=cfg.tmux_session_name, panes=[])
        status = runtime.status(spec)
        if getattr(args, "json", False):
            print(json.dumps(status, indent=2, ensure_ascii=False))
        else:
            print(f"runtime: {status.get('runtime', runtime.name)}")
            print(f"session: {status.get('session', cfg.tmux_session_name)}")
            print(f"available: {status.get('available', False)}")
            if "state" in status:
                print(f"state: {status['state']}")
            if "detail" in status:
                print(f"detail: {status['detail']}")
            if "state_file" in status:
                print(f"state_file: {status['state_file']}")
        return 0 if status.get("available") else 1
    elif action == "clean-exited":
        from memory_os.toolkit.workspace_runtime import ZellijWorkspaceRuntime

        runtime_name = getattr(args, "runtime", "zellij")
        if runtime_name != "zellij":
            print("clean-exited currently supports only --runtime zellij", file=sys.stderr)
            return 2
        runtime = ZellijWorkspaceRuntime()
        result = runtime.clean_exited_sessions(apply=getattr(args, "apply", False))
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            mode = "apply" if result["apply"] else "dry-run"
            print(f"runtime: {result['runtime']}")
            print(f"mode: {mode}")
            if result["exited_sessions"]:
                print("exited_sessions:")
                for session in result["exited_sessions"]:
                    marker = "deleted" if session in result["deleted"] else "pending"
                    print(f"- {session}: {marker}")
            else:
                print("exited_sessions: none")
            if not result["apply"]:
                print("hint: rerun with --apply to delete listed EXITED sessions")
        return 0
    elif action == "restart-pane":
        agent_id = args.name
        root = Path(config.root_dir).resolve()
        from memory_os.toolkit.runtime_control import RuntimeControl

        step = RuntimeControl(root, config=config).restart_pane(agent_id)
        stream = sys.stdout if step.ok else sys.stderr
        print(step.detail, file=stream)
        return 0 if step.ok else 1
    return 0

def cmd_zellij(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    """Launch the selected Memory OS workspace in Zellij."""
    from memory_os.toolkit.workspace import launch_workspace

    os.environ["MEMORY_OS_WORKSPACE_RUNTIME"] = "zellij"
    launch_workspace(Path(config.root_dir))
    return 0

def cmd_run_daemon_blocking(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.daemon import MemoryDaemon
    root = Path(args.root).resolve()
    transcript_path = Path(args.log_file).resolve()
    daemon = MemoryDaemon(config, transcript_path)
    daemon.run()
    return 0

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
            patch_archive = result["patch_archive"]
            print(f"  Patch archive  : {'OK' if patch_archive.get('ok') else 'FAILED'}")
            if patch_archive.get("archived_records"):
                print(f"  Archived patch rows : {patch_archive['archived_records']}")
            elif patch_archive.get("detail"):
                print(f"  Detail         : {patch_archive.get('detail')}")
            print(f"  Resource level : {result['snapshot']['level'].upper()}")
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
        print(f"  Events log         : {snap.events_jsonl_mb} MB / {snap.events_soft_limit_mb} MB soft limit" + ("  [!] archive rotation advised" if snap.events_soft_limit_exceeded else ""))
        if snap.events_soft_limit_exceeded:
            print("  Advisory           : events.jsonl is the audit source of truth; plan explicit archive rotation, do not prune it silently.")
        print(f"  Patch audit log    : {snap.patches_jsonl_mb} MB / {snap.patches_soft_limit_mb} MB soft limit" + ("  [!] archive compaction advised" if snap.patches_soft_limit_exceeded else ""))
        if snap.patches_soft_limit_exceeded:
            print("  Advisory           : patches.jsonl keeps the patch audit trail; use 'memory_os resources compact' to archive superseded patch states while keeping the latest state per patch hot.")
        growth = f"{snap.growth_mb_per_hour} MB/hr" if snap.growth_mb_per_hour is not None else "n/a (no prior snapshot)"
        print(f"  Growth rate        : {growth}" + ("  [!] exceeds max_observed_growth_mb_per_hour" if snap.growth_alert else ""))
        write_flag = "  [!] over cap" if not write_status.ok else ""
        print(f"  Agent artifacts    : {write_status.agent_context_mb} MB / {write_status.max_agent_context_mb} MB, {write_status.agent_context_files}/{write_status.max_agent_context_files} files{write_flag}")
        print(f"\nResource level: {snap.level.upper()}")

    return 1 if snap.level == "hot" or not write_status.ok else 0

def cmd_storage(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.storage_tier import StorageTierAdvisor

    assessment = StorageTierAdvisor(config).assess()
    if args.format == "json":
        print(json.dumps(assessment.to_dict(), indent=2))
    else:
        print(f"Recommended tier: {assessment.tier}")
        for reason in assessment.reasons:
            print(f"  - {reason}")
        print("\nSignals:")
        for key, value in assessment.signals.items():
            print(f"  {key}: {value}")
    return 0

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

def cmd_git_commit_safe(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.git_commit_safe import GitCommitSafeError, safe_commit

    try:
        output = safe_commit(config.root_dir, args.files, args.message)
    except GitCommitSafeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(output)
    return 0

def cmd_release_check(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.core.release_check import ReleaseChecker

    try:
        result = ReleaseChecker(config).run(target=args.target)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
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

def _print_workspace_runtime_doctor(config: MemoryOSConfig) -> None:
    from memory_os.toolkit.workspace_runtime import WorkspaceSpec, workspace_runtime_diagnostics
    from memory_os.toolkit.doctor import workspace_diagnostic_lines

    spec = WorkspaceSpec(root=config.root_dir, session_name=config.tmux_session_name, panes=[])
    for line in workspace_diagnostic_lines(workspace_runtime_diagnostics(spec)):
        print(line)

def cmd_doctor(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.doctor import DoctorService, render_doctor_text

    report = DoctorService(config).run()
    if getattr(args, "format", "text") == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_doctor_text(report))
    return 0 if report["ok"] else 1


def cmd_killall(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    """Stop and close all Memory OS processes, daemons, tmux and Zellij sessions/panes."""
    root = Path(config.root_dir).resolve()
    from memory_os.toolkit.workspace_runtime import ZellijWorkspaceRuntime, TmuxWorkspaceRuntime
    from memory_os.toolkit.runtime_control import RuntimeControl

    print("🛑 Shutting down all Memory OS processes, daemons, and multiplexer sessions...")

    # 1. Shutdown daemons and runtime control
    rc_result = RuntimeControl(root, config=config).shutdown_all(force=True)

    # 2. Stop Zellij sessions
    zellij = ZellijWorkspaceRuntime()
    if zellij.is_available():
        zellij.stop_all()
        zellij.clean_exited_sessions(apply=True)

    # 3. Stop Tmux sessions
    tmux = TmuxWorkspaceRuntime()
    if tmux.is_available():
        tmux.stop_all()

    print("🟢 All Memory OS processes, daemons, and Zellij/Tmux sessions have been closed.")
    return 0


def cmd_undo(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.modules.undo_service import UndoService

    task_id = getattr(args, "task_id", None)
    dry_run = getattr(args, "dry_run", False)
    use_json = getattr(args, "json", False)

    service = UndoService(config)
    result = service.undo(task_id=task_id, dry_run=dry_run)

    if use_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if result.get("ok"):
            prefix = "[DRY RUN] " if dry_run else ""
            t_id = result.get("task_id") or "latest"
            print(f"✨ {prefix}Undo completed for task: {t_id}")
            patches = result.get("patches_rolled_back") or []
            if patches:
                print(f"  • Patches rolled back ({len(patches)}): {', '.join(patches)}")
            if result.get("git_reverted"):
                print("  • Git changes reverted successfully.")
            elif result.get("reverted_files"):
                print(f"  • Reverted files ({len(result['reverted_files'])}): {', '.join(result['reverted_files'])}")
        else:
            print(f"❌ Undo failed: {result.get('error', 'Unknown error')}")

    return 0 if result.get("ok") else 1

