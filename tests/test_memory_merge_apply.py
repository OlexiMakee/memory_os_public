import json
from pathlib import Path

from memory_os.cli import cmd_memory_merge_apply
from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.memory_graph_service import MemoryGraphService


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


def test_merge_apply_rewrites_nodes_and_edges(tmp_path, capsys):
    config = make_config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {"id": "fact:alpha", "type": "fact", "summary": "task ids and status reports drive routing", "status": "verified", "trust": "verified", "tags": ["routing"], "evidence": ["a.py"], "related_nodes": []},
            {"id": "fact:alpha-copy", "type": "fact", "summary": "status reports and task ids drive routing", "status": "verified", "trust": "verified", "tags": ["routing"], "evidence": ["a.py"], "related_nodes": []},
            {"id": "fact:beta", "type": "fact", "summary": "different topic entirely", "status": "verified", "trust": "verified", "tags": ["other"], "evidence": ["b.py"], "related_nodes": []},
        ],
    )
    _write_jsonl(
        config.memory_dir / "edges.jsonl",
        [
            {"source": "fact:beta", "target": "fact:alpha-copy", "type": "depends_on"},
        ],
    )

    report = MemoryGraphService(config).merge_apply(limit=5, dry_run=False)
    assert report["applied"] is True
    assert report["patch_ids"]
    assert report["applied_groups"] == 1
    assert report["merged_out_nodes"]
    canonical = report["merge_groups"][0]["canonical"]

    nodes = [json.loads(line) for line in (config.memory_dir / "nodes.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    edges = [json.loads(line) for line in (config.memory_dir / "edges.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    alpha = next(node for node in nodes if node["id"] == "fact:alpha")
    alpha_copy = next(node for node in nodes if node["id"] == "fact:alpha-copy")

    canonical_node = next(node for node in nodes if node["id"] == canonical)
    other_node = alpha if alpha["id"] != canonical else alpha_copy

    assert canonical_node["status"] == "verified"
    assert "task ids" in canonical_node["summary"]
    assert canonical_node["tags"] == ["routing"]
    assert other_node["status"] == "superseded"
    assert all(edge["target"] != other_node["id"] for edge in edges)
    assert any(edge["target"] == canonical for edge in edges)

    code = cmd_memory_merge_apply(type("Args", (), {"format": "json", "limit": 5, "dry_run": False})(), config)
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["applied"] is False
    assert payload["status"] in {"empty", "ok"}


def test_merge_apply_dry_run_leaves_graph_unchanged(tmp_path, capsys):
    config = make_config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {"id": "fact:alpha", "type": "fact", "summary": "task ids and status reports drive routing", "status": "verified", "trust": "verified", "tags": ["routing"], "evidence": ["a.py"], "related_nodes": []},
            {"id": "fact:alpha-copy", "type": "fact", "summary": "status reports and task ids drive routing", "status": "verified", "trust": "verified", "tags": ["routing"], "evidence": ["a.py"], "related_nodes": []},
        ],
    )

    before_nodes = (config.memory_dir / "nodes.jsonl").read_text(encoding="utf-8")
    report = MemoryGraphService(config).merge_apply(limit=5, dry_run=True)
    after_nodes = (config.memory_dir / "nodes.jsonl").read_text(encoding="utf-8")
    assert report["applied"] is False
    assert report["applied_groups"] == 1
    assert before_nodes == after_nodes
