import json
from pathlib import Path

from memory_os.cli import cmd_memory_curate
from memory_os.core.config import MemoryOSConfig


def make_config(tmp_path: Path) -> MemoryOSConfig:
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "memory" / "nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "edges.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "events.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({"version": "0.1", "memory_dir": "memory", "db_path": "memory/memory_os.db"}),
        encoding="utf-8",
    )
    return MemoryOSConfig(str(tmp_path / "memory_os.config.json"))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_memory_curate_finds_merge_candidate_and_component(tmp_path, capsys):
    config = make_config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {
                "id": "fact:alpha",
                "type": "fact",
                "summary": "Claude routing uses explicit task ids and status reports",
                "tags": ["routing", "telegram"],
                "evidence": ["a.py"],
                "status": "verified",
            },
            {
                "id": "fact:alpha-copy",
                "type": "fact",
                "summary": "Explicit task ids and status reports drive Claude routing",
                "tags": ["routing", "telegram"],
                "evidence": ["a.py"],
                "status": "verified",
            },
            {
                "id": "fact:other",
                "type": "fact",
                "summary": "Local browser launcher defaults to a desktop session",
                "tags": ["desktop"],
                "evidence": ["b.py"],
                "status": "verified",
            },
            {
                "id": "fact:linked",
                "type": "fact",
                "summary": "Desktop launcher depends on session detection",
                "tags": ["desktop"],
                "evidence": ["c.py"],
                "status": "verified",
            },
        ],
    )
    _write_jsonl(
        config.memory_dir / "edges.jsonl",
        [
            {"source": "fact:other", "target": "fact:linked", "type": "depends_on"},
        ],
    )

    code = cmd_memory_curate(type("Args", (), {"format": "json", "limit": 10})(), config)
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert report["status"] == "yellow"
    assert report["live_nodes"] == 4
    assert report["merge_candidates"]
    pair = report["merge_candidates"][0]
    assert {pair["left"], pair["right"]} == {"fact:alpha", "fact:alpha-copy"}
    assert report["primary_recommendation"] == "merge-preview"
    assert report["next_actions"][0]["action"] == "merge-preview"
    assert any(action["action"] == "browse" for action in report["next_actions"])
    assert report["components"]
    assert report["components"][0]["size"] == 2
    assert set(report["orphan_nodes"]) == {"fact:alpha", "fact:alpha-copy"}
