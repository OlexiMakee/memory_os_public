"""Canonical loader for the Memory OS agent registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from memory_os.core.toml_compat import load_toml_path


class AgentRegistryLoadError(ValueError):
    """Raised when a requested agent registry cannot be loaded."""


KNOWN_AGENTS = ("claude", "codex", "agy")


def _main_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def agent_registry_path(root: Path, *, fallback_to_main: bool = False) -> Path:
    path = Path(root) / "agent_context" / "agents" / "registry.toml"
    if fallback_to_main and not path.exists():
        return _main_repo_root() / "agent_context" / "agents" / "registry.toml"
    return path


def load_agent_registry(
    root: Path,
    *,
    fallback_to_main: bool = False,
    strict: bool = False,
) -> Dict[str, Any]:
    """Load the complete registry document while preserving TOML order."""
    path = agent_registry_path(root, fallback_to_main=fallback_to_main)
    if not path.exists():
        if strict:
            raise AgentRegistryLoadError(f"Agent registry not found: {path}")
        return {}

    try:
        data = load_toml_path(path)
        agents = data.get("agent", {})
        if not isinstance(agents, dict):
            raise AgentRegistryLoadError(f"Invalid [agent] table in {path}")
        return data
    except (OSError, ImportError, ValueError) as exc:
        if strict:
            if isinstance(exc, AgentRegistryLoadError):
                raise
            raise AgentRegistryLoadError(f"Cannot load agent registry {path}: {exc}") from exc
        return {}
