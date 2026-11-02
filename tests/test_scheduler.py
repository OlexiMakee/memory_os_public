import json
from pathlib import Path

from memory_os.core.config import MemoryOSConfig
from memory_os.core.scheduler import HardwareScheduler
from memory_os.modules.compactor import MemoryCompactor


def _make_config(tmp_path: Path, resource_mode: str = "normal") -> MemoryOSConfig:
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({
            "version": "0.1",
            "memory_dir": "memory",
            "resource_mode": resource_mode,
            "capsules_file": "agent_context/task_capsules.jsonl",
            "db_path": "memory/memory_os.db",
        }),
        encoding="utf-8",
    )
    return MemoryOSConfig(config_path=str(tmp_path / "memory_os.config.json"))


def test_hardware_scheduler_worker_limits_follow_resource_mode(monkeypatch):
    monkeypatch.setattr("memory_os.core.scheduler.multiprocessing.cpu_count", lambda: 8)

    assert HardwareScheduler.cpu_worker_limit("quiet") == 1
    assert HardwareScheduler.cpu_worker_limit("normal") == 4
    assert HardwareScheduler.cpu_worker_limit("max") == 8


def test_hardware_scheduler_execute_parallel_uses_mode_limit(monkeypatch):
    monkeypatch.setattr("memory_os.core.scheduler.multiprocessing.cpu_count", lambda: 8)
    scheduler = HardwareScheduler(mode="normal")

    observed = {}
    original = HardwareScheduler.execute_parallel

    def wrapped(self, func, items, max_workers=None):
        observed["self_max_workers"] = self.max_workers
        observed["override"] = max_workers
        return original(self, func, items, max_workers=max_workers)

    monkeypatch.setattr(HardwareScheduler, "execute_parallel", wrapped)

    result = scheduler.execute_parallel(lambda item: item * 2, [1, 2, 3])

    assert result == [2, 4, 6]
    assert observed["self_max_workers"] == 4
    assert observed["override"] is None


def test_compactor_panel_vote_uses_scheduler_limit(tmp_path, monkeypatch):
    config = _make_config(tmp_path, resource_mode="quiet")
    compactor = MemoryCompactor(config=config)
    observed = {}

    def fake_execute_parallel(self, func, items, max_workers=None):
        observed["mode"] = self.mode
        observed["max_workers"] = max_workers
        return [func(item) for item in items]

    monkeypatch.setattr(HardwareScheduler, "execute_parallel", fake_execute_parallel)
    monkeypatch.setattr(
        compactor,
        "_run_critic",
        lambda critic_idx, nodes, provider, model: [
            {"node_id": nodes[0]["id"], "verdict": "approve", "reason": "ok"}
        ],
    )

    surviving, votes = compactor._panel_vote([{"id": "node-1", "summary": "x"}], None, None)

    assert observed["mode"] == "quiet"
    assert observed["max_workers"] == 1
    assert surviving == [{"id": "node-1", "summary": "x"}]
    assert len(votes) == 3
