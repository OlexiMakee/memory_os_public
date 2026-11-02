"""Workspace launch facade for multiplexer-backed Memory OS sessions."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from memory_os.toolkit.agent_registry import load_agent_registry
from memory_os.toolkit.workspace_prompts import PromptPrincipleSync
from memory_os.toolkit.workspace_status import instances
from memory_os.toolkit.workspace_tasks import (
    relay_result_to_claude as _relay_result_to_claude,
    send_task,
    watch_task,
)

_RESUME_CMD: Dict[str, List[str]] = {
    "claude": ["claude", "--continue"],
    "codex": ["codex", "resume", "--last"],
    "agy": ["agy", "--continue"],
}

_FRESH_CMD: Dict[str, List[str]] = {
    "claude": ["claude"],
    "codex": ["codex"],
    "agy": ["agy"],
}


def _resolve_agent_launch_cmd(agent_id: str, root: Path, profile: str = "full_autonomy") -> List[str]:
    """Return project-isolated agent launch command based on workspace root."""
    from memory_os.toolkit.startup_profile import apply_profile_to_flags

    is_main_repo = root.name.lower() in ("memory_os", "memory-os", "memory_os_public")
    registry = load_agent_registry(root)
    agent_cfg = registry.get("agent", {}).get(agent_id, {})
    default_cmd = agent_cfg.get("command", [agent_id])
    
    base_cmd = list(_RESUME_CMD.get(agent_id, default_cmd) if is_main_repo else _FRESH_CMD.get(agent_id, default_cmd))
    launch_flags = apply_profile_to_flags(list(agent_cfg.get("launch_flags") or []), profile)
    base_cmd.extend(launch_flags)

    if agent_id == "claude":
        prompt_file = root / "agent_context" / "agents" / "prompts" / "claude.md"
        if prompt_file.exists():
            base_cmd.extend(["--append-system-prompt-file", str(prompt_file)])
    elif agent_id == "codex":
        prompt_file = root / "agent_context" / "agents" / "prompts" / "codex.md"
        if prompt_file.exists():
            try:
                prompt_content = prompt_file.read_text(encoding="utf-8")
                base_cmd.extend(["-c", f"system_prompt={prompt_content}"])
            except Exception as _e:
                import sys as _sys
                print(f'Ignored exception: {_e}', file=_sys.stderr)

    return base_cmd


def _cli_agent_ids(root: Path) -> List[str]:
    agents = load_agent_registry(root, fallback_to_main=True).get("agent", {})
    return [aid for aid, cfg in agents.items() if cfg.get("kind") == "cli_agent" and aid != "local"]


def _telegram_chat_cmd() -> List[str]:
    return [
        sys.executable,
        "-m",
        "memory_os",
        "telegram-daemon",
        "--swarm-control",
        "--swarm-watch-timeout",
        "0",
    ]


def launch_workspace(root: Optional[Path] = None, profile: str = "full_autonomy") -> None:
    """Attach to existing session or create a new one and exec into it."""
    from memory_os.core.config import MemoryOSConfig
    from memory_os.toolkit.project_secrets import ensure_project_telegram_token
    from memory_os.toolkit.startup_profile import record_startup_profile
    from memory_os.toolkit.workspace_runtime import (
        WorkspacePaneSpec,
        WorkspaceSpec,
        select_workspace_runtime,
    )

    if root is None:
        root = Path(__file__).resolve().parents[3]

    record_startup_profile(root, profile)

    # Run first-launch bootstrap check if marker does not exist
    from memory_os.toolkit.bootstrap_installer import is_bootstrapped, run_bootstrap, mark_bootstrapped
    if not is_bootstrapped() and sys.stdin.isatty() and sys.stdout.isatty():
        print("🔍 First launch detected. Checking required system tools and agent CLIs...")
        run_bootstrap(force=False, interactive=True)
        mark_bootstrapped()

    ensure_project_telegram_token(
        root,
        interactive=sys.stdin.isatty() and sys.stdout.isatty(),
    )
    PromptPrincipleSync(root).sync()

    cfg = MemoryOSConfig(str(root / "memory_os.config.json"))
    session_name = cfg.tmux_session_name

    project = root.name  # e.g. "memory_os"
    cli_agents = _cli_agent_ids(root)
    venv = (root / ".venv" / "bin" / "activate").exists()

    panes: List[WorkspacePaneSpec] = []
    for agent_id in (cli_agents or ["claude"]):
        panes.append(
            WorkspacePaneSpec(
                key=agent_id,
                label=f"{agent_id}:{project}",
                command=_resolve_agent_launch_cmd(agent_id, root, profile=profile),
                kind="cli_agent",
            )
        )
    panes.append(
        WorkspacePaneSpec(
            key="agent-manager",
            label="agent-manager",
            command=[sys.executable, "-m", "memory_os", "agent-manager"],
            kind="manager",
        )
    )
    panes.append(
        WorkspacePaneSpec(
            key="telegram-chat",
            label="telegram-chat",
            command=_telegram_chat_cmd(),
            kind="telegram",
        )
    )

    runtime_name = os.environ.get("MEMORY_OS_WORKSPACE_RUNTIME", "auto")
    runtime = select_workspace_runtime(runtime_name)
    spec = WorkspaceSpec(root=root, session_name=session_name, panes=panes, venv=venv)
    runtime.launch(spec, attach=True)
