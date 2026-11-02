import json
from pathlib import Path

from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.memory_graph_service import MemoryGraphService


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


def test_service_health_curate_and_browse(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {"id": "fact:root", "type": "fact", "summary": "root node", "status": "verified", "trust": "verified", "related_nodes": ["fact:leaf"], "tags": ["graph"]},
            {"id": "fact:leaf", "type": "fact", "summary": "leaf node", "status": "verified", "trust": "verified", "related_nodes": [], "tags": ["graph"]},
            {"id": "fact:dup", "type": "fact", "summary": "root node", "status": "verified", "trust": "verified", "related_nodes": [], "tags": ["graph"]},
        ],
    )
    _write_jsonl(
        config.memory_dir / "edges.jsonl",
        [
            {"source": "fact:root", "target": "fact:leaf", "type": "contains"},
        ],
    )

    class FakeEvalRunner:
        def __init__(self, config):
            self.config = config

        def list_suites(self):
            return [{"name": "retrieval-relevance"}]

        def run(self, suite):
            return {"ok": True, "recall_at_5": 1.0, "pass_threshold": 1.0}

    monkeypatch.setattr("memory_os.toolkit.memory_graph_service.EvalRunner", FakeEvalRunner, raising=False)

    service = MemoryGraphService(config)
    health = service.health()
    curate = service.curate(limit=5)
    browse = service.browse(node_id="fact:root", depth=1, limit=2, neighbors=2, edges_limit=2)

    assert health["status"] == "green"
    assert curate["merge_candidates"]
    assert {curate["merge_candidates"][0]["left"], curate["merge_candidates"][0]["right"]} == {"fact:root", "fact:dup"}
    assert browse["status"] == "ok"
    assert browse["focus_ids"] == ["fact:root"]
    assert browse["results"][0]["focus"]["id"] == "fact:root"
    assert browse["results"][0]["focus_signal"]["degree"] == 1
    assert "outbound=1" in browse["results"][0]["focus_signal"]["reason"]


def test_service_memory_management_patch_paths(tmp_path):
    config = make_config(tmp_path)
    service = MemoryGraphService(config)

    created = service.upsert_node({
        "id": "fact:api",
        "type": "fact",
        "summary": "memory api node",
        "status": "verified",
        "trust": "verified",
        "tags": "api,ui",
        "evidence": ["README.md"],
    })
    service.upsert_node({
        "id": "fact:target",
        "type": "fact",
        "summary": "target node",
        "status": "verified",
        "trust": "verified",
    })
    assert created["status"] == "ok"

    listed = service.list_nodes(query="memory api", tag="ui")
    assert listed["total"] == 1
    assert listed["nodes"][0]["id"] == "fact:api"
    timeline = service.timeline(days=1)
    timeline_ids = [node["id"] for day in timeline["days"] for node in day["nodes"]]
    assert "fact:api" in timeline_ids

    updated = service.update_node("fact:api", summary="memory api node updated", tags=["api", "updated"])
    assert updated["status"] == "ok"
    assert updated["node"]["summary"] == "memory api node updated"
    assert "updated" in updated["node"]["tags"]

    pinned = service.pin_node("fact:api", True)
    assert pinned["pinned"] is True
    assert "pinned" in pinned["node"]["tags"]

    verified = service.verify_node("fact:api")
    assert verified["verified"] is True
    assert service.get_node("fact:api")["node"]["protocol_level"] == 99

    edge = service.upsert_edge({
        "source": "fact:api",
        "target": "fact:target",
        "type": "depends_on",
        "confidence": 1.0,
    })
    assert edge["status"] == "ok"
    assert service.list_edges(source="fact:api")["total"] == 1

    deleted_edge = service.delete_edge("fact:api", "fact:target", "depends_on")
    assert deleted_edge["deleted"] is True
    assert service.list_edges(source="fact:api")["total"] == 0

    service.upsert_edge({
        "source": "fact:api",
        "target": "fact:target",
        "type": "depends_on",
        "confidence": 1.0,
    })
    deleted_node = service.delete_node("fact:api")
    assert deleted_node["deleted"] is True
    assert deleted_node["deleted_edges"] == 1
    assert service.get_node("fact:api")["status"] == "not_found"
    assert service.list_edges(target="fact:target")["total"] == 0

    service.upsert_node({"id": "fact:merge-source", "summary": "source summary", "status": "verified"})
    service.upsert_node({"id": "fact:merge-target", "summary": "target summary", "status": "verified"})
    merged = service.merge_nodes("fact:merge-source", "fact:merge-target")
    assert merged["merged"] is True
    assert service.get_node("fact:merge-source")["status"] == "not_found"
    assert "Merged from: source summary" in service.get_node("fact:merge-target")["node"]["summary"]

    exported = service.export_graph()
    assert exported["status"] == "ok"
    assert any(node["id"] == "fact:merge-target" for node in exported["nodes"])

    events = service.list_events(node_id="fact:merge-target")
    assert any(event.get("event") == "memory.ui.node.merged" for event in events["events"])


def test_list_nodes_owns_since_internal_and_pagination_filters(tmp_path, monkeypatch):
    internal_dir = tmp_path / "internal_memory"
    monkeypatch.setattr(
        MemoryOSConfig,
        "internal_memory_dir",
        property(lambda self: internal_dir),
    )
    config = make_config(tmp_path)
    config.internal_memory_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {"id": "fact:old", "type": "fact", "summary": "old", "status": "verified", "trust": "verified", "freshness": "2026-01-01T00:00:00+00:00"},
            {"id": "fact:new", "type": "fact", "summary": "new", "status": "verified", "trust": "verified", "freshness": "2026-07-01T00:00:00+00:00"},
        ],
    )
    _write_jsonl(
        config.internal_memory_dir / "nodes.jsonl",
        [{"id": "internal:new", "type": "fact", "summary": "internal", "status": "verified", "trust": "verified", "freshness": "2026-07-02T00:00:00+00:00"}],
    )

    result = MemoryGraphService(config).list_nodes(
        since="2026-06-01",
        include_internal=True,
        limit=1,
        offset=1,
    )

    assert result["total"] == 2
    assert [node["id"] for node in result["nodes"]] == ["internal:new"]
