"""Tests for Universal Undo Command (memory_os undo)."""

import json
import argparse
from pathlib import Path
import pytest

from memory_os.core.config import MemoryOSConfig
from memory_os.core.patch import RelationPatch, RelationPatchStore
from memory_os.core.repository import MemoryRepository
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.modules.undo_service import UndoService
from memory_os.cli_groups.system_cmds import cmd_undo


def test_undo_service_no_target(tmp_path: Path):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text('{"version": "0.1"}', encoding="utf-8")
    config = MemoryOSConfig(config_path=str(cfg_path))
    service = UndoService(config)
    res = service.undo()
    assert res["ok"] is False
    assert "No revertible" in res["error"]


def test_undo_service_dry_run(tmp_path: Path):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text('{"version": "0.1"}', encoding="utf-8")
    config = MemoryOSConfig(config_path=str(cfg_path))
    storage = FileSystemMemoryStorage()
    repo = MemoryRepository(storage, config)
    patch_store = RelationPatchStore(repo)

    patch = RelationPatch(
        operation="upsert_node",
        source="",
        target="test_node_1",
        type="fact",
        domain="test",
        confidence=1.0,
        evidence=[],
        reason="test patch",
        created_by_protocol=0,
        required_verification_protocol=0,
        payload={"node": {"id": "test_node_1", "type": "fact", "summary": "Initial node"}, "task_id": "task-test-1"},
    )
    p_id = patch_store.propose(patch)
    patch_store.apply(p_id)

    service = UndoService(config, repository=repo)
    res = service.undo(task_id="task-test-1", dry_run=True)

    assert res["ok"] is True
    assert res["dry_run"] is True
    assert p_id in res["patches_rolled_back"]

    retrieved = next((p for p in repo.get_patches() if p.id == p_id), None)
    assert retrieved is not None
    assert retrieved.status == "applied"


def test_undo_service_rollback_execution(tmp_path: Path):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text('{"version": "0.1"}', encoding="utf-8")
    config = MemoryOSConfig(config_path=str(cfg_path))
    storage = FileSystemMemoryStorage()
    repo = MemoryRepository(storage, config)
    patch_store = RelationPatchStore(repo)

    patch = RelationPatch(
        operation="upsert_node",
        source="",
        target="test_node_2",
        type="fact",
        domain="test",
        confidence=1.0,
        evidence=[],
        reason="test patch task-100",
        created_by_protocol=0,
        required_verification_protocol=0,
        payload={"node": {"id": "test_node_2", "type": "fact", "summary": "Node 2"}, "task_id": "task-100"},
    )
    p_id = patch_store.propose(patch)
    patch_store.apply(p_id)

    service = UndoService(config, repository=repo)
    res = service.undo(task_id="task-100", dry_run=False)

    assert res["ok"] is True
    assert res["dry_run"] is False
    assert p_id in res["patches_rolled_back"]

    retrieved = next((p for p in repo.get_patches() if p.id == p_id), None)
    assert retrieved is not None
    assert retrieved.status == "rolled_back"

    events = repo.get_events()
    assert any(e.get("event") == "memory.undo" for e in events)


def test_undo_service_dirty_git_workspace(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text('{"version": "0.1"}', encoding="utf-8")
    config = MemoryOSConfig(config_path=str(cfg_path))
    service = UndoService(config)

    monkeypatch.setattr(service, "_is_git_workspace_clean", lambda: False)
    monkeypatch.setattr(service, "_resolve_target_task_id", lambda: "task-dirty")

    res = service.undo(task_id="task-dirty", dry_run=False)
    assert res["ok"] is True
    assert res["git_clean"] is False
    assert res["git_reverted"] is False


def test_cmd_undo_cli(tmp_path: Path, capsys):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text('{"version": "0.1"}', encoding="utf-8")
    config = MemoryOSConfig(config_path=str(cfg_path))
    storage = FileSystemMemoryStorage()
    repo = MemoryRepository(storage, config)
    patch_store = RelationPatchStore(repo)

    patch = RelationPatch(
        operation="upsert_node",
        source="",
        target="cli_node",
        type="fact",
        domain="cli",
        confidence=1.0,
        evidence=[],
        reason="cli task",
        created_by_protocol=0,
        required_verification_protocol=0,
        payload={"node": {"id": "cli_node", "type": "fact", "summary": "CLI node"}, "task_id": "task-cli"},
    )
    p_id = patch_store.propose(patch)
    patch_store.apply(p_id)

    args = argparse.Namespace(task_id="task-cli", dry_run=True, json=True)
    exit_code = cmd_undo(args, config)

    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["dry_run"] is True
    assert p_id in data["patches_rolled_back"]
