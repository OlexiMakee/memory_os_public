import json
from pathlib import Path

from memory_os.cli import cmd_memory_health
from memory_os.core.config import MemoryOSConfig


def make_config(tmp_path: Path) -> MemoryOSConfig:
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "memory" / "nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "edges.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "events.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "archived_nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "archived_edges.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps(
            {
                "version": "0.1",
                "memory_dir": "memory",
                "capsules_file": "agent_context/task_capsules.jsonl",
                "db_path": "memory/memory_os.db",
            }
        ),
        encoding="utf-8",
    )
    return MemoryOSConfig(str(tmp_path / "memory_os.config.json"))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_memory_health_reports_green_state(tmp_path, monkeypatch, capsys):
    config = make_config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {"id": "fact:1", "summary": "first", "type": "fact", "confidence": 0.4},
            {"id": "fact:2", "summary": "second", "type": "fact"},
            {"id": "comm:1", "summary": "noise", "type": "comm"},
        ],
    )
    _write_jsonl(
        config.memory_dir / "edges.jsonl",
        [
            {"source": "fact:1", "target": "comm:1", "type": "relates"},
            {"source": "fact:2", "target": "comm:1", "type": "relates"},
        ],
    )
    _write_jsonl(
        config.memory_dir / "archived_nodes.jsonl",
        [{"id": "fact:old", "summary": "archived", "type": "fact"}],
    )
    _write_jsonl(
        config.memory_dir / "archived_edges.jsonl",
        [{"source": "fact:old", "target": "fact:1", "type": "relates"}],
    )

    class FakeEvalRunner:
        def __init__(self, config):
            self.config = config

        def list_suites(self):
            return [{"name": "retrieval-relevance"}]

        def run(self, suite):
            assert suite == "retrieval-relevance"
            return {"ok": True, "recall_at_5": 1.0, "pass_threshold": 1.0}

    monkeypatch.setattr("memory_os.toolkit.memory_graph_service.EvalRunner", FakeEvalRunner, raising=False)

    code = cmd_memory_health(type("Args", (), {"format": "json"})(), config)
    out = capsys.readouterr().out
    report = json.loads(out)

    assert code == 0
    assert report["status"] == "green"
    assert report["live_nodes"] == 3
    assert report["comm_nodes"] == 1
    assert report["eval_status"] == "ok"
    assert report["confidence_floor"] == 0.5
    assert report["low_confidence_count"] == 1
    assert report["low_confidence_nodes"] == ["fact:1"]
    assert report["top_connected_nodes"][0]["id"] == "comm:1"


def test_memory_health_fails_on_eval_failure(tmp_path, monkeypatch, capsys):
    config = make_config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [{"id": "fact:1", "summary": "first", "type": "fact"}],
    )

    class FakeEvalRunner:
        def __init__(self, config):
            self.config = config

        def list_suites(self):
            return [{"name": "retrieval-relevance"}]

        def run(self, suite):
            return {"ok": False, "recall_at_5": 0.25, "pass_threshold": 1.0}

    monkeypatch.setattr("memory_os.toolkit.memory_graph_service.EvalRunner", FakeEvalRunner, raising=False)

    code = cmd_memory_health(type("Args", (), {"format": "json"})(), config)
    out = capsys.readouterr().out
    report = json.loads(out)

    assert code == 1
    assert report["status"] == "red"
    assert report["eval_status"] == "failed"


def test_memory_health_marks_missing_eval_as_yellow(tmp_path, monkeypatch, capsys):
    config = make_config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [{"id": "fact:1", "summary": "first", "type": "fact"}],
    )

    class FakeEvalRunner:
        def __init__(self, config):
            self.config = config

        def list_suites(self):
            return []

        def run(self, suite):
            raise AssertionError("run() must not be called when retrieval suite is missing")

    monkeypatch.setattr("memory_os.toolkit.memory_graph_service.EvalRunner", FakeEvalRunner, raising=False)

    code = cmd_memory_health(type("Args", (), {"format": "json"})(), config)
    out = capsys.readouterr().out
    report = json.loads(out)

    assert code == 0
    assert report["status"] == "yellow"
    assert report["eval_status"] == "unavailable"


def test_memory_health_text_includes_confidence_floor(tmp_path, monkeypatch, capsys):
    config = make_config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {"id": "fact:1", "summary": "first", "type": "fact", "confidence": 0.4},
            {"id": "fact:2", "summary": "second", "type": "fact"},
        ],
    )
    _write_jsonl(config.memory_dir / "edges.jsonl", [])

    class FakeEvalRunner:
        def __init__(self, config):
            self.config = config

        def list_suites(self):
            return []

        def run(self, suite):
            raise AssertionError("run() must not be called")

    monkeypatch.setattr("memory_os.toolkit.memory_graph_service.EvalRunner", FakeEvalRunner, raising=False)

    code = cmd_memory_health(type("Args", (), {"format": "text"})(), config)
    out = capsys.readouterr().out

    assert code == 0
    assert "Confidence floor: 0.50" in out
    assert "1 node(s) below" in out
