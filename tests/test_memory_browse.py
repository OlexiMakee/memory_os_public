import json
from pathlib import Path

from memory_os.cli import cmd_memory_browse
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
        json.dumps({"version": "0.1", "memory_dir": "memory", "db_path": "memory/memory_os.db"}),
        encoding="utf-8",
    )
    return MemoryOSConfig(str(tmp_path / "memory_os.config.json"))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_memory_browse_focuses_node_and_neighbors(tmp_path, capsys):
    config = make_config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {"id": "fact:root", "type": "fact", "summary": "root node", "status": "verified", "trust": "verified", "related_nodes": ["fact:leaf"]},
            {"id": "fact:leaf", "type": "fact", "summary": "leaf node", "status": "verified", "trust": "verified", "related_nodes": []},
            {"id": "fact:other", "type": "fact", "summary": "other node", "status": "verified", "trust": "verified", "related_nodes": []},
        ],
    )
    _write_jsonl(
        config.memory_dir / "edges.jsonl",
        [
            {"source": "fact:other", "target": "fact:root", "type": "depends_on"},
            {"source": "fact:root", "target": "fact:leaf", "type": "contains"},
        ],
    )

    code = cmd_memory_browse(
        type("Args", (), {
            "query": "",
            "node_id": "fact:root",
            "depth": 1,
            "limit": 3,
            "neighbors": 5,
            "edges": 5,
            "format": "json",
        })(),
        config,
    )
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert report["focus_ids"] == ["fact:root"]
    focus = report["results"][0]
    assert focus["focus"]["id"] == "fact:root"
    assert focus["focus_signal"]["degree"] == 2
    assert "inbound=1" in focus["focus_signal"]["reason"]
    assert any(edge["source"] == "fact:other" and edge["target"] == "fact:root" for edge in focus["inbound_edges"])
    assert any(node["id"] == "fact:leaf" for node in focus["neighbor_nodes"])


def test_memory_browse_resolves_query(tmp_path, capsys):
    config = make_config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {"id": "fact:alpha", "type": "fact", "summary": "alpha routing note", "status": "verified", "trust": "verified", "related_nodes": []},
        ],
    )

    code = cmd_memory_browse(
        type("Args", (), {
            "query": "alpha routing",
            "node_id": None,
            "depth": 1,
            "limit": 3,
            "neighbors": 5,
            "edges": 5,
            "format": "json",
        })(),
        config,
    )
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert report["focus_ids"] == ["fact:alpha"]
