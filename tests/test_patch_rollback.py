import json
from pathlib import Path

from memory_os.core.config import MemoryOSConfig
from memory_os.core.patch import RelationPatch, RelationPatchStore
from memory_os.core.repository import MemoryRepository
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.core.disk_guard import DiskGuard


def _config(root: Path) -> MemoryOSConfig:
    (root / "memory").mkdir()
    (root / "agent_context").mkdir()
    (root / "memory_os.config.json").write_text(
        json.dumps({"version": "0.1", "memory_dir": "memory", "db_path": "memory/memory_os.db"}),
        encoding="utf-8",
    )
    return MemoryOSConfig(config_path=str(root / "memory_os.config.json"))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_patch_store_rollback_restores_previous_node_state(tmp_path):
    config = _config(tmp_path)
    storage = FileSystemMemoryStorage()
    repo = MemoryRepository(storage, config)
    store = RelationPatchStore(repo)

    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [{"id": "fact:existing", "type": "fact", "summary": "original", "evidence": [], "status": "verified"}],
    )
    _write_jsonl(config.memory_dir / "edges.jsonl", [])
    _write_jsonl(config.memory_dir / "events.jsonl", [])

    patch = RelationPatch(
        operation="upsert_node",
        source="",
        target="fact:new",
        type="fact",
        domain="",
        confidence=1.0,
        evidence=[],
        reason="add a new node",
        created_by_protocol=0,
        required_verification_protocol=0,
        payload={
            "node": {
                "id": "fact:new",
                "type": "fact",
                "summary": "temporary",
                "evidence": [],
                "status": "draft",
                "trust": "unverified",
                "related_nodes": [],
                "tags": [],
            }
        },
    )

    patch_id = store.propose(patch)
    assert store.apply(patch_id)
    nodes_after_apply = [row["id"] for row in storage.load_jsonl(config.memory_dir / "nodes.jsonl")]
    assert "fact:new" in nodes_after_apply

    assert store.rollback(patch_id)
    nodes_after_rollback = [row["id"] for row in storage.load_jsonl(config.memory_dir / "nodes.jsonl")]
    assert "fact:new" not in nodes_after_rollback
    assert nodes_after_rollback == ["fact:existing"]

    events = storage.load_jsonl(config.memory_dir / "events.jsonl")
    rollback_events = [e for e in events if e.get("event") == "memory.patch.rolled_back"]
    assert rollback_events and rollback_events[-1].get("timestamp")


def test_patch_store_rollback_restores_from_archived_snapshot(tmp_path):
    config = _config(tmp_path)
    storage = FileSystemMemoryStorage()
    repo = MemoryRepository(storage, config)
    store = RelationPatchStore(repo)

    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [{"id": "fact:existing", "type": "fact", "summary": "original", "evidence": [], "status": "verified"}],
    )
    _write_jsonl(config.memory_dir / "edges.jsonl", [])
    _write_jsonl(config.memory_dir / "events.jsonl", [])

    patch = RelationPatch(
        operation="upsert_node",
        source="",
        target="fact:new",
        type="fact",
        domain="",
        confidence=1.0,
        evidence=[],
        reason="add a new node",
        created_by_protocol=0,
        required_verification_protocol=0,
        payload={
            "node": {
                "id": "fact:new",
                "type": "fact",
                "summary": "temporary",
                "evidence": [],
                "status": "draft",
                "trust": "unverified",
                "related_nodes": [],
                "tags": [],
            }
        },
    )

    patch_id = store.propose(patch)
    assert store.apply(patch_id)
    compact_result = DiskGuard(config).compact_patches(dry_run=False)
    assert compact_result["rollback_archived_records"] == 1

    reloaded_store = RelationPatchStore(repo)
    assert reloaded_store.rollback(patch_id)
    nodes_after_rollback = [row["id"] for row in storage.load_jsonl(config.memory_dir / "nodes.jsonl")]
    assert "fact:new" not in nodes_after_rollback
    assert nodes_after_rollback == ["fact:existing"]
