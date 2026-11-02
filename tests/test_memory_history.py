import json
from pathlib import Path

from memory_os.core.config import MemoryOSConfig
from memory_os.modules.history import MemoryHistory


def make_config(tmp_path: Path) -> MemoryOSConfig:
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "memory" / "nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "edges.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "events.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "archived_nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "archived_edges.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({"version": "0.1", "memory_dir": "memory", "db_path": "memory/memory_os.db"}),
        encoding="utf-8",
    )
    return MemoryOSConfig(str(tmp_path / "memory_os.config.json"))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_memory_history_show_reports_replacement_links(tmp_path):
    config = make_config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {
                "id": "fact:new",
                "type": "fact",
                "summary": "new node",
                "status": "verified",
                "trust": "verified",
                "evidence": [],
                "related_nodes": [],
                "tags": [],
            },
        ],
    )
    _write_jsonl(
        config.memory_dir / "edges.jsonl",
        [{"source": "fact:new", "target": "fact:old", "type": "overrides"}],
    )
    _write_jsonl(
        config.memory_dir / "archived_nodes.jsonl",
        [
            {
                "id": "fact:old",
                "type": "fact",
                "summary": "old node",
                "status": "superseded",
                "trust": "verified",
                "evidence": [],
                "related_nodes": [],
                "tags": [],
            },
        ],
    )
    _write_jsonl(config.memory_dir / "archived_edges.jsonl", [])
    _write_jsonl(
        config.memory_dir / "events.jsonl",
        [
            {
                "timestamp": "2026-07-02T00:00:00Z",
                "event": "memory.node.deprecated",
                "node_id": "fact:old",
                "claim": "Deprecated to superseded via edge overrides from fact:new",
                "evidence": [],
                "validator": "test",
                "status": "accepted",
            }
        ],
    )

    history = MemoryHistory(config)
    old_report = history.show("fact:old")
    new_report = history.show("fact:new")

    assert old_report["found"] is True
    assert old_report["replaced_by"] == ["fact:new"]
    assert old_report["replaces"] == []
    assert new_report["replaces"] == ["fact:old"]
    assert new_report["replaced_by"] == []
    assert old_report["superseded_by_details"] == [
        {"id": "fact:new", "summary": "new node", "reason": ""}
    ]


def test_memory_history_show_superseded_details_with_reason(tmp_path, capsys):
    import argparse
    from memory_os.cli import cmd_memory_show

    config = make_config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {
                "id": "fact:newer",
                "type": "fact",
                "summary": "newer summary content",
                "status": "verified",
                "trust": "verified",
                "evidence": [],
                "related_nodes": [],
                "tags": [],
            },
        ],
    )
    _write_jsonl(
        config.memory_dir / "edges.jsonl",
        [{"source": "fact:newer", "target": "fact:older", "type": "supersedes", "reason": "more recent data available"}],
    )
    _write_jsonl(
        config.memory_dir / "archived_nodes.jsonl",
        [
            {
                "id": "fact:older",
                "type": "fact",
                "summary": "older summary content",
                "status": "superseded",
                "trust": "verified",
                "evidence": [],
                "related_nodes": [],
                "tags": [],
            },
        ],
    )
    _write_jsonl(config.memory_dir / "archived_edges.jsonl", [])
    _write_jsonl(config.memory_dir / "events.jsonl", [])

    history = MemoryHistory(config)
    report = history.show("fact:older")
    assert report["superseded_by_details"] == [
        {"id": "fact:newer", "summary": "newer summary content", "reason": "more recent data available"}
    ]

    # Test CLI output formatting
    args = argparse.Namespace(node_id="fact:older", format="text")
    exit_code = cmd_memory_show(args, config)
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Superseded by: fact:newer — newer summary content (more recent data available)" in captured.out

