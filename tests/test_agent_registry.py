import argparse
import json

from memory_os.cli import cmd_agent_registry
from memory_os.core.config import MemoryOSConfig


def test_agent_registry_audit_accepts_ollama_http_without_cli(tmp_path, monkeypatch, capsys):
    agents_dir = tmp_path / "agent_context" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "registry.toml").write_text(
        """
[agent.local-router]
kind = "local_model"
command = ["ollama", "run", "qwen3:4b"]
capabilities = ["classify"]
""",
        encoding="utf-8",
    )
    (tmp_path / "memory_os.config.json").write_text(json.dumps({"version": "0.1"}), encoding="utf-8")

    monkeypatch.setattr("memory_os.cli_groups.agent_cmds.shutil.which", lambda _binary: None)
    monkeypatch.setattr(
        "memory_os.core.llm_service.ollama_http_health",
        lambda timeout=1.0: {
            "ok": True,
            "host": "http://127.0.0.1:11434",
            "model": "qwen3:4b",
            "detail": "HTTP API reachable",
        },
    )

    args = argparse.Namespace(root=str(tmp_path), registry_action="audit")
    code = cmd_agent_registry(args, MemoryOSConfig(str(tmp_path / "memory_os.config.json")))

    out = capsys.readouterr().out
    assert code == 0
    assert "ollama HTTP" in out
    assert "qwen3:4b" in out
