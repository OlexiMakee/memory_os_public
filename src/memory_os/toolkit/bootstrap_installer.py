"""Universal System Bootstrap & Agent Installer for Memory OS.

Checks system prerequisite tools (tmux, git, curl, sqlite3) and
agent systems (claude, codex, agy, hermes) upon first launch or via 'memory_os install'.
"""

import os
import json
from memory_os.toolkit.agent_registry import KNOWN_AGENTS
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple


SYSTEM_TOOLS = ["tmux", "zellij", "git", "curl", "sqlite3"]
KNOWN_AGENTS = list(KNOWN_AGENTS) + ["hermes"]
BOOTSTRAP_MARKER = Path.home() / ".memory_os" / ".bootstrapped"


def check_system_tools() -> Dict[str, bool]:
    """Check availability of core system tools in PATH."""
    return {tool: (shutil.which(tool) is not None) for tool in SYSTEM_TOOLS}


def check_installed_agents() -> Dict[str, bool]:
    """Check availability of agent CLI executables in PATH."""
    return {agent: (shutil.which(agent) is not None) for agent in KNOWN_AGENTS}


def is_bootstrapped() -> bool:
    """Return True if first-launch bootstrap has been performed."""
    return BOOTSTRAP_MARKER.exists()


def mark_bootstrapped() -> None:
    """Create marker file recording completed bootstrap."""
    BOOTSTRAP_MARKER.parent.mkdir(parents=True, exist_ok=True)
    BOOTSTRAP_MARKER.write_text("bootstrapped=true\n", encoding="utf-8")


def prompt_system_tool_install(missing: List[str]) -> bool:
    """Prompt user and attempt installation of missing system tools in Ubuntu."""
    print(f"\n⚠️ Missing required system tools: {', '.join(missing)}")
    try:
        ans = input("Would you like to install missing system tools? [Y/n]: ").strip().lower()
        if ans and ans != "y":
            return False
        
        apt_missing = [t for t in missing if t != "zellij"]
        if apt_missing:
            cmd = ["sudo", "apt-get", "update"]
            print("Running sudo apt-get update...")
            subprocess.run(cmd, check=False)

            install_cmd = ["sudo", "apt-get", "install", "-y"] + apt_missing
            print(f"Running {' '.join(install_cmd)}...")
            subprocess.run(install_cmd, check=False)

        if "zellij" in missing:
            print("Installing zellij via snap...")
            res = subprocess.run(["sudo", "snap", "install", "zellij", "--classic"], check=False)
            return res.returncode == 0

        return True
    except (KeyboardInterrupt, EOFError):
        return False


def prompt_agent_systems_setup(agents_status: Dict[str, bool]) -> None:
    """Present interactive checklist for agent framework selection & installation guidance."""
    print("\n🤖 Memory OS — Agent Framework Systems Status:\n")
    for agent, installed in agents_status.items():
        status_str = "🟢 Installed" if installed else "⚪ Not found in PATH"
        print(f"  [{'✓' if installed else ' '}] {agent:<10} — {status_str}")
    
    missing_agents = [a for a, inst in agents_status.items() if not inst]
    if missing_agents:
        print(f"\n💡 Tip: You can install or configure missing CLI agents ({', '.join(missing_agents)}) anytime.")
        print("  - Claude CLI:  npm install -g @anthropic-ai/claude-code")
        print("  - Codex CLI:   pip install codex-cli")
        print("  - AGY CLI:     pip install antigravity-cli")
        print("  - Hermes AI:   pip install hermes-agent")
    print()


def run_bootstrap(force: bool = False, interactive: bool = True, dry_run: bool = False, json_output: bool = False) -> Dict[str, Any]:
    """Main entrypoint for checking prerequisites and agent systems."""
    tools_status = check_system_tools()
    agents_status = check_installed_agents()
    missing_tools = [t for t, avail in tools_status.items() if not avail]

    if json_output:
        res = {
            "bootstrapped": is_bootstrapped(),
            "system_tools": tools_status,
            "agent_systems": agents_status,
            "missing_system_tools": missing_tools,
        }
        print(json.dumps(res, indent=2))
        return res

    if not force and is_bootstrapped() and not dry_run:
        if shutil.which("tmux") is None and interactive and sys.stdin.isatty():
            prompt_system_tool_install(["tmux"])
        return {"bootstrapped": True, "system_tools": tools_status, "agent_systems": agents_status}

    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"🚀 {prefix}Running Memory OS System Bootstrap & Environment Diagnostic...\n")

    if missing_tools and interactive and sys.stdin.isatty() and not dry_run:
        prompt_system_tool_install(missing_tools)
    elif missing_tools:
        print(f"⚠️ Warning: Missing system tools: {', '.join(missing_tools)}")

    if interactive and sys.stdin.isatty() and not dry_run:
        prompt_agent_systems_setup(agents_status)

    # Re-check tools after possible interactive install
    current_tools = check_system_tools()
    all_critical_present = current_tools.get("tmux", False) and current_tools.get("git", False)

    if not dry_run and all_critical_present:
        mark_bootstrapped()

    return {"bootstrapped": is_bootstrapped(), "system_tools": current_tools, "agent_systems": agents_status}
