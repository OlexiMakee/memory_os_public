import json
from pathlib import Path

import pytest

from memory_os.core.config import MemoryOSConfig
from memory_os.core.patch import PatchValidationError, RelationPatch, RelationPatchStore
from memory_os.core.repository import MemoryRepository
from memory_os.core.storage import FileSystemMemoryStorage


def _config(root: Path) -> MemoryOSConfig:
    (root / "memory").mkdir()
    (root / "agent_context").mkdir()
    (root / "memory_os.config.json").write_text(
        json.dumps({"version": "0.1", "memory_dir": "memory", "db_path": "memory/memory_os.db"}),
        encoding="utf-8",
    )
    return MemoryOSConfig(config_path=str(root / "memory_os.config.json"))


def _edge_patch(edge_type: str, created: int = 0, verified: int = 0) -> RelationPatch:
    return RelationPatch(
        operation="upsert_edge",
        source="fact:a",
        target="fact:b",
        type=edge_type,
        domain="test",
        confidence=1.0,
        evidence=[],
        reason="test edge",
        created_by_protocol=created,
        required_verification_protocol=verified,
    )


def test_patch_store_enforces_relation_registry_by_default(tmp_path):
    config = _config(tmp_path)
    repo = MemoryRepository(FileSystemMemoryStorage(), config)
    store = RelationPatchStore(repo)

    with pytest.raises(PatchValidationError, match="Unknown relation type"):
        store.propose(_edge_patch("unknown_relation"))


def test_patch_store_rejects_under_protocol_semantic_edges(tmp_path):
    config = _config(tmp_path)
    repo = MemoryRepository(FileSystemMemoryStorage(), config)
    store = RelationPatchStore(repo)

    with pytest.raises(PatchValidationError, match="requires protocol >= 7"):
        store.propose(_edge_patch("overrides"))


def test_repository_sets_deterministic_relation_protocol_defaults(tmp_path):
    config = _config(tmp_path)
    storage = FileSystemMemoryStorage()
    repo = MemoryRepository(storage, config)

    repo.upsert_edge({"source": "fact:a", "target": "fact:b", "type": "co_tagged"})

    patches = repo.get_patches()
    assert len(patches) == 1
    patch = patches[0]
    assert patch.type == "co_tagged"
    assert patch.created_by_protocol == 1
    assert patch.required_verification_protocol == 1
    assert patch.status == "applied"


def test_repository_requires_explicit_protocol_for_semantic_relations(tmp_path):
    config = _config(tmp_path)
    repo = MemoryRepository(FileSystemMemoryStorage(), config)

    with pytest.raises(PatchValidationError):
        repo.upsert_edge({"source": "fact:new", "target": "fact:old", "type": "overrides"})

    repo.upsert_edge_with_protocol(
        {"source": "fact:new", "target": "fact:old", "type": "overrides"},
        protocol_level=8,
    )
    assert repo.get_patches()[0].status == "applied"


def test_upsert_node_defaults_confidence_from_relation_patch(tmp_path):
    config = _config(tmp_path)
    repo = MemoryRepository(FileSystemMemoryStorage(), config)
    store = RelationPatchStore(repo)
    patch = repo._make_patch(
        operation="upsert_node",
        target="fact:patch-confidence",
        patch_type="fact",
        confidence=0.42,
        evidence=[],
        payload={"summary": "patch confidence should become node confidence"},
        reason="test node confidence",
    )

    patch_id = store.propose(patch)
    assert store.apply(patch_id)

    nodes = [json.loads(line) for line in (config.memory_dir / "nodes.jsonl").read_text().splitlines()]
    assert nodes[0]["id"] == "fact:patch-confidence"
    assert nodes[0]["confidence"] == 0.42


def test_patch_store_apply_many_records_patch_audit_events(tmp_path):
    config = _config(tmp_path)
    repo = MemoryRepository(FileSystemMemoryStorage(), config)
    store = RelationPatchStore(repo)
    node = {
        "id": "fact:apply-many-audit",
        "type": "fact",
        "summary": "apply_many records audit events",
        "evidence": [],
        "status": "verified",
        "freshness": "2026-07-04T00:00:00Z",
        "trust": "verified",
        "related_nodes": [],
        "tags": [],
    }
    node_patch = repo._make_patch(
        operation="replace_nodes",
        target="memory/nodes.jsonl",
        payload={"nodes": [node]},
        reason="replace nodes through apply_many",
    )
    edge_patch = repo._make_patch(
        operation="replace_edges",
        target="memory/edges.jsonl",
        payload={"edges": []},
        reason="replace edges through apply_many",
    )

    node_patch_id = store.propose(node_patch)
    edge_patch_id = store.propose(edge_patch)

    assert store.apply_many([node_patch_id, edge_patch_id])
    events = repo.get_events()
    assert [event["event"] for event in events[:2]] == [
        "memory.patch.replace_nodes",
        "memory.patch.replace_edges",
    ]
    patch_status = {patch.id: patch.status for patch in repo.get_patches()}
    assert patch_status[node_patch_id] == "applied"
    assert patch_status[edge_patch_id] == "applied"
