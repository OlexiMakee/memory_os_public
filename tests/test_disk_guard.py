import argparse
import json
from pathlib import Path

from memory_os.cli import cmd_resources
from memory_os.core.config import MemoryOSConfig
from memory_os.core.disk_guard import DiskGuard
from memory_os.core.storage_tier import StorageTierAdvisor


def make_resource_root(tmp_path: Path, memory_settings: dict) -> MemoryOSConfig:
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "memory" / "nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "edges.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "events.jsonl").write_text("x" * 4096, encoding="utf-8")
    (tmp_path / "memory" / "patches.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps(
            {
                "memory_dir": "memory",
                "db_path": "memory/memory_os.db",
                "memory": memory_settings,
                "resources": {
                    "min_free_disk_mb": 0,
                    "max_sqlite_db_mb": 1024,
                    "max_sqlite_wal_mb": 1024,
                    "max_jsonl_total_mb": 1024,
                    "max_observed_growth_mb_per_hour": 1024,
                },
            }
        ),
        encoding="utf-8",
    )
    return MemoryOSConfig(str(tmp_path / "memory_os.config.json"))


def test_disk_guard_tracks_events_jsonl_soft_limit(tmp_path):
    config = make_resource_root(tmp_path, {"events_soft_limit_mb": 0.001})

    snapshot = DiskGuard(config).snapshot()

    assert snapshot.events_jsonl_mb > snapshot.events_soft_limit_mb
    assert snapshot.events_soft_limit_exceeded is True
    assert snapshot.level == "hot"
    assert snapshot.to_dict()["events_jsonl_mb"] == snapshot.events_jsonl_mb
    assert snapshot.to_dict()["events_soft_limit_mb"] == 0.001


def test_disk_guard_tracks_patches_jsonl_soft_limit(tmp_path):
    config = make_resource_root(tmp_path, {"patches_soft_limit_mb": 0.001})
    (tmp_path / "memory" / "patches.jsonl").write_text("x" * 4096, encoding="utf-8")

    snapshot = DiskGuard(config).snapshot()

    assert snapshot.patches_jsonl_mb > snapshot.patches_soft_limit_mb
    assert snapshot.patches_soft_limit_exceeded is True
    assert snapshot.to_dict()["patches_jsonl_mb"] == snapshot.patches_jsonl_mb
    assert snapshot.to_dict()["patches_soft_limit_mb"] == 0.001


def test_storage_tier_advisor_exposes_events_jsonl_signal(tmp_path):
    config = make_resource_root(tmp_path, {"events_soft_limit_mb": 0.001})

    assessment = StorageTierAdvisor(config, thresholds={"db_mb_tier2": 1024, "wal_mb_tier2": 1024}).assess()

    assert assessment.tier == "sqlite"
    assert assessment.signals["events_soft_limit_exceeded"] is True
    assert assessment.signals["events_jsonl_mb"] > assessment.signals["events_soft_limit_mb"]
    assert any("archive rotation" in reason for reason in assessment.reasons)


def test_storage_tier_advisor_exposes_patches_jsonl_signal(tmp_path):
    config = make_resource_root(tmp_path, {"patches_soft_limit_mb": 0.001})
    (tmp_path / "memory" / "patches.jsonl").write_text("x" * 4096, encoding="utf-8")

    assessment = StorageTierAdvisor(config, thresholds={"db_mb_tier2": 1024, "wal_mb_tier2": 1024}).assess()

    assert assessment.signals["patches_soft_limit_exceeded"] is True
    assert assessment.signals["patches_jsonl_mb"] > assessment.signals["patches_soft_limit_mb"]
    assert any("patches.jsonl" in reason for reason in assessment.reasons)


def test_resources_snapshot_prints_events_jsonl_advisory(tmp_path, capsys):
    config = make_resource_root(tmp_path, {"events_soft_limit_mb": 0.001})
    args = argparse.Namespace(resources_action="snapshot", format="text")

    exit_code = cmd_resources(args, config)
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Events log" in output
    assert "archive rotation advised" in output
    assert "events.jsonl is the audit source of truth" in output


def test_resources_snapshot_prints_patches_jsonl_advisory(tmp_path, capsys):
    config = make_resource_root(tmp_path, {"patches_soft_limit_mb": 0.001})
    (tmp_path / "memory" / "patches.jsonl").write_text("x" * 4096, encoding="utf-8")
    args = argparse.Namespace(resources_action="snapshot", format="text")

    exit_code = cmd_resources(args, config)
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Patch audit log" in output
    assert "archive compaction advised" in output
    assert "use 'memory_os resources compact'" in output


def test_resources_compact_archives_superseded_patch_rows(tmp_path):
    config = make_resource_root(tmp_path, {"patches_soft_limit_mb": 0.001})
    patches_path = tmp_path / "memory" / "patches.jsonl"
    patches_path.write_text(
        "\n".join([
            json.dumps({"id": "p1", "status": "pending"}),
            json.dumps({"id": "p1", "status": "applied"}),
            json.dumps({"id": "p2", "status": "pending"}),
            json.dumps({"id": "p2", "status": "rolled_back"}),
        ]) + "\n",
        encoding="utf-8",
    )

    result = DiskGuard(config).compact_patches(dry_run=False)
    kept = [json.loads(line) for line in patches_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    archive_path = Path(result["archive_path"])
    archived = [json.loads(line) for line in archive_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert result["ok"] is True
    assert result["archived_records"] == 2
    assert kept == [{"id": "p1", "status": "applied"}, {"id": "p2", "status": "rolled_back"}]
    assert archived == [{"id": "p1", "status": "pending"}, {"id": "p2", "status": "pending"}]


def test_resources_compact_externalizes_rollback_snapshot(tmp_path):
    config = make_resource_root(tmp_path, {"patches_soft_limit_mb": 0.001})
    patches_path = tmp_path / "memory" / "patches.jsonl"
    patches_path.write_text(
        json.dumps({
            "id": "p1",
            "status": "applied",
            "payload": {"_rollback": {"nodes": [{"id": "fact:existing"}]}},
        }) + "\n",
        encoding="utf-8",
    )

    result = DiskGuard(config).compact_patches(dry_run=False)
    kept = [json.loads(line) for line in patches_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rollback_archive_path = Path(result["rollback_archive_path"])
    archived = [json.loads(line) for line in rollback_archive_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert result["ok"] is True
    assert result["rollback_archived_records"] == 1
    assert "_rollback" not in kept[0]["payload"]
    assert kept[0]["payload"]["_rollback_archived"] is True
    assert archived == [{"patch_id": "p1", "rollback": {"nodes": [{"id": "fact:existing"}]}}]


def test_resource_compaction_has_no_wal_checkpoint_action(tmp_path):
    config = make_resource_root(tmp_path, {})
    guard = DiskGuard(config)

    result = guard.compact(dry_run=True)

    assert result["ok"] is True
    assert "checkpoint" not in result
    assert not hasattr(guard, "checkpoint_sqlite")
