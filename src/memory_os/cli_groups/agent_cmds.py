import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_os import MemoryOSConfig

UTC = timezone.utc
def cmd_task(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.task_kernel import TaskKernel

    root = Path(args.root).resolve() if args.root else Path.cwd()
    kernel = TaskKernel(root)
    action = args.task_action

    if action == "create":
        caps = [c.strip() for c in args.capabilities.split(",")] if getattr(args, "capabilities", None) else []
        task = kernel.create(
            title=args.title,
            goal=getattr(args, "goal", "") or "",
            risk=getattr(args, "risk", "low") or "low",
            capabilities=caps,
            done_criteria=getattr(args, "done_criteria", None),
        )
        if getattr(args, "json", False):
            print(json.dumps(task, indent=2, ensure_ascii=False))
        else:
            print(f"Created {task['id']}  [{task['status']}]  {task['title']}")
        return 0

    if action == "list":
        tasks = kernel.list_tasks(
            status=getattr(args, "status", None),
            agent=getattr(args, "agent", None),
            risk=getattr(args, "risk", None),
        )
        if getattr(args, "json", False):
            print(json.dumps(tasks, indent=2, ensure_ascii=False))
            return 0
        if not tasks:
            print("No tasks found.")
            return 0
        for t in tasks:
            agent_label = f"  agent={t['agent']}" if t.get("agent") else ""
            blocked = f"  BLOCKED: {t['blocked_reason']}" if t.get("blocked_reason") else ""
            print(f"{t['id']}  [{t['status']:8}]  [{t['risk']}]  {t['title'][:60]}{agent_label}{blocked}")
        return 0

    if action == "status":
        task = kernel.get(args.task_id)
        if task is None:
            print(f"Task not found: {args.task_id}", file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            print(json.dumps(task, indent=2, ensure_ascii=False))
            return 0
        for k, v in task.items():
            if v is not None and v != [] and v != 0:
                print(f"{k:18}: {v}")
        events = kernel.events(task_id=args.task_id)
        if events:
            print("\nEvents:")
            for e in events:
                parts = [e["ts"], e["event"]]
                if e.get("agent"):
                    parts.append(f"agent={e['agent']}")
                if e.get("reason"):
                    parts.append(f"reason={e['reason']}")
                print("  " + "  ".join(parts))
        return 0

    if action == "claim":
        task = kernel.claim(args.task_id, args.agent, lease_minutes=getattr(args, "lease_minutes", 30))
        print(f"Claimed {task['id']} by {task['agent']}  (lease until {task['lease_expires']})")
        return 0

    if action == "start":
        task = kernel.start(args.task_id)
        print(f"{task['id']} → running")
        return 0

    if action == "block":
        task = kernel.block(args.task_id, args.reason)
        print(f"{task['id']} → blocked  ({args.reason})")
        return 0

    if action == "review":
        task = kernel.review(args.task_id, summary=getattr(args, "summary", None))
        print(f"{task['id']} → review")
        return 0

    if action == "done":
        task = kernel.done(args.task_id, summary=getattr(args, "summary", None))
        print(f"{task['id']} → done")
        return 0

    if action == "unclaim":
        task = kernel.unclaim(args.task_id)
        print(f"{task['id']} → pending  (unclaimed)")
        return 0

    if action == "leases":
        leases = kernel.stale_leases()
        all_leases = kernel.list_leases()
        if getattr(args, "json", False):
            print(json.dumps({"all": all_leases, "stale": leases}, indent=2, ensure_ascii=False))
            return 0
        if not all_leases:
            print("No active leases.")
            return 0
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        for tid, lease in all_leases.items():
            stale_marker = "  [STALE]" if lease.get("expires", "9999") < now else ""
            print(f"{tid}  owner={lease['owner']}  expires={lease['expires']}{stale_marker}")
        return 0

    if action == "events":
        limit = getattr(args, "limit", None)
        task_id_filter = getattr(args, "task_id", None)
        events = kernel.events(task_id=task_id_filter, limit=limit)
        if getattr(args, "json", False):
            print(json.dumps(events, indent=2, ensure_ascii=False))
            return 0
        for e in events:
            parts = [e["ts"], e.get("task_id", "?"), e["event"]]
            if e.get("agent"):
                parts.append(f"agent={e['agent']}")
            if e.get("reason"):
                parts.append(f"reason={e['reason']}")
            print("  ".join(parts))
        return 0

    print(f"Unknown task action: {action}", file=sys.stderr)
    return 1

def cmd_plan(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    """Phase 3 — produce an execution plan for a task or free text."""
    from memory_os.toolkit.router_plan import RouterPlan

    root = Path(args.root).resolve() if args.root else Path.cwd()
    router = RouterPlan(root)

    task_id = getattr(args, "task_id", None)
    text = getattr(args, "text", "") or ""
    risk = getattr(args, "risk", "low") or "low"
    caps_raw = getattr(args, "capabilities", "") or ""
    caps = [c.strip() for c in caps_raw.split(",") if c.strip()]

    try:
        plan = router.route(task_id=task_id, text=text, risk=risk, capabilities=caps)
    except KeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False))
        return 0

    print(f"agent       : {plan.agent}  (kind={plan.agent_kind})")
    print(f"mode        : {plan.mode}")
    print(f"cost        : {plan.estimated_cost}")
    print(f"fallback    : {plan.fallback or '—'}")
    print(f"review req  : {plan.requires_review}")
    print(f"budget_deg  : {plan.budget_degraded}")
    if plan.blocked_reason:
        print(f"blocked     : {plan.blocked_reason}")
    print(f"rationale   : {plan.rationale}")
    return 0

def cmd_dispatch(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    """Phase 4 — dispatch a task to an agent adapter."""
    from memory_os.toolkit.dispatcher import DispatcherEngine
    from memory_os.toolkit.router_plan import RouterPlan
    from memory_os.toolkit.task_kernel import TaskKernel
    from memory_os.toolkit.daemon_hygiene import DaemonHygiene

    root = Path(args.root).resolve() if args.root else Path.cwd()
    dispatcher = DispatcherEngine(root)
    dry_run = getattr(args, "dry_run", False)
    task_id = getattr(args, "task_id", None)
    adapter = getattr(args, "adapter", "auto") or "auto"
    cmd_override = getattr(args, "cmd", None)

    if task_id:
        task = TaskKernel(root).get(task_id)
        if task:
            # Check resource guard for heavy jobs
            effort = task.get("effort", "low")
            if "high" in effort.lower() or "medium" in effort.lower():
                hygiene = DaemonHygiene(root)
                if not hygiene.resource_guard_preflight(effort):
                    print("Error: System under heavy load. Resource guard prevented heavy task dispatch.", file=sys.stderr)
                    return 1

    if adapter == "shell" and cmd_override:
        result = dispatcher.shell(task_id, cmd_override.split(), dry_run=dry_run)
    elif adapter == "script" and cmd_override:
        result = dispatcher.script(task_id, cmd_override.split(), dry_run=dry_run)
    elif adapter == "local_model":
        text = getattr(args, "text", "") or ""
        result = dispatcher.local_model(task_id, text, dry_run=dry_run)
    elif adapter in KNOWN_AGENTS:
        extra = getattr(args, "text", "") or ""
        timeout = getattr(args, "timeout", 300.0) or 300.0
        result = dispatcher.cli_agent(
            task_id=task_id,
            agent_id=adapter,
            extra_context=extra,
            dry_run=dry_run,
            timeout=timeout,
        )
    else:
        # Auto-route: produce a plan then dispatch
        if not task_id:
            print("Error: --task-id required for auto dispatch", file=sys.stderr)
            return 1
        try:
            plan = RouterPlan(root).route(task_id=task_id)
        except KeyError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        result = dispatcher.dispatch_plan(plan, dry_run=dry_run)

    if getattr(args, "json", False):
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0 if result.ok else 1

    status = "OK" if result.ok else "FAILED"
    print(f"[{status}]  adapter={result.adapter}  agent={result.agent}  exit={result.exit_code}  {result.duration_sec}s")
    if result.stdout:
        print("\n--- stdout ---")
        print(result.stdout[:2000])
    if result.stderr:
        print("\n--- stderr ---")
        print(result.stderr[:500])
    if result.evidence_path:
        print(f"\nevidence → {result.evidence_path}")
    if result.error:
        print(f"\nerror: {result.error}", file=sys.stderr)
    return 0 if result.ok else 1

def _cmd_feed_watch(comm: Any, root: Path) -> int:
    """Tail agent_context/task_events.jsonl in real-time (Ctrl-C to stop)."""
    import select
    events_path = root / "agent_context" / "task_events.jsonl"
    if not events_path.exists():
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.touch()
    print(f"Watching {events_path} — Ctrl-C to stop", flush=True)
    try:
        with events_path.open("r", encoding="utf-8") as fh:
            fh.seek(0, 2)  # seek to end — only new lines
            while True:
                line = fh.readline()
                if line:
                    line = line.strip()
                    if line:
                        try:
                            record = json.loads(line)
                            ts = record.get("ts", "")
                            event = record.get("event", "?")
                            kind = record.get("kind", "")
                            sender = record.get("sender", "")
                            task_id = record.get("task_id", "")
                            msg = record.get("message", "")
                            parts = [ts, event]
                            if kind:
                                parts.append(f"kind={kind}")
                            if sender:
                                parts.append(f"from={sender}")
                            if task_id:
                                parts.append(f"task={task_id}")
                            if msg:
                                parts.append(f'"{msg[:80]}"')
                            print("  ".join(parts), flush=True)
                        except json.JSONDecodeError:
                            print(line, flush=True)
                else:
                    import time as _time
                    _time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    return 0

def cmd_comm(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.agent_comm import AgentComm, format_inbox_text, format_resume_report, format_status_text

    root = Path(args.root).resolve() if args.root else Path.cwd()
    comm = AgentComm(root, config=config)
    action = args.comm_action

    if action == "send":
        result = comm.send(
            recipient=args.recipient,
            message=args.message,
            kind=args.kind,
            sender=getattr(args, "sender", None) or os.environ.get("MEMORY_OS_AGENT_ID", "claude"),
            task_id=getattr(args, "task_id", ""),
            tmux_target=getattr(args, "tmux_target", None),
            unlock_buffers=not getattr(args, "no_unlock", False),
        )
        if getattr(args, "json", False):
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            print("sent" if result.ok else "failed")
            print(f"kind: {result.kind}")
            print(f"sender: {result.sender}")
            print(f"recipient: {result.recipient}")
            print(f"tmux_target: {result.tmux_target}")
            print(f"task_id: {result.task_id}")
            if result.error:
                print(f"error: {result.error}", file=sys.stderr)
        return 0 if result.ok else 1

    if action == "inbox":
        recipient = getattr(args, "recipient", None) or os.environ.get("MEMORY_OS_AGENT_ID", "claude")
        if getattr(args, "rewind", False):
            comm.reset_inbox_cursor(recipient)
        inbox = comm.inbox(
            recipient=recipient,
            limit=getattr(args, "limit", 20),
            task_id=getattr(args, "task_id", None),
            unread_only=not getattr(args, "all", False),
            peek=getattr(args, "peek", False),
        )
        if getattr(args, "json", False):
            print(json.dumps(inbox, indent=2, ensure_ascii=False))
        else:
            print(format_inbox_text(inbox))
        return 0

    if action == "read":
        recipient = getattr(args, "recipient", None) or os.environ.get("MEMORY_OS_AGENT_ID", "claude")
        msg = comm.read_message(recipient, args.msg_id)
        if msg is None:
            print(f"no message #{args.msg_id} in {recipient} inbox", file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            print(json.dumps(msg, indent=2, ensure_ascii=False))
        else:
            print(f"[#{args.msg_id}] {msg.get('ts')} [{msg.get('kind')}] {msg.get('sender')} -> {msg.get('recipient')} task={msg.get('task_id')}")
            print()
            print(msg.get("message", ""))
        return 0

    if action == "rotate":
        archived = []
        a = comm.rotate_events()
        if a:
            archived.append(str(a))
        for inbox_file in sorted((root / "agent_context" / "inbox").glob("*.jsonl")):
            a = comm.rotate_inbox(inbox_file.stem)
            if a:
                archived.append(str(a))
        print("\n".join(archived) if archived else "nothing to rotate")
        return 0

    if action == "status":
        status = comm.status()
        if getattr(args, "json", False):
            print(json.dumps(status, indent=2, ensure_ascii=False))
        else:
            print(format_status_text(status))
        return 0

    if action == "resume":
        report = comm.resume_report(limit=getattr(args, "limit", 5))
        if getattr(args, "json", False):
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(format_resume_report(report))
        return 0

    if action == "feed":
        from memory_os.toolkit.agent_comm import format_feed_text
        if getattr(args, "watch", False):
            return _cmd_feed_watch(comm, root)
        events = comm.feed(limit=getattr(args, "limit", 30), new_only=getattr(args, "new", False))
        if getattr(args, "json", False):
            print(json.dumps(events, indent=2, ensure_ascii=False))
        else:
            print(format_feed_text(events))
        return 0


    print(f"Unknown comm action: {action}", file=sys.stderr)
    return 1

def cmd_handoff(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    """Build a handoff context pack markdown for agent-to-agent transitions."""
    from memory_os.toolkit.handoff_builder import HandoffBuilder

    root = Path(args.root).resolve() if args.root else Path.cwd()
    builder = HandoffBuilder(root)
    output = Path(args.output) if getattr(args, "output", None) else None

    try:
        path = builder.build(args.task_id, output_path=output)
    except KeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Handoff written → {path}")
    if getattr(args, "print_output", False):
        print()
        print(path.read_text(encoding="utf-8"))
    return 0

def cmd_agent_registry(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    """Agent Registry: list and audit registered agents (Phase 2 of Agentic OS)."""
    from memory_os.toolkit.agent_registry import AgentRegistryLoadError, load_agent_registry

    root = Path(args.root).resolve() if args.root else Path.cwd()
    registry_path = root / "agent_context" / "agents" / "registry.toml"
    action = args.registry_action

    if action == "list":
        if not registry_path.exists():
            print("No agent registry found. Create agent_context/agents/registry.toml to get started.")
            print("\nExample entry:")
            print('[agent.local-router]')
            print('kind = "local_model"')
            print('capabilities = ["classify", "tool_intent", "summarize_output"]')
            print('cost_class = "cheap"')
            print('risk_max = "low"')
            return 0
        try:
            agents = load_agent_registry(root, strict=True).get("agent", {})
        except AgentRegistryLoadError as exc:
            print(f"[ERROR] {exc}")
            return 1
        if not agents:
            print("Registry is empty.")
            return 0
        for agent_id, cfg in agents.items():
            kind = cfg.get("kind", "?")
            caps = ", ".join(cfg.get("capabilities", []))
            cost = cfg.get("cost_class", "?")
            risk = cfg.get("risk_max", "?")
            print(f"{agent_id:20}  kind={kind:14}  cost={cost:8}  risk_max={risk:6}  caps=[{caps}]")
        return 0

    if action == "audit":
        if not registry_path.exists():
            print("[MISSING] agent_context/agents/registry.toml not found")
            return 1
        try:
            agents = load_agent_registry(root, strict=True).get("agent", {})
        except AgentRegistryLoadError as exc:
            print(f"[ERROR] {exc}")
            return 1
        issues = 0
        prompt_warnings = 0
        from memory_os.toolkit.agent_health import AgentHealthProbe
        probe = AgentHealthProbe(root)

        for agent_id, cfg in agents.items():
            cmd = cfg.get("command", [])
            binary = cmd[0] if cmd else None
            status_str = "[OK]"
            if binary and shutil.which(binary) is None:
                if cfg.get("kind") == "local_model" and binary == "ollama":
                    from memory_os.core.llm_service import ollama_http_health
                    health = ollama_http_health(timeout=1.0)
                    if health.get("ok"):
                        status_str = f"[OK] {agent_id}: ollama HTTP {health['host']} model={health['model']} (CLI not in PATH)"
                    else:
                        status_str = f"[MISSING CLI] {agent_id}: '{binary}' not found in PATH"
                        issues += 1
                else:
                    status_str = f"[MISSING CLI] {agent_id}: '{binary}' not found in PATH"
                    issues += 1
            else:
                status_str = f"[OK] {agent_id}: {binary or '(no command)'}"

            prompt_res = probe.verify_system_prompt(agent_id, cfg)
            if prompt_res.get("ok"):
                prompt_str = f"[OK PROMPT] {prompt_res.get('detail')}"
            else:
                prompt_str = f"[WARNING PROMPT] {prompt_res.get('detail')}"
                prompt_warnings += 1

            print(f"{status_str} | {prompt_str}")

        if issues:
            print(f"\n{issues} issue(s) found.")
            return 1
        if prompt_warnings:
            print(f"\nAll CLI binaries OK ({prompt_warnings} prompt warning(s)).")
        else:
            print("\nAll agents OK.")
        return 0


    if action == "health":
        from memory_os.toolkit.agent_health import AgentHealthProbe
        probe = AgentHealthProbe(root)
        results = probe.check_all(force=getattr(args, "force", False))
        if getattr(args, "json", False):
            print(json.dumps(results, indent=2, ensure_ascii=False))
            return 0
        print("=== Agent Health & Quota Probe ===")
        for agent_id, res in sorted(results.items()):
            st = res.get("status", "?")
            dt = res.get("detail", "")
            icon = "[✓]" if st == "ok" else "[✗]"
            pr = res.get("prompt", {})
            pr_str = f"prompt={'ok' if pr.get('ok') else 'warn'}({pr.get('detail')})"
            print(f"  {icon} {agent_id:18} status={st:14} detail={dt:35} {pr_str}")
        return 0


    print(f"Unknown registry action: {action}", file=sys.stderr)
    return 1

def cmd_agent_manager(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    """Run interactive agent manager TUI."""
    root = Path(args.root).resolve() if args.root else Path.cwd()
    from memory_os.toolkit.agent_manager import AgentManagerTUI
    tui = AgentManagerTUI(root)
    if getattr(args, "restart_all", False):
        result = tui.restart_all(
            force=getattr(args, "force", False),
            detach_workspace=not getattr(args, "no_detach", False),
            workspace_only=getattr(args, "workspace_only", False),
        )
        if getattr(args, "json", False):
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(tui.format_control_result(result))
        return 0 if result.get("ok") else 1
    if getattr(args, "shutdown_all", False):
        result = tui.shutdown_all(
            force=getattr(args, "force", False),
            workspace_only=getattr(args, "workspace_only", False),
        )
        if getattr(args, "json", False):
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(tui.format_control_result(result))
        return 0 if result.get("ok") else 1
    if getattr(args, "probe_usage", False):
        from memory_os.toolkit.usage_probe import USAGE_COMMANDS, probe_pane_usage
        for agent_id in USAGE_COMMANDS:
            usage = probe_pane_usage(root, agent_id)
            print(f"{agent_id}: {usage or 'skipped (busy pane or nothing parsed)'}")
        tui.print_status()
        return 0
    if getattr(args, "json", False):
        print(json.dumps(tui.get_agents_status(), ensure_ascii=False, indent=2))
        return 0
    if getattr(args, "status", False):
        tui.print_status()
        return 0
    if getattr(args, "plain", False):
        tui.run_plain(interactive=True)
        return 0
    tui.run_curses()
    return 0

def cmd_agent_run(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.agent_brain.brain import LocalLLMActionBrain
    from memory_os.agent_brain.executors import default_executors
    from memory_os.agent_brain.orchestrator import Orchestrator

    brain = LocalLLMActionBrain(provider=args.provider, model=args.model)
    orchestrator = Orchestrator(brain=brain, executors=default_executors(config))
    try:
        result = orchestrator.run(args.task)
    except (RuntimeError, ValueError, KeyError) as exc:
        # No provider configured, or the model didn't return parseable
        # ActionRequest JSON — expected without a trained action-LoRA yet.
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print(f"Action : {result.action}")
        print(f"OK     : {result.ok}")
        print(f"Data   : {result.data}" if result.ok else f"Error  : {result.error}")
    return 0 if result.ok else 1

def cmd_swarm_send(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    """Send a task to an agent pane with the swarm completion protocol."""
    from memory_os.toolkit.workspace import send_task

    ok = send_task(
        agent_id=args.agent,
        task_id=args.task_id,
        prompt=args.prompt,
        sender=getattr(args, "sender", None) or os.environ.get("MEMORY_OS_AGENT_ID", "claude"),
        effort=getattr(args, "effort", "") or "",
    )
    if ok:
        print(f"Task {args.task_id} sent to {args.agent}")
    else:
        print(f"Agent '{args.agent}' not found in workspace pane map", file=sys.stderr)
        return 1
    return 0

def cmd_swarm_watch(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    """Block until an agent reports done via STATUS_REPORT, then print result."""
    from memory_os.toolkit.workspace import watch_task

    root = Path(args.root).resolve() if args.root else Path.cwd()
    timeout = getattr(args, "timeout", 300)
    task_id = args.task_id

    print(f"Watching for task={task_id} (timeout={timeout}s) …", flush=True)
    result = watch_task(task_id=task_id, root=root, timeout=timeout)

    if result.get("timed_out"):
        print(f"Timeout: no STATUS_REPORT received for task={task_id} within {timeout}s", file=sys.stderr)
        return 1

    sender = result.get("sender", "?")
    message = result.get("message", "")
    ts = result.get("ts", "")
    print(f"\n[SWARM DONE] task={task_id}")
    print(f"  from:    {sender}")
    print(f"  at:      {ts}")
    print(f"  message: {message}")
    return 0
