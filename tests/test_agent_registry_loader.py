import builtins
from types import SimpleNamespace

import pytest

from memory_os.core import toml_compat
from memory_os.toolkit import agent_registry
from memory_os.toolkit.agent_registry import AgentRegistryLoadError, load_agent_registry


def _write_registry(root, text: str) -> None:
    path = root / "agent_context" / "agents" / "registry.toml"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")


def test_load_agent_registry_preserves_declaration_order(tmp_path):
    _write_registry(
        tmp_path,
        """
[agent.codex]
kind = "cli_agent"

[agent.agy]
kind = "cli_agent"
""",
    )

    registry = load_agent_registry(tmp_path)

    assert list(registry["agent"]) == ["codex", "agy"]


def test_load_agent_registry_can_fall_back_to_main_root(tmp_path, monkeypatch):
    main_root = tmp_path / "main"
    project_root = tmp_path / "project"
    _write_registry(main_root, '[agent.claude]\nkind = "cli_agent"\n')
    monkeypatch.setattr(agent_registry, "_main_repo_root", lambda: main_root)

    registry = load_agent_registry(project_root, fallback_to_main=True)

    assert registry["agent"]["claude"]["kind"] == "cli_agent"


def test_load_agent_registry_reports_malformed_toml_in_strict_mode(tmp_path):
    _write_registry(tmp_path, "[agent.codex\n")

    assert load_agent_registry(tmp_path) == {}
    with pytest.raises(AgentRegistryLoadError, match="Cannot load agent registry"):
        load_agent_registry(tmp_path, strict=True)


def test_toml_compat_falls_back_for_python_before_311(monkeypatch):
    """agent_registry (and skill_registry/workspace_registry) all load TOML through
    core.toml_compat now -- one fallback implementation, not one per caller.
    """
    real_import = builtins.__import__
    fallback_parser = SimpleNamespace(__name__="tomli")

    def import_without_tomllib(name, *args, **kwargs):
        if name == "tomllib":
            raise ImportError("simulated Python 3.10")
        if name == "tomli":
            return fallback_parser
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_tomllib)

    assert toml_compat.toml_module().__name__ == "tomli"
