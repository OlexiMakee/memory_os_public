import json
from pathlib import Path

from memory_os.core.config import MemoryOSConfig
from memory_os.modules.timecode_normalizer import TimecodeNormalizer


def _config(root: Path) -> MemoryOSConfig:
    (root / "memory").mkdir()
    (root / "agent_context").mkdir()
    (root / "memory_os.config.json").write_text(
        json.dumps(
            {
                "version": "0.1",
                "memory_dir": "memory",
                "db_path": "memory/memory_os.db",
                "user_timezone": "Europe/Kyiv",
            }
        ),
        encoding="utf-8",
    )
    (root / "memory" / "edges.jsonl").write_text("", encoding="utf-8")
    return MemoryOSConfig(str(root / "memory_os.config.json"))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_timecode_normalizer_converts_naive_values_and_is_idempotent(tmp_path):
    config = _config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {
                "id": "fact:naive-time",
                "type": "fact",
                "summary": "naive timestamp",
                "evidence": [],
                "status": "verified",
                "freshness": "2026-07-01T08:52:32",
                "valid_from": "2026-07-01T08:52:32",
                "trust": "verified",
                "related_nodes": [],
                "tags": [],
            }
        ],
    )
    _write_jsonl(
        config.memory_dir / "events.jsonl",
        [
            {
                "timestamp": "2026-07-01T08:52:32",
                "event": "memory.node.verified",
                "node_id": "fact:naive-time",
                "claim": "verified",
                "evidence": [],
                "validator": "test",
                "status": "accepted",
            }
        ],
    )

    first = TimecodeNormalizer(config).normalize()
    second = TimecodeNormalizer(config).normalize()

    assert first.nodes_fixed == 1
    assert first.events_fixed == 1
    assert first.unresolvable == 0
    assert second.nodes_fixed == 0
    assert second.events_fixed == 0
    assert second.unresolvable == 0

    node = _read_jsonl(config.memory_dir / "nodes.jsonl")[0]
    assert node["freshness"] == "2026-07-01T11:52:32+03:00"
    assert node["valid_from"] == "2026-07-01T11:52:32+03:00"
    events = _read_jsonl(config.memory_dir / "events.jsonl")
    assert events[0]["timestamp"] == "2026-07-01T11:52:32+03:00"
    assert any(event["event"] == "memory.patch.replace_nodes" for event in events)
    assert any(event["event"] == "memory.patch.replace_events" for event in events)


def test_timecode_normalizer_replaces_fresh_literal_from_earliest_event(tmp_path):
    config = _config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {
                "id": "fact:fresh-time",
                "type": "fact",
                "summary": "fresh literal",
                "evidence": [],
                "status": "verified",
                "freshness": "fresh",
                "trust": "verified",
                "related_nodes": [],
                "tags": [],
            }
        ],
    )
    _write_jsonl(
        config.memory_dir / "events.jsonl",
        [
            {
                "timestamp": "2026-07-01T12:00:00+00:00",
                "event": "memory.node.proposed",
                "node_id": "fact:fresh-time",
                "claim": "proposed",
                "evidence": [],
                "validator": "test",
                "status": "pending",
            },
            {
                "timestamp": "2026-07-01T10:00:00+00:00",
                "event": "memory.node.verified",
                "node_id": "fact:fresh-time",
                "claim": "verified",
                "evidence": [],
                "validator": "test",
                "status": "accepted",
            },
        ],
    )

    result = TimecodeNormalizer(config).normalize()

    assert result.nodes_fixed == 1
    # offset-aware event timestamps are canonical — never rewritten to another zone
    assert result.events_fixed == 0
    assert result.unresolvable == 0
    node = _read_jsonl(config.memory_dir / "nodes.jsonl")[0]
    assert node["freshness"] == "2026-07-01T13:00:00+03:00"


def test_timecode_normalizer_reports_unresolvable_fresh_literal(tmp_path):
    config = _config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {
                "id": "fact:fresh-unresolved",
                "type": "fact",
                "summary": "fresh literal without evidence",
                "evidence": [],
                "status": "verified",
                "freshness": "fresh",
                "trust": "verified",
                "related_nodes": [],
                "tags": [],
            }
        ],
    )
    _write_jsonl(config.memory_dir / "events.jsonl", [])

    result = TimecodeNormalizer(config).normalize()

    assert result.nodes_fixed == 1
    assert result.events_fixed == 0
    assert result.unresolvable == 1
    node = _read_jsonl(config.memory_dir / "nodes.jsonl")[0]
    assert node["freshness"] == ""
