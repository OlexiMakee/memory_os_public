import json
from pathlib import Path

from memory_os.cli import cmd_memory_merge_preview
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


def test_merge_preview_groups_semantic_duplicates(tmp_path, capsys):
    config = make_config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {"id": "fact:alpha", "type": "fact", "summary": "task ids and status reports drive routing", "status": "verified", "trust": "verified", "tags": ["routing"], "evidence": ["a.py"]},
            {"id": "fact:alpha-copy", "type": "fact", "summary": "status reports and task ids drive routing", "status": "verified", "trust": "verified", "tags": ["routing"], "evidence": ["a.py"]},
            {"id": "fact:beta", "type": "fact", "summary": "different topic entirely", "status": "verified", "trust": "verified", "tags": ["other"], "evidence": ["b.py"]},
        ],
    )

    report = MemoryGraphService(config).merge_preview(limit=5)
    assert report["status"] == "ok"
    assert report["merge_groups"]
    group = report["merge_groups"][0]
    assert {group["canonical"], *group["members"]} >= {"fact:alpha", "fact:alpha-copy"}
    assert "routing" in group["merged_tags"]
    assert group["replacement_plan"]

    code = cmd_memory_merge_preview(type("Args", (), {"format": "json", "limit": 5})(), config)
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code == 0
    assert payload["merge_groups"][0]["canonical"] == group["canonical"]
