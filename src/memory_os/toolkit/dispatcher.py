"""Phase 4 — Agentic OS Dispatch Adapters.

Thin adapters that execute a RouterPlan against a real agent and write evidence.
Each adapter:
  1. Builds the context for its specific agent/tool
  2. Launches the command
  3. Bounds and captures stdout/stderr/exit_code
  4. Writes evidence to agent_context/evidence/<task_id>/
  5. Appends a task event
  6. Returns a DispatchResult

CLI:
    memory_os dispatch --task-id <id> [--dry-run]
    memory_os dispatch --task-id <id> --adapter shell --cmd "pytest tests/"
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_os.toolkit.agent_registry import load_agent_registry

MAX_OUTPUT_BYTES = 64 * 1024   # 64KB evidence cap
MAX_TIMEOUT_SEC = 300          # 5 minutes max per dispatch
SYSTEM_INSTRUCTION = (
    "Memory OS principles: no praise — criticize directly — surface alternatives first. "
    "Work 100% autonomously: NEVER ask the user for input, confirmation, or choices. ALWAYS execute commands and edit files directly. "
    "Telegraphic English for tasks; reply in user's language. "
    "Search memory_os before answering. Write decisions after completing. "
    "Run tests after every edit. "
    "Swarm AgentComm is the PRIMARY inter-agent channel; tmux is only one optional transport/runtime. "
    "Never describe delegatable work, delegate it: "
    "memory_os swarm-send --agent <id> --task-id <id> --prompt \"...\". "
    "Mandatory on done: "
    "memory_os comm send --kind STATUS_REPORT --sender <agent_id> --task-id <id> "
    "<task_initiator> \"<files changed | pytest N passed | risks>\". "
    "Report inaccuracies immediately via comm send — never silently continue."
)


@dataclass
class DispatchResult:
    task_id: Optional[str]
    agent: str
    adapter: str
    ok: bool
    exit_code: Optional[int]
    stdout: str
    stderr: str
    evidence_path: Optional[str]
    duration_sec: float
    dry_run: bool
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CliAgentAdapter:
    """Non-interactive subprocess adapter for CLI agents in KNOWN_AGENTS."""

    def __init__(self, root: Path):
        self.root = root

    def load_agent_config(self, agent_id: str) -> Dict[str, Any]:
        registry = load_agent_registry(self.root)
        cfg = registry.get("agent", {}).get(agent_id, {})
        return {
            "command": list(cfg.get("command") or [agent_id]),
            "dispatch_flags": list(cfg.get("dispatch_flags") or []),
        }

    def build_command(self, agent_id: str, prompt: str) -> List[str]:
        from memory_os.toolkit.startup_profile import apply_profile_to_flags, read_startup_profile

        cfg = self.load_agent_config(agent_id)
        base = list(cfg.get("command") or [agent_id])
        profile = read_startup_profile(self.root)
        flags = apply_profile_to_flags(list(cfg.get("dispatch_flags") or []), profile)

        if agent_id == "codex":
            cmd = base
            if cmd[:1] == ["codex"] and (len(cmd) == 1 or cmd[1] != "exec"):
                cmd = ["codex", "exec", *cmd[1:]]
            if "-C" not in cmd:
                cmd.extend(["-C", str(self.root)])
            cmd.extend(flags)
            cmd.append(prompt)
            return cmd

        return [*base, *flags, "-p", prompt]

    def binary_for(self, agent_id: str) -> str:
        cfg = self.load_agent_config(agent_id)
        command = list(cfg.get("command") or [agent_id])
        return command[0] if command else agent_id

    def run(
        self,
        agent_id: str,
        prompt: str,
        timeout: float,
        env: Optional[Dict[str, str]] = None,
    ) -> DispatchResult:
        import os as _os

        binary = self.binary_for(agent_id)
        if not shutil.which(binary):
            return DispatchResult(
                task_id=None,
                agent=agent_id,
                adapter="cli_agent",
                ok=False,
                exit_code=None,
                stdout="",
                stderr="",
                evidence_path=None,
                duration_sec=0.0,
                dry_run=False,
                error=f"CLI agent binary not found in PATH: {binary}",
            )

        cmd = self.build_command(agent_id, prompt)
        run_env = _os.environ.copy()
        if env:
            run_env.update(env)

        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.root),
                env=run_env,
            )
            duration = time.monotonic() - t0
            ok = proc.returncode == 0
            return DispatchResult(
                task_id=None,
                agent=agent_id,
                adapter="cli_agent",
                ok=ok,
                exit_code=proc.returncode,
                stdout=proc.stdout[:MAX_OUTPUT_BYTES],
                stderr=proc.stderr[:MAX_OUTPUT_BYTES],
                evidence_path=None,
                duration_sec=round(duration, 2),
                dry_run=False,
                error=None if ok else f"exit {proc.returncode}",
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - t0
            return DispatchResult(
                task_id=None,
                agent=agent_id,
                adapter="cli_agent",
                ok=False,
                exit_code=None,
                stdout="",
                stderr="",
                evidence_path=None,
                duration_sec=round(duration, 2),
                dry_run=False,
                error=f"timeout after {timeout}s",
            )
        except Exception as exc:
            duration = time.monotonic() - t0
            return DispatchResult(
                task_id=None,
                agent=agent_id,
                adapter="cli_agent",
                ok=False,
                exit_code=None,
                stdout="",
                stderr="",
                evidence_path=None,
                duration_sec=round(duration, 2),
                dry_run=False,
                error=str(exc),
            )


class DispatcherEngine:
    def __init__(self, root: Path):
        self.root = root

    def _build_context_pack(
        self,
        task_id: Optional[str],
        task_text: str = "",
    ) -> Dict[str, Any]:
        """Pre-dispatch hook: build context pack via ContextPackBuilder."""
        try:
            from memory_os.core.config import MemoryOSConfig
            from memory_os.core.context_pack import ContextPackBuilder
            from memory_os.toolkit.task_kernel import TaskKernel

            resolved_task = task_text
            contract_path = None
            if task_id:
                try:
                    task = TaskKernel(self.root).get(task_id)
                    if task:
                        resolved_task = f"{task.get('title', '')} {task.get('goal', '')}".strip()
                except Exception as _e:
                    import sys as _sys
                    print(f'Ignored exception: {_e}', file=_sys.stderr)
                possible_contract = self.root / "specs" / task_id / "contract.json"
                if possible_contract.exists():
                    contract_path = str(possible_contract)

            config_path = self.root / "memory_os.config.json"
            if not config_path.exists():
                config_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
            config = MemoryOSConfig(str(config_path))
            builder = ContextPackBuilder(config)
            return builder.build(
                task=resolved_task or "task dispatch",
                contract_path=contract_path,
            )
        except Exception:
            return {}

    def _evidence_dir(self, task_id: str) -> Path:
        d = self.root / "agent_context" / "evidence" / task_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _write_evidence(
        self,
        task_id: str,
        adapter: str,
        result: DispatchResult,
        context_pack: Optional[Dict[str, Any]] = None,
    ) -> Path:
        ev_dir = self._evidence_dir(task_id)
        ts = int(time.time())
        evidence_file = ev_dir / f"{ts}_{adapter}_dispatch.json"
        payload = {
            "task_id": task_id,
            "adapter": adapter,
            "agent": result.agent,
            "system_instruction": SYSTEM_INSTRUCTION,
            "context_pack_built": bool(context_pack),
            "ok": result.ok,
            "exit_code": result.exit_code,
            "stdout": result.stdout[:MAX_OUTPUT_BYTES],
            "stderr": result.stderr[:MAX_OUTPUT_BYTES],
            "duration_sec": result.duration_sec,
            "dry_run": result.dry_run,
            "error": result.error,
        }
        evidence_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return evidence_file

    def _update_task(self, task_id: str, result: DispatchResult) -> None:
        from memory_os.toolkit.task_kernel import TaskKernel
        kernel = TaskKernel(self.root)
        task = kernel.get(task_id)
        if task is None:
            return
        if result.ok and task.get("status") in ("claimed", "running"):
            kernel.done(task_id, summary=f"dispatch:{result.adapter} exit={result.exit_code}")
            self._write_task_memory(task, result)
        elif not result.ok and task.get("status") in ("claimed", "running"):
            kernel.block(task_id, reason=f"dispatch failed: {result.error or result.stderr[:120]}")

    def _write_handoff_memory(self, task_id: str, agent_id: str) -> None:
        """Write a handoff event as a fact MemoryNode so future searches can find it."""
        import hashlib
        import re as _re
        try:
            from memory_os.toolkit.task_kernel import TaskKernel
            from memory_os.core.config import MemoryOSConfig
            from memory_os.modules.lifecycle import LifecycleManager
            task = TaskKernel(self.root).get(task_id)
            if not task:
                return
            config = MemoryOSConfig(str(self.root / "memory_os.config.json"))
            lifecycle = LifecycleManager(config)

            title = task.get("title", "?")
            goal = task.get("goal", "")
            summary = f"Handoff to {agent_id}: {title}"
            if goal:
                summary += f" — {goal[:100]}"

            slug = _re.sub(r"[^A-Za-z0-9._-]+", "-", title.lower()).strip("-._")[:40] or "handoff"
            digest = hashlib.sha1(f"handoff:{task_id}:{agent_id}".encode()).hexdigest()[:8]
            node_id = f"handoff:{slug}-{digest}"

            evidence_parts: List[str] = []
            pack = self.root / "agent_context" / "context_packs" / f"handoff_{task_id}.md"
            if pack.exists():
                try:
                    evidence_parts.append(str(pack.relative_to(self.root)))
                except ValueError:
                    pass

            lifecycle.propose(
                node_id=node_id,
                node_type="fact",
                summary=summary,
                evidence=",".join(evidence_parts),
                tags=",".join([agent_id, task.get("risk", "low"), "handoff"]),
            )
            self._sync_shared_memory()
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)

    def _write_task_memory(self, task: Dict[str, Any], result: DispatchResult) -> None:
        """Write a completed task as a memory fact node for future retrieval."""
        import hashlib
        import re as _re
        try:
            from memory_os.core.config import MemoryOSConfig
            from memory_os.modules.lifecycle import LifecycleManager
            config = MemoryOSConfig(str(self.root / "memory_os.config.json"))
            lifecycle = LifecycleManager(config)

            title = task.get("title", "?")
            goal = task.get("goal", "")
            adapter = result.adapter or "unknown"
            duration = f"{result.duration_sec:.1f}s" if result.duration_sec else "?"

            summary = f"Task done: {title}"
            if goal:
                summary += f" — {goal[:100]}"
            summary += f" [adapter={adapter}, duration={duration}]"

            evidence_parts: List[str] = []
            if result.evidence_path:
                try:
                    ev = Path(result.evidence_path)
                    if ev.exists():
                        evidence_parts.append(str(ev.relative_to(self.root)))
                except (ValueError, OSError):
                    pass

            slug = _re.sub(r"[^A-Za-z0-9._-]+", "-", title.lower()).strip("-._")[:40] or "task"
            digest = hashlib.sha1(f"{task['id']}:{title}".encode()).hexdigest()[:8]
            node_id = f"task:{slug}-{digest}"

            lifecycle.propose(
                node_id=node_id,
                node_type="fact",
                summary=summary,
                evidence=",".join(evidence_parts),
                tags=",".join([adapter, task.get("risk", "low"), "task_result"]),
            )
            self._sync_shared_memory()
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)

    def _sync_shared_memory(self) -> None:
        """Keep JSONL memory and SQLite graph index aligned after agent writes."""
        try:
            from memory_os.core.config import MemoryOSConfig
            from memory_os.core.repository import MemoryRepository
            from memory_os.core.storage import FileSystemMemoryStorage

            config = MemoryOSConfig(str(self.root / "memory_os.config.json"))
            MemoryRepository(FileSystemMemoryStorage(), config).sync_graph_nodes()
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)

    # ------------------------------------------------------------------ #
    # Shell adapter                                                         #
    # ------------------------------------------------------------------ #

    def shell(
        self,
        task_id: Optional[str],
        cmd: List[str],
        dry_run: bool = False,
        timeout: float = MAX_TIMEOUT_SEC,
        env: Optional[Dict[str, str]] = None,
    ) -> DispatchResult:
        pack = self._build_context_pack(task_id, " ".join(cmd))
        import os
        if dry_run:
            return DispatchResult(
                task_id=task_id, agent="shell", adapter="shell",
                ok=True, exit_code=None, stdout=f"[dry-run] would run: {cmd}",
                stderr="", evidence_path=None, duration_sec=0.0, dry_run=True,
            )
        import os as _os
        run_env = _os.environ.copy()
        if env:
            run_env.update(env)
        run_env["MEMORY_OS_SYSTEM_INSTRUCTION"] = SYSTEM_INSTRUCTION
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, cwd=str(self.root), env=run_env,
            )
            duration = time.monotonic() - t0
            ok = proc.returncode == 0
            result = DispatchResult(
                task_id=task_id, agent="shell", adapter="shell",
                ok=ok, exit_code=proc.returncode,
                stdout=proc.stdout[:MAX_OUTPUT_BYTES],
                stderr=proc.stderr[:MAX_OUTPUT_BYTES],
                evidence_path=None, duration_sec=round(duration, 2), dry_run=False,
                error=None if ok else f"exit {proc.returncode}",
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - t0
            result = DispatchResult(
                task_id=task_id, agent="shell", adapter="shell",
                ok=False, exit_code=None, stdout="", stderr="",
                evidence_path=None, duration_sec=round(duration, 2), dry_run=False,
                error=f"timeout after {timeout}s",
            )
        except Exception as exc:
            duration = time.monotonic() - t0
            result = DispatchResult(
                task_id=task_id, agent="shell", adapter="shell",
                ok=False, exit_code=None, stdout="", stderr="",
                evidence_path=None, duration_sec=round(duration, 2), dry_run=False,
                error=str(exc),
            )
        if task_id:
            ev = self._write_evidence(task_id, "shell", result, context_pack=pack)
            result.evidence_path = str(ev)
            if not dry_run:
                self._update_task(task_id, result)
        return result

    # ------------------------------------------------------------------ #
    # Script adapter (python -m memory_os ...)                             #
    # ------------------------------------------------------------------ #

    def script(
        self,
        task_id: Optional[str],
        subcommand: List[str],
        dry_run: bool = False,
        timeout: float = 120.0,
    ) -> DispatchResult:
        pack = self._build_context_pack(task_id, " ".join(subcommand))
        import sys
        cmd = [sys.executable, "-m", "memory_os"] + subcommand
        if dry_run:
            return DispatchResult(
                task_id=task_id, agent="memory-os-cli", adapter="script",
                ok=True, exit_code=None, stdout=f"[dry-run] would run: {cmd}",
                stderr="", evidence_path=None, duration_sec=0.0, dry_run=True,
            )
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, cwd=str(self.root),
            )
            duration = time.monotonic() - t0
            ok = proc.returncode == 0
            result = DispatchResult(
                task_id=task_id, agent="memory-os-cli", adapter="script",
                ok=ok, exit_code=proc.returncode,
                stdout=proc.stdout[:MAX_OUTPUT_BYTES],
                stderr=proc.stderr[:MAX_OUTPUT_BYTES],
                evidence_path=None, duration_sec=round(duration, 2), dry_run=False,
                error=None if ok else f"exit {proc.returncode}",
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - t0
            result = DispatchResult(
                task_id=task_id, agent="memory-os-cli", adapter="script",
                ok=False, exit_code=None, stdout="", stderr="",
                evidence_path=None, duration_sec=round(duration, 2), dry_run=False,
                error=f"timeout after {timeout}s",
            )
        except Exception as exc:
            duration = time.monotonic() - t0
            result = DispatchResult(
                task_id=task_id, agent="memory-os-cli", adapter="script",
                ok=False, exit_code=None, stdout="", stderr="",
                evidence_path=None, duration_sec=round(duration, 2), dry_run=False,
                error=str(exc),
            )
        if task_id:
            ev = self._write_evidence(task_id, "script", result, context_pack=pack)
            result.evidence_path = str(ev)
            if not dry_run:
                self._update_task(task_id, result)
        return result

    # ------------------------------------------------------------------ #
    # Local model adapter (call llm_service directly)                      #
    # ------------------------------------------------------------------ #

    def local_model(
        self,
        task_id: Optional[str],
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        dry_run: bool = False,
        timeout: float = 60.0,
    ) -> DispatchResult:
        pack = self._build_context_pack(task_id, prompt)
        if SYSTEM_INSTRUCTION not in system_prompt:
            system_prompt = f"{SYSTEM_INSTRUCTION}\n{system_prompt}".strip()
        if dry_run:
            return DispatchResult(
                task_id=task_id, agent="local-router", adapter="local_model",
                ok=True, exit_code=None,
                stdout=f"[dry-run] would call local LLM: {prompt[:100]}",
                stderr="", evidence_path=None, duration_sec=0.0, dry_run=True,
            )
        from memory_os.core.llm_service import DefaultLlmProviderService
        t0 = time.monotonic()
        try:
            response = DefaultLlmProviderService().call_llm(
                user_message=prompt,
                system_prompt=system_prompt,
                provider=None,   # local-first: llama_server -> llama_cpp -> ollama
                max_tokens=200,
            )
            duration = time.monotonic() - t0
            result = DispatchResult(
                task_id=task_id, agent="local-router", adapter="local_model",
                ok=True, exit_code=0, stdout=response[:MAX_OUTPUT_BYTES], stderr="",
                evidence_path=None, duration_sec=round(duration, 2), dry_run=False,
            )
        except Exception as exc:
            duration = time.monotonic() - t0
            result = DispatchResult(
                task_id=task_id, agent="local-router", adapter="local_model",
                ok=False, exit_code=None, stdout="", stderr="",
                evidence_path=None, duration_sec=round(duration, 2), dry_run=False,
                error=str(exc),
            )
        if task_id:
            ev = self._write_evidence(task_id, "local_model", result, context_pack=pack)
            result.evidence_path = str(ev)
            if not dry_run:
                self._update_task(task_id, result)
        return result

    # ------------------------------------------------------------------ #
    # CLI Agent adapter — KNOWN_AGENTS                                    #
    # User must give explicit consent before dispatching to CLI agents.   #
    # ------------------------------------------------------------------ #

    def _build_cli_context(
        self,
        task_id: Optional[str],
        extra_context: str = "",
        pack: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build a structured context prompt for a CLI agent dispatch."""
        parts: List[str] = []
        parts.append("# System Instruction")
        parts.append(SYSTEM_INSTRUCTION)
        parts.append("")

        if task_id:
            from memory_os.toolkit.task_kernel import TaskKernel
            kernel = TaskKernel(self.root)
            task = kernel.get(task_id)
            if task:
                parts.append(f"# Memory OS Task Dispatch — {task_id}")
                parts.append("")
                parts.append(f"**Title:** {task.get('title', '?')}")
                if task.get("goal"):
                    parts.append(f"**Goal:** {task['goal']}")
                parts.append(f"**Status:** {task.get('status', '?')}  |  **Risk:** {task.get('risk', '?')}")
                if task.get("capabilities"):
                    parts.append(f"**Required capabilities:** {', '.join(task['capabilities'])}")
                if task.get("done_criteria"):
                    parts.append(f"**Done criteria:** {task['done_criteria']}")
                if task.get("blocked_reason"):
                    parts.append(f"**BLOCKED reason:** {task['blocked_reason']}")
                if task.get("handoff_summary"):
                    parts.append(f"**Prior handoff:** {task['handoff_summary']}")
                parts.append("")

        # Add recent memory nodes for context
        nodes_path = self.root / "memory" / "nodes.jsonl"
        if nodes_path.exists():
            nodes = []
            for line in nodes_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    n = json.loads(line)
                    if n.get("status") != "archived":
                        nodes.append(n)
                except json.JSONDecodeError:
                    continue
            nodes.sort(key=lambda n: n.get("created_at", ""), reverse=True)
            if nodes[:5]:
                parts.append("## Recent Memory (top 5 nodes)")
                for n in nodes[:5]:
                    parts.append(f"- [{n.get('type', '?')}] {(n.get('summary') or '')[:100]}")
                parts.append("")

        # Evidence files
        if task_id:
            ev_dir = self.root / "agent_context" / "evidence" / task_id
            if ev_dir.exists():
                files = sorted(f.name for f in ev_dir.iterdir() if f.is_file())
                if files:
                    parts.append("## Evidence from prior dispatches")
                    for f in files:
                        parts.append(f"- agent_context/evidence/{task_id}/{f}")
                    parts.append("")

        if extra_context:
            parts.append(extra_context)

        parts.append("## Your Task")
        parts.append("Complete the goal above. Report what you did in a clear summary when done.")

        return "\n".join(parts)

    def cli_agent(
        self,
        task_id: Optional[str],
        agent_id: str,
        extra_context: str = "",
        dry_run: bool = False,
        timeout: float = MAX_TIMEOUT_SEC,
    ) -> DispatchResult:
        """Dispatch to a CLI agent (one of KNOWN_AGENTS) with full repo context.

        Requires explicit user consent before calling this method.
        agent_id must match an entry in agent_context/agents/registry.toml.
        """
        pack = self._build_context_pack(task_id, extra_context)
        prompt = self._build_cli_context(task_id, extra_context, pack=pack)
        adapter = CliAgentAdapter(self.root)
        cmd = adapter.build_command(agent_id, prompt)

        if dry_run:
            preview = f"[dry-run] would run: {cmd[0]} ... (prompt length={len(prompt)})"
            return DispatchResult(
                task_id=task_id, agent=agent_id, adapter="cli_agent",
                ok=True, exit_code=None, stdout=preview,
                stderr="", evidence_path=None, duration_sec=0.0, dry_run=True,
            )

        if task_id:
            self._write_handoff_memory(task_id, agent_id)

        result = adapter.run(agent_id=agent_id, prompt=prompt, timeout=timeout)
        result.task_id = task_id

        if task_id:
            ev = self._write_evidence(task_id, f"cli_agent_{agent_id}", result, context_pack=pack)
            result.evidence_path = str(ev)
            self._update_task(task_id, result)

        return result


    # ------------------------------------------------------------------ #
    # Dispatch from a RouterPlan                                           #
    # ------------------------------------------------------------------ #

    def dispatch_plan(
        self,
        plan,   # ExecutionPlan from router_plan
        dry_run: bool = False,
        extra_cmd: Optional[List[str]] = None,
    ) -> DispatchResult:
        """Execute a RouterPlan using the appropriate adapter."""
        task_id = plan.task_id
        kind = plan.agent_kind
        text = plan.text

        blocked_reason = getattr(plan, "blocked_reason", None)
        if blocked_reason:
            return DispatchResult(
                task_id=task_id,
                agent=plan.agent,
                adapter="blocked",
                ok=False,
                exit_code=None,
                stdout="",
                stderr="",
                evidence_path=None,
                duration_sec=0.0,
                dry_run=dry_run,
                error=blocked_reason,
            )

        if kind in ("script",):
            subcmd = extra_cmd or ["validate"]
            return self.script(task_id, subcmd, dry_run=dry_run)

        if kind == "shell":
            cmd = extra_cmd or ["bash", "-c", "echo 'shell dispatch placeholder'"]
            return self.shell(task_id, cmd, dry_run=dry_run)

        if kind == "local_model":
            return self.local_model(task_id, text, dry_run=dry_run)

        if kind == "cli_agent":
            return self.cli_agent(
                task_id=task_id,
                agent_id=plan.agent,
                extra_context=text,
                dry_run=dry_run,
            )

        return DispatchResult(
            task_id=task_id, agent=plan.agent, adapter="unknown",
            ok=False, exit_code=None, stdout="", stderr="",
            evidence_path=None, duration_sec=0.0, dry_run=dry_run,
            error=f"unknown agent_kind: {kind}",
        )
