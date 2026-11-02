import argparse
import json

from memory_os import MemoryOS, MemoryOSConfig
from memory_os.cli import cmd_doctor


def test_doctor_json_is_structured_and_queries_database(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "memory_os.config.json"
    config_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    config = MemoryOSConfig(str(config_path))

    for directory in (config.memory_dir, tmp_path / "agent_context", tmp_path / "workflows"):
        directory.mkdir(parents=True, exist_ok=True)
    for path in (
        config.memory_dir / "nodes.jsonl",
        config.memory_dir / "edges.jsonl",
        config.memory_dir / "events.jsonl",
        config.capsules_file,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    MemoryOS(config)

    monkeypatch.setattr("memory_os.core.llm_service._discover_ollama_model", lambda host: None)
    monkeypatch.setattr(
        "memory_os.toolkit.workspace_runtime.workspace_runtime_diagnostics",
        lambda spec: {"runtimes": {}, "zellij_exited_sessions": []},
    )

    exit_code = cmd_doctor(argparse.Namespace(format="json"), config)

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["ok"] is True
    assert report["database"]["active_nodes"] == 0
    assert report["database"]["telemetry_records"] == 0
    assert report["daemon"]["state"] == "stopped"
